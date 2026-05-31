"""Tool inventory declaration (Spec 02).

This module declares *what* tools the agent is given, not *how* they run. No tool
logic lives here: ``get_market_data`` (yfinance) and ``submit_dossier`` are
implemented in Fase 2 (block-C/D); the server tools (``web_search``, ``web_fetch``,
code execution) are resolved by Anthropic and only declared by type and version.

Tool ``description`` strings are written for the model. They are kept inline here
as the contract baseline and get externalized to versioned files under ``prompts/``
when the loop is built (Spec 02 acceptance criteria, block-C).

Versions are anchored per ADR:
- ``web_search_20260209``  (ADR-003)
- ``web_fetch_20260209``   (ADR-005)
- ``code_execution_20260120`` (ADR-011)
"""

from __future__ import annotations

from app.dossier.models import dossier_json_schema

# Agent model (ADR-001, ADR-010).
# claude-sonnet-4-6 is the current stable alias for the Sonnet 4.6 tier.
# Anthropic has not released a dated snapshot for this model yet; pin to the
# dated version (e.g. "claude-sonnet-4-6-YYYYMMDD") when one becomes available.
# Guardrail classifier uses the dated Haiku 4.5 snapshot (pinned 2025-10-01).
AGENT_MODEL = "claude-sonnet-4-6"
GUARDRAIL_MODEL = "claude-haiku-4-5-20251001"

# --- Server tools (resolved by Anthropic; no client implementation) ----------

# web_search is billed per use; max_uses caps cost per execution (ADR-003 + ADR-007).
# Provisional value: recalibrated against the evaluation set in block-E/H.
WEB_SEARCH_MAX_USES = 5

WEB_SEARCH_TOOL: dict = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": WEB_SEARCH_MAX_USES,
}

WEB_FETCH_TOOL: dict = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
}

CODE_EXECUTION_TOOL: dict = {
    "type": "code_execution_20260120",
    "name": "code_execution",
}

# --- Client tools (schema only; implementation in block-C/D) -----------------

GET_MARKET_DATA_TOOL: dict = {
    "name": "get_market_data",
    "description": (
        "Get structured, point-in-time market data for a listed company by its "
        "ticker symbol: price, currency, daily change, market cap, P/E, forward "
        "P/E, EPS, dividend yield, and 52-week range. Use this for any precise "
        "numeric market figure instead of web search, which returns stale or "
        "inconsistent prose. Fields with no available datum come back as null; "
        "never infer them. On provider failure returns "
        '{"error": ..., "recoverable": true}.'
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "The exchange ticker symbol of the company, e.g. 'AAPL' or "
                    "'SAP.DE'."
                ),
            },
        },
        "required": ["ticker"],
    },
}

SUBMIT_DOSSIER_TOOL: dict = {
    "name": "submit_dossier",
    "description": (
        "Submit the final, completed CompanyDossier to end the research. Call "
        "this exactly once, when you have gathered enough information: market "
        "data, a business overview, key facts, and recent news, each qualitative "
        "fact citing a source listed in 'sources'. Calling this tool ends the "
        "loop; do not call any other tool afterwards."
    ),
    # The dossier contract is the tool input schema (ADR-006). Citation and
    # computed-provenance rules are enforced by Pydantic on validation after the
    # call, not by this schema.
    "input_schema": dossier_json_schema(),
}

# Full inventory registered with the Anthropic client (Spec 02). Server tools and
# client tools coexist in the same tools=[...] list.
TOOLS: list[dict] = [
    GET_MARKET_DATA_TOOL,
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    CODE_EXECUTION_TOOL,
    SUBMIT_DOSSIER_TOOL,
]
