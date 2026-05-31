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
from pathlib import Path
from typing import Callable

import anthropic

from app.config import settings
from app.dossier.models import CompanyDossier
from app.observability.tracer import get_tracer
from app.tools.client import ToolResult, dispatch_client_tool, is_terminal_tool
from app.tools.inventory import AGENT_MODEL, TOOLS

logger = logging.getLogger(__name__)

# Provisional turn limits (ADR-007). Derived from settings so they can be
# overridden via AGENT_MAX_TURNS in the .env. Recalibrate against the eval
# set in block-E/H.
HARD_TURN_LIMIT: int = settings.agent_max_turns
SOFT_TURN_LIMIT: int = max(1, HARD_TURN_LIMIT - 5)

# Sonnet 4.6 rate card (USD per million tokens). Verify against the current card.
_COST_PER_MTOK_IN = 3.00
_COST_PER_MTOK_OUT = 15.00

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
    terminated_by: str  # "submit_dossier" | "end_turn" | "hard_limit"


def _load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_tools_with_cache() -> list[dict]:
    """Return the TOOLS list with a cache breakpoint on the last entry.

    Keeping all tools stable between turns lets Anthropic serve the tool
    definitions from cache on every turn after the first.
    """
    tools = list(TOOLS)
    last = dict(tools[-1])
    last["cache_control"] = {"type": "ephemeral"}
    return tools[:-1] + [last]


def _estimate_cost(usage: anthropic.types.Usage) -> float:
    # Cache-read tokens are billed at ~10% of regular input; treat as zero here
    # for a conservative upper bound. Block-E can refine with the actual rate.
    return (
        usage.input_tokens * _COST_PER_MTOK_IN / 1_000_000
        + usage.output_tokens * _COST_PER_MTOK_OUT / 1_000_000
    )


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
    on_turn: Callable[[int, str, list], None] | None = None,
) -> LoopResult:
    """Run the research loop for *ticker* and return a LoopResult.

    Parameters
    ----------
    ticker:
        Exchange ticker symbol to research (e.g. "AAPL", "SAP.DE").
    on_turn:
        Optional callback invoked after every turn with
        ``(turn_number, stop_reason, content_blocks)``. The serving layer
        uses this for SSE streaming; the CLI ignores it.
    """
    # api_key from settings (loaded from the repo-root .env via pydantic-settings).
    # Falls back to the ANTHROPIC_API_KEY env var if settings.anthropic_api_key is empty,
    # which is the default SDK behaviour when api_key=None.
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key or None
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
    tools = _build_tools_with_cache()

    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Research the company with ticker symbol: {ticker}",
        }
    ]

    total_cost = 0.0
    dossier: CompanyDossier | None = None
    terminated_by = "hard_limit"
    turn = 0

    with tracer.start(ticker) as run_trace:
        for turn in range(1, HARD_TURN_LIMIT + 1):
            # Soft limit: inject a wrap-up message so the model finishes soon.
            if turn == SOFT_TURN_LIMIT:
                logger.info("Soft turn limit reached — injecting wrap-up message")
                messages.append({"role": "user", "content": _WRAP_UP_MESSAGE})

            logger.info("Turn %d / %d", turn, HARD_TURN_LIMIT)

            response = client.messages.create(
                model=AGENT_MODEL,
                max_tokens=8192,
                system=system_with_cache,
                tools=tools,
                messages=messages,
            )

            turn_cost = _estimate_cost(response.usage)
            total_cost += turn_cost
            run_trace.record_turn(turn, response, turn_cost)

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

                # Build tool_result content for the next message.
                tool_result_content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(results[tu.id].json_response),
                    }
                    for tu in tool_uses
                ]

                # Append assistant turn (all blocks, including server_tool_use).
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_result_content})

                # Detect successful dossier submission.
                for tu in tool_uses:
                    if is_terminal_tool(tu.name):
                        result = results[tu.id]
                        if result.success and result.dossier is not None:
                            dossier = result.dossier
                            terminated_by = "submit_dossier"
                        else:
                            logger.warning(
                                "submit_dossier failed validation; model will retry"
                            )
                        break  # only one submit_dossier per turn expected

                if terminated_by == "submit_dossier":
                    break

            elif response.stop_reason == "max_tokens":
                logger.warning("Turn %d hit max_tokens; continuing loop", turn)
                messages.append({"role": "assistant", "content": response.content})

        else:
            # for-else: loop exhausted HARD_TURN_LIMIT without a break.
            logger.warning(
                "Hard turn limit %d reached without termination", HARD_TURN_LIMIT
            )
            terminated_by = "hard_limit"

        run_trace.finish(terminated_by, total_cost, turn)

    return LoopResult(
        dossier=dossier,
        turns=turn,
        cost_usd=total_cost,
        terminated_by=terminated_by,
    )
