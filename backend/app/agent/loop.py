"""Tool-use loop over the Anthropic SDK (Spec 03, ADR-010).

Builds the request → stop_reason → tool_result cycle by hand on the Anthropic
Python SDK. Client tools (get_market_data, submit_dossier) are dispatched here;
server tools (web_search, web_fetch, code_execution) are resolved by Anthropic
and arrive already executed in the response content.

Turn limits are provisional (ADR-007): SOFT_TURN_LIMIT triggers a wrap-up nudge;
HARD_TURN_LIMIT cuts the loop unconditionally. Recalibrate against the evaluation
set in block-H.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anthropic

from app.config import settings
from app.dossier.models import CompanyDossier
from app.guardrails.classifier import classify_dossier
from app.guardrails.injection import wrap_external_content
from app.observability.tracer import get_tracer
from app.tools.client import ToolResult, dispatch_client_tool, is_terminal_tool
from app.tools.inventory import AGENT_MODEL, TOOLS

logger = logging.getLogger(__name__)

# Provisional turn limits (ADR-007). Read at call time from settings so that
# tests can patch settings.agent_max_turns without reloading the module, and
# so that AGENT_MAX_TURNS changes in .env take effect without a restart.
# Kept as module-level aliases for backward-compat imports in test_loop.py.
HARD_TURN_LIMIT: int = settings.agent_max_turns   # used by tests for assertions
SOFT_TURN_LIMIT: int = max(1, HARD_TURN_LIMIT - 5)  # used by tests for assertions

# Sonnet 4.6 rate card (USD per million tokens). Verify against the current card.
_COST_PER_MTOK_IN = 3.00
_COST_PER_MTOK_OUT = 15.00
_COST_PER_MTOK_CACHE_WRITE = 3.75   # cache_creation_input_tokens (125 % of input)
_COST_PER_MTOK_CACHE_READ = 0.30    # cache_read_input_tokens (10 % of input)

_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "system_prompt_v1.md"
)

_WRAP_UP_MESSAGE = (
    "You are approaching the turn limit for this research session. "
    "Stop collecting more information and call submit_dossier now with "
    "what you have gathered so far."
)


@dataclass
class LoopResult:
    """Outcome of a single research execution."""

    dossier: CompanyDossier | None
    turns: int
    cost_usd: float
    terminated_by: str  # "submit_dossier" | "end_turn" | "hard_limit" | "submit_dossier_failed" | "budget_exceeded" | "guardrail_blocked"


def _load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_tools_with_cache(tools: list[dict] | None = None) -> list[dict]:
    """Return *tools* (or the default TOOLS) with a cache breakpoint on the last entry.

    Keeping all tools stable between turns lets Anthropic serve the tool
    definitions from cache on every turn after the first.
    """
    tool_list = list(tools if tools is not None else TOOLS)
    last = dict(tool_list[-1])
    last["cache_control"] = {"type": "ephemeral"}
    return tool_list[:-1] + [last]


def _estimate_cost(usage: anthropic.types.Usage) -> tuple[float, dict[str, float]]:
    """Return (total_usd, per_dimension_breakdown) using Anthropic's rate card.

    The breakdown uses the same keys as the usage_details we send to Langfuse so
    that cost_details can fully suppress model-based pricing in Langfuse.
    """
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    breakdown: dict[str, float] = {
        "input": usage.input_tokens * _COST_PER_MTOK_IN / 1_000_000,
        "output": usage.output_tokens * _COST_PER_MTOK_OUT / 1_000_000,
        "cache_creation_input_tokens": cache_write * _COST_PER_MTOK_CACHE_WRITE / 1_000_000,
        "cache_read_input_tokens": cache_read * _COST_PER_MTOK_CACHE_READ / 1_000_000,
    }
    return sum(breakdown.values()), breakdown


def _extract_client_tool_uses(content: list) -> list:
    """Return tool_use blocks only (client tools).

    Server tools (web_search, web_fetch, code_execution) produce server_tool_use
    blocks which are resolved by Anthropic and require no client action.
    """
    return [b for b in content if getattr(b, "type", None) == "tool_use"]


def _execute_tools_parallel(tool_uses: list) -> dict[str, ToolResult]:
    """Execute all client tool calls concurrently and return id → ToolResult."""
    if not tool_uses:
        return {}

    results: dict[str, ToolResult] = {}

    def _run(tu) -> tuple[str, ToolResult]:
        logger.debug("Dispatching tool %s (id=%s)", tu.name, tu.id)
        return tu.id, dispatch_client_tool(tu.name, tu.input)

    with ThreadPoolExecutor(max_workers=len(tool_uses)) as executor:
        futures = {executor.submit(_run, tu): tu for tu in tool_uses}
        for future in as_completed(futures):
            tu_id, result = future.result()
            results[tu_id] = result

    return results


def run(
    ticker: str,
    *,
    max_turns: int | None = None,
    on_turn: Callable[[int, str, list], None] | None = None,
    tools: list[dict] | None = None,
    temperature: float | None = None,
) -> LoopResult:
    """Run the research loop for *ticker* and return a LoopResult.

    Parameters
    ----------
    ticker:
        Exchange ticker symbol to research (e.g. "AAPL", "SAP.DE").
    max_turns:
        Override the hard turn limit. Defaults to ``settings.agent_max_turns``
        (read at call time, not at import time). Tests pass a small value here
        so they don't depend on the baked module-level constant.
    on_turn:
        Optional callback invoked after every turn with
        ``(turn_number, stop_reason, content_blocks)``. The serving layer
        uses this for SSE streaming; the CLI ignores it.
    tools:
        Override the tool inventory. When ``None`` (default) the production
        TOOLS list is used. The eval runner passes EVAL_TOOLS to replace
        server tools with deterministic client-tool equivalents (Spec 07).
    temperature:
        Model sampling temperature. ``None`` leaves the API default (1.0).
        The eval runner passes 0.0 to reduce between-run variance.
    """
    # Read limits at call time so runtime patches to settings are honoured.
    hard_limit = max_turns if max_turns is not None else settings.agent_max_turns
    soft_limit = max(1, hard_limit - 5)

    # api_key from settings (loaded from the repo-root .env via pydantic-settings).
    # Falls back to the ANTHROPIC_API_KEY env var if settings.anthropic_api_key is empty,
    # which is the default SDK behaviour when api_key=None.
    # timeout per API request (ADR-007, Spec 04): agent and classifier use separate
    # clients with different timeout profiles; agent uses agent_timeout_s.
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key or None,
        timeout=settings.agent_timeout_s,
        max_retries=settings.agent_max_retries,
    )
    tracer = get_tracer()

    system_prompt = _load_system_prompt()
    system_with_cache = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    _tools = _build_tools_with_cache(tools)

    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Research the company with ticker symbol: {ticker}",
        }
    ]

    total_cost = 0.0
    budget_usd = settings.agent_budget_usd
    dossier: CompanyDossier | None = None
    terminated_by = "hard_limit"
    turn = 0
    total_tool_calls = 0
    total_tool_errors = 0
    # ADR-006: allow exactly one retry when submit_dossier validation fails.
    submit_attempts = 0

    with tracer.start(ticker) as run_trace:
        for turn in range(1, hard_limit + 1):
            # Hard budget cut (ADR-007, Spec 04): placed BEFORE the API call so that
            # the previous turn's tools (including submit_dossier) are always dispatched
            # before the cap is enforced. A completed dossier is never discarded.
            # On turn 1 total_cost=0 so this never fires before the first response.
            if total_cost >= budget_usd:
                logger.warning(
                    "Budget cap $%.2f exceeded (spent $%.4f); stopping before turn %d",
                    budget_usd,
                    total_cost,
                    turn,
                )
                terminated_by = "budget_exceeded"
                break

            # Soft limit: inject a wrap-up message so the model finishes soon.
            if turn == soft_limit:
                logger.info("Soft turn limit reached — injecting wrap-up message")
                messages.append({"role": "user", "content": _WRAP_UP_MESSAGE})

            logger.info("Turn %d / %d", turn, hard_limit)

            create_kwargs: dict = dict(
                model=AGENT_MODEL,
                max_tokens=8192,
                system=system_with_cache,
                tools=_tools,
                messages=messages,
            )
            if temperature is not None:
                create_kwargs["temperature"] = temperature
            response = client.messages.create(**create_kwargs)

            turn_cost, cost_breakdown = _estimate_cost(response.usage)
            total_cost += turn_cost
            run_trace.record_turn(turn, response, turn_cost, cost_breakdown)

            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_created = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            logger.debug(
                "Turn %d: stop_reason=%s tokens_in=%d tokens_out=%d "
                "cache_read=%d cache_created=%d cost=%.4f",
                turn,
                response.stop_reason,
                response.usage.input_tokens,
                response.usage.output_tokens,
                cache_read,
                cache_created,
                turn_cost,
            )

            if on_turn:
                on_turn(turn, response.stop_reason, response.content)

            if response.stop_reason == "end_turn":
                terminated_by = "end_turn"
                break

            if response.stop_reason == "tool_use":
                tool_uses = _extract_client_tool_uses(response.content)
                results = _execute_tools_parallel(tool_uses)

                total_tool_calls += len(tool_uses)
                total_tool_errors += sum(
                    1 for r in results.values() if "error" in r.json_response
                )

                # Append the full assistant turn (includes server_tool_use blocks).
                messages.append({"role": "assistant", "content": response.content})

                # Only send tool_result when there are client tool calls.
                # If stop_reason=="tool_use" with zero client tool_use blocks (all
                # server-side), skipping the user message avoids an empty content:[]
                # which the Anthropic API rejects with a 400.
                if tool_uses:
                    # Untrusted external content enters the context wrapped in
                    # explicit delimiters and sanitized against boundary forgery
                    # (layer L1, indirect prompt injection defense; spec 04/09).
                    tool_result_content = [
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": wrap_external_content(
                                tu.name, json.dumps(results[tu.id].json_response)
                            ),
                        }
                        for tu in tool_uses
                    ]
                    messages.append({"role": "user", "content": tool_result_content})

                # Detect successful dossier submission (ADR-006).
                for tu in tool_uses:
                    if is_terminal_tool(tu.name):
                        result = results[tu.id]
                        submit_attempts += 1
                        if result.success and result.dossier is not None:
                            # Overwrite loop-authoritative fields. The model
                            # self-reports these but its estimates are unreliable;
                            # the loop has the ground truth for all four.
                            candidate = result.dossier.model_copy(
                                update={
                                    "generated_at": datetime.now(tz=timezone.utc),
                                    "run": result.dossier.run.model_copy(
                                        update={
                                            "model": AGENT_MODEL,
                                            "cost_usd": total_cost,
                                            "turns": turn,
                                        }
                                    ),
                                }
                            )
                            # Output guardrail (layer L3, spec 04/09): a schema-valid
                            # dossier can still carry an injected verdict or leaked
                            # prompt. Classify before releasing; block if unsafe.
                            verdict = classify_dossier(
                                candidate.model_dump(mode="json")
                            )
                            run_trace.record_guardrail(verdict)
                            if verdict.allowed:
                                dossier = candidate
                                terminated_by = "submit_dossier"
                            else:
                                logger.warning(
                                    "Output guardrail blocked dossier (%s): %s",
                                    verdict.layer,
                                    verdict.reason,
                                )
                                dossier = None
                                terminated_by = "guardrail_blocked"
                        elif submit_attempts > 1:
                            # ADR-006: one retry allowed; persistent failure stops loop.
                            logger.warning(
                                "submit_dossier failed validation on retry %d; "
                                "stopping loop",
                                submit_attempts,
                            )
                            terminated_by = "submit_dossier_failed"
                        else:
                            logger.warning(
                                "submit_dossier failed validation; model will retry"
                            )
                        break  # only one submit_dossier per turn expected

                if terminated_by in (
                    "submit_dossier",
                    "submit_dossier_failed",
                    "guardrail_blocked",
                ):
                    break

            elif response.stop_reason == "max_tokens":
                logger.warning("Turn %d hit max_tokens; continuing loop", turn)
                messages.append({"role": "assistant", "content": response.content})

        else:
            # for-else: loop exhausted hard_limit without a break.
            logger.warning(
                "Hard turn limit %d reached without termination", hard_limit
            )
            terminated_by = "hard_limit"

        run_trace.finish(
            terminated_by, total_cost, turn, total_tool_calls, total_tool_errors
        )

    return LoopResult(
        dossier=dossier,
        turns=turn,
        cost_usd=total_cost,
        terminated_by=terminated_by,
    )
