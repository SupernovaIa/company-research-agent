"""FastAPI application: health probe + /research endpoint with SSE streaming.

Rate limiting (Spec 04, ADR-007): slowapi middleware enforces
settings.rate_limit_per_minute requests per IP. The limiter uses in-memory
state by default; swap the storage backend for Redis in production (Upstash).

SSE streaming (Spec 06, block-G): /research streams one ``turn`` event per
loop turn and a final ``done`` or ``error`` event with the full dossier.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)

_limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="company-research-agent",
    description="Financial research agent with tool use. Returns a structured, citable dossier.",
    version="0.1.0",
)
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_RATE_LIMIT = f"{settings.rate_limit_per_minute}/minute"


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 with a static payload."""
    return {"status": "ok"}


async def _research_stream(ticker: str) -> AsyncGenerator[str, None]:
    """Run the research loop in a thread pool and yield SSE events.

    Yields:
        ``event: turn``  — one per loop turn; data: {turn, stop_reason, tools}.
        ``event: done``  — agent submitted a valid dossier; data: {dossier, terminated_by, cost_usd, turns}.
        ``event: error`` — two payload shapes:
            controlled failure (budget_exceeded, hard_limit, guardrail_blocked, …):
                data: {terminated_by, cost_usd, turns}
            unhandled exception (import error, API crash before first turn, …):
                data: {error: "internal error"}
    """
    from app.agent.loop import run

    current_loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def on_turn(turn: int, stop_reason: str, content: list) -> None:
        tool_names = [b.name for b in content if getattr(b, "type", None) == "tool_use"]
        payload = {"turn": turn, "stop_reason": stop_reason, "tools": tool_names}
        current_loop.call_soon_threadsafe(queue.put_nowait, ("turn", payload))

    async def _run_in_thread() -> None:
        try:
            result = await asyncio.to_thread(run, ticker, on_turn=on_turn)
            current_loop.call_soon_threadsafe(queue.put_nowait, ("done", result))
        except Exception:
            logger.exception("Research loop raised unexpectedly for ticker=%s", ticker)
            current_loop.call_soon_threadsafe(
                queue.put_nowait, ("exc", {"error": "internal error"})
            )

    task = asyncio.create_task(_run_in_thread())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "turn":
                yield f"event: turn\ndata: {json.dumps(payload)}\n\n"
            elif kind == "done":
                result = payload
                if result.dossier is not None:
                    body = {
                        "dossier": result.dossier.model_dump(mode="json"),
                        "terminated_by": result.terminated_by,
                        "cost_usd": result.cost_usd,
                        "turns": result.turns,
                    }
                else:
                    body = {
                        "terminated_by": result.terminated_by,
                        "cost_usd": result.cost_usd,
                        "turns": result.turns,
                    }
                event = "done" if result.dossier is not None else "error"
                yield f"event: {event}\ndata: {json.dumps(body)}\n\n"
                break
            elif kind == "exc":
                yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                break
    finally:
        # Cancel the background task so `await task` returns promptly when
        # the client disconnects. The underlying thread (asyncio.to_thread)
        # cannot be interrupted mid-call, but cancelling the task prevents
        # the finally block from blocking until the full agent run finishes.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.post("/research")
@_limiter.limit(_RATE_LIMIT)
async def research(request: Request, body: dict):  # noqa: ANN201 — mixed Response types
    """Run the research agent for *ticker* and stream loop events as SSE.

    Request body: ``{"ticker": "AAPL"}``

    Stream events:
        ``turn``  — one per loop turn; includes stop_reason and tool names called.
        ``done``  — final event on success; includes the full CompanyDossier.
        ``error`` — final event on agent failure or crash; see ``_research_stream`` for
                    the two distinct payload shapes.

    Note on HTTP status: SSE always returns **HTTP 200** once the stream opens,
    even when the agent fails. Agent-level failures (budget_exceeded, hard_limit,
    guardrail_blocked, …) are signalled via ``event: error`` in the stream body.
    Monitor agent health via Langfuse completion rate (``scripts/metrics.py``),
    not via HTTP status codes.
    """
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return JSONResponse(status_code=422, content={"error": "ticker is required"})

    return StreamingResponse(
        _research_stream(ticker),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
