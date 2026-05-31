"""FastAPI application: health probe + /research endpoint.

Rate limiting (Spec 04, ADR-007): slowapi middleware enforces
settings.rate_limit_per_minute requests per IP. The limiter uses in-memory
state by default; swap the storage backend for Redis in production (Upstash).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings

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


@app.post("/research")
@_limiter.limit(_RATE_LIMIT)
def research(request: Request, body: dict) -> JSONResponse:
    """Run the research agent for a ticker and return the dossier.

    Request body: {"ticker": "AAPL"}

    Returns the CompanyDossier as JSON on success, or an error dict with
    ``terminated_by`` on failure (budget_exceeded, hard_limit, etc.).
    SSE streaming lands in block-G.
    """
    from app.agent.loop import run

    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return JSONResponse(status_code=422, content={"error": "ticker is required"})

    result = run(ticker)

    if result.dossier is not None:
        return JSONResponse(
            content=result.dossier.model_dump(mode="json"),
            status_code=200,
        )

    return JSONResponse(
        status_code=500,
        content={
            "error": "No dossier produced.",
            "terminated_by": result.terminated_by,
            "turns": result.turns,
            "cost_usd": result.cost_usd,
        },
    )
