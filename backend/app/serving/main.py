"""FastAPI application entrypoint.

Block A scope: only the health probe is wired. The /research endpoint and SSE
streaming land in the serving block (see specs/06-serving-metrics.md).
"""

from fastapi import FastAPI

app = FastAPI(
    title="company-research-agent",
    description="Financial research agent with tool use. Returns a structured, citable dossier.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 with a static payload."""
    return {"status": "ok"}
