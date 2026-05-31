"""Client tool dispatch and minimal stub implementations (Spec 03).

Block-C scope: dispatch routing + enough implementation to run the loop end-to-end.
Block-D replaces these stubs with production implementations: yfinance error handling,
guardrails on submit_dossier (retry logic, output classifier), and Langfuse spans.

The distinction between client tools and server tools (ADR-003, ADR-005, ADR-011):
- Client tools  → this module executes them and returns a tool_result.
- Server tools  → Anthropic resolves them; they appear as server_tool_use blocks
                  in the response content but need no action here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.dossier.models import CompanyDossier

logger = logging.getLogger(__name__)

# Name of the tool that terminates the loop (ADR-006).
TERMINAL_TOOL = "submit_dossier"


@dataclass
class ToolResult:
    """Wraps the result of a client tool call.

    json_response is serialized to JSON and returned to the model as tool_result.
    dossier is only set for a successful submit_dossier call; the loop stores it.
    """

    json_response: dict
    dossier: CompanyDossier | None = None

    @property
    def success(self) -> bool:
        return self.json_response.get("success", False)


def is_terminal_tool(name: str) -> bool:
    return name == TERMINAL_TOOL


def dispatch_client_tool(name: str, input_data: dict) -> ToolResult:
    """Route a client tool call to its implementation and return the result."""
    if name == "get_market_data":
        return _get_market_data(input_data)
    if name == "submit_dossier":
        return _submit_dossier(input_data)
    return ToolResult(
        json_response={"error": f"Unknown client tool: {name}", "recoverable": False}
    )


# ---------------------------------------------------------------------------
# Stub implementations — replaced by production implementations in block-D.
# ---------------------------------------------------------------------------

def _get_market_data(input_data: dict) -> ToolResult:
    """Minimal market data stub for block-C.

    Attempts a basic yfinance call if the library is available.
    Returns a recoverable error otherwise so the model falls back to web search.
    Block-D adds full error handling, timeouts, and Langfuse spans.
    """
    ticker = input_data.get("ticker", "")
    try:
        import yfinance as yf  # optional dep in block-C

        info = yf.Ticker(ticker).fast_info
        return ToolResult(
            json_response={
                "ticker": ticker,
                "price": getattr(info, "last_price", None),
                "currency": getattr(info, "currency", None),
                "market_cap": getattr(info, "market_cap", None),
                "week52_high": getattr(info, "year_high", None),
                "week52_low": getattr(info, "year_low", None),
                "source": "yfinance",
                "as_of": "now",
            }
        )
    except ImportError:
        logger.debug("yfinance not installed; returning recoverable error for %s", ticker)
        return ToolResult(
            json_response={
                "error": "Market data provider not available in this build phase.",
                "recoverable": True,
            }
        )
    except Exception as exc:
        logger.warning("get_market_data failed for %s: %s", ticker, exc)
        return ToolResult(
            json_response={"error": str(exc), "recoverable": True}
        )


def _submit_dossier(input_data: dict) -> ToolResult:
    """Minimal submit_dossier for block-C: validate schema and signal loop termination.

    Block-D adds: retry logic on validation failure, output guardrail classifier,
    and Langfuse span.
    """
    try:
        dossier = CompanyDossier.model_validate(input_data)
        logger.info(
            "Dossier validated for %s (schema_version=%s)",
            dossier.company.ticker,
            dossier.schema_version,
        )
        return ToolResult(
            json_response={"success": True, "message": "Dossier submitted and validated."},
            dossier=dossier,
        )
    except ValidationError as exc:
        error_summary = exc.error_count()
        logger.warning("Dossier validation failed: %d error(s)", error_summary)
        return ToolResult(
            json_response={
                "success": False,
                "error": str(exc),
                "hint": "Fix the validation errors and call submit_dossier again.",
            }
        )
