"""Langfuse v4 instrumentation for the research loop (ADR-008).

A null-safe wrapper: if Langfuse keys are absent the tracer does nothing and
the loop runs without instrumentation. Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
and LANGFUSE_BASE_URL to enable tracing.

Reads credentials from ``app.config.settings`` (loaded from the repo-root .env).

Langfuse v4 API change: ``lf.trace()`` no longer exists. Tracing uses
``lf.start_observation(as_type="span")`` for the root span (= trace) and
``span.start_observation(as_type="generation")`` for nested LLM turns.

Usage inside the loop::

    tracer = get_tracer()
    with tracer.start(ticker) as run_trace:
        for turn in ...:
            run_trace.record_turn(turn, response, cost_usd, cost_breakdown)
        run_trace.finish(terminated_by, cost_usd, turns)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


class _RunTrace:
    """One trace for a single research execution (backed by a root Langfuse span)."""

    def __init__(self, lf: Any | None, root_span: Any | None) -> None:
        self._lf = lf
        self._root = root_span

    def record_turn(
        self,
        turn: int,
        response: Any,
        cost_usd: float,
        cost_breakdown: dict[str, float],
    ) -> None:
        if self._root is None:
            return
        try:
            usage = response.usage
            tool_names = [
                b.name
                for b in response.content
                if getattr(b, "type", None) == "tool_use"
            ]
            model_name = getattr(response, "model", "unknown")
            gen = self._root.start_observation(
                name=f"turn_{turn}",
                as_type="generation",
                model=model_name,
                metadata={
                    "stop_reason": response.stop_reason,
                    "turn": turn,
                    "cost_usd": cost_usd,
                    "tool_names": tool_names,
                },
            )
            # cost_details includes every key in usage_details plus "total".
            # The "total" key populates calculatedTotalCost on the observation,
            # which Langfuse sums to compute the trace-level totalCost and drives
            # the "Cost by model" / "Cost by type" dashboard views.
            # Covering all dimension keys overrides any model-definition pricing
            # that Langfuse would otherwise apply.
            gen.update(
                usage_details={
                    "input": usage.input_tokens,
                    "output": usage.output_tokens,
                    "cache_creation_input_tokens": getattr(
                        usage, "cache_creation_input_tokens", 0
                    ),
                    "cache_read_input_tokens": getattr(
                        usage, "cache_read_input_tokens", 0
                    ),
                },
                cost_details=cost_breakdown,
            )
            gen.end()
        except Exception:
            logger.debug("Langfuse record_turn failed", exc_info=True)

    def record_guardrail(self, verdict: Any) -> None:
        """Record the output-guardrail verdict as a nested event on the trace.

        Makes which defense layer acted (heuristic / classifier) visible in the
        trace, so the red-team runner can confirm per-layer blocking (spec 09).
        """
        if self._root is None:
            return
        try:
            ev = self._root.start_observation(
                name="output_guardrail",
                as_type="span",
                metadata={
                    "allowed": verdict.allowed,
                    "layer": verdict.layer,
                    "reason": verdict.reason,
                },
            )
            ev.end()
        except Exception:
            logger.debug("Langfuse record_guardrail failed", exc_info=True)

    def finish(
        self,
        terminated_by: str,
        cost_usd: float,
        turns: int,
        tool_calls: int = 0,
        tool_errors: int = 0,
    ) -> None:
        if self._root is None:
            return
        try:
            self._root.update(
                output={
                    "terminated_by": terminated_by,
                    "total_cost_usd": cost_usd,
                    "total_turns": turns,
                    "tool_calls": tool_calls,
                    "tool_errors": tool_errors,
                }
            )
            self._root.end()
        except Exception:
            logger.debug("Langfuse finish failed", exc_info=True)


class Tracer:
    """Null-safe Langfuse tracer. Initialise once; use start() per execution."""

    def __init__(self) -> None:
        self._lf: Any | None = None
        self._enabled = False

        from app.config import settings

        pk = settings.langfuse_public_key
        sk = settings.langfuse_secret_key
        if pk and sk:
            try:
                from langfuse import Langfuse

                host = settings.langfuse_effective_host
                # Langfuse v4: constructor accepts both base_url and host;
                # base_url is preferred in v4.
                self._lf = Langfuse(public_key=pk, secret_key=sk, base_url=host)
                self._enabled = True
                logger.info("Langfuse tracing enabled (host=%s)", host)
            except ImportError:
                logger.warning(
                    "langfuse not installed; tracing disabled. "
                    "Install with: uv add langfuse"
                )
        else:
            logger.debug(
                "LANGFUSE_PUBLIC_KEY/SECRET_KEY not set; tracing disabled"
            )

    @contextmanager
    def start(self, ticker: str) -> Generator[_RunTrace, None, None]:
        root_span = None
        if self._lf is not None:
            try:
                # v4: start_observation without trace_context creates a new root span (trace).
                root_span = self._lf.start_observation(
                    name="research",
                    as_type="span",
                    input={"ticker": ticker},
                )
            except Exception:
                logger.debug("Langfuse root span creation failed", exc_info=True)

        run_trace = _RunTrace(self._lf, root_span)
        try:
            yield run_trace
        finally:
            if self._lf is not None:
                try:
                    self._lf.flush()
                except Exception:
                    logger.debug("Langfuse flush failed", exc_info=True)

    @property
    def enabled(self) -> bool:
        return self._enabled


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    """Return the process-level Tracer singleton."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def reset_tracer() -> None:
    """Clear the singleton so the next get_tracer() call re-initialises it.

    Intended for test teardown only: prevents a live Langfuse HTTP client
    created in one test from leaking into subsequent tests in the same process.
    """
    global _tracer
    _tracer = None
