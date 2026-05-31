"""Client tool dispatch and production implementations (Spec 02, Spec 05).

The distinction between client tools and server tools (ADR-003, ADR-005, ADR-011):
- Client tools  → this module executes them and returns a tool_result.
- Server tools  → Anthropic resolves them; they appear as server_tool_use blocks
                  in the response content but need no action here.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone

import yfinance as yf
from pydantic import ValidationError

from app.dossier.models import CompanyDossier

logger = logging.getLogger(__name__)

# Name of the tool that terminates the loop (ADR-006).
TERMINAL_TOOL = "submit_dossier"

# Timeout for a single yfinance network call (seconds).
_YFINANCE_TIMEOUT_S = 10


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
# Production implementations (block-D)
# ---------------------------------------------------------------------------

def _get_market_data(input_data: dict) -> ToolResult:
    """Fetch structured market data for a ticker via yfinance (ADR-004).

    Returns all MarketData fields; fields with no datum are null. On any provider
    failure returns {"error": ..., "recoverable": true} so the model can fall back
    to web search without breaking the loop (Spec 02).
    """
    ticker = input_data.get("ticker", "").strip().upper()
    if not ticker:
        return ToolResult(
            json_response={"error": "ticker is required", "recoverable": False}
        )

    def _fetch() -> dict:
        info = yf.Ticker(ticker).info
        # Prefer currentPrice; fall back to regularMarketPrice. Use explicit
        # None checks — `or` would silently discard a legitimate price of 0.
        price = info.get("currentPrice")
        if price is None:
            price = info.get("regularMarketPrice")
        if price is None:
            raise ValueError(f"no price data returned for {ticker!r}")
        return {
            "ticker": ticker,
            "price": float(price),
            "currency": info.get("currency"),
            "change_pct": _to_float(info.get("regularMarketChangePercent")),
            "market_cap": _to_float(info.get("marketCap")),
            "pe_ratio": _to_float(info.get("trailingPE")),
            "forward_pe": _to_float(info.get("forwardPE")),
            "eps": _to_float(info.get("trailingEps")),
            "dividend_yield": _to_float(info.get("dividendYield")),
            "week52_high": _to_float(info.get("fiftyTwoWeekHigh")),
            "week52_low": _to_float(info.get("fiftyTwoWeekLow")),
            "as_of": datetime.now(tz=timezone.utc).isoformat(),
            "source": "Yahoo Finance",
        }

    # shutdown(wait=False) in the finally so a timed-out or failed _fetch()
    # thread does not block the caller while the OS socket drains.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_fetch)
        try:
            data = future.result(timeout=_YFINANCE_TIMEOUT_S)
        except FuturesTimeoutError:
            logger.warning("get_market_data timed out for %s", ticker)
            return ToolResult(
                json_response={
                    "error": f"Market data request timed out after {_YFINANCE_TIMEOUT_S}s.",
                    "recoverable": True,
                }
            )
        return ToolResult(json_response=data)
    except Exception as exc:
        logger.warning("get_market_data failed for %s: %s", ticker, exc)
        return ToolResult(json_response={"error": str(exc), "recoverable": True})
    finally:
        executor.shutdown(wait=False)


def _submit_dossier(input_data: dict) -> ToolResult:
    """Validate the dossier schema and signal loop termination (ADR-006, Spec 05).

    Returns success=True on valid input. On ValidationError returns a detailed
    error so the loop can feed it back to the model for one retry (ADR-006).
    Unexpected errors are caught and returned as non-recoverable to avoid crashing
    the ThreadPoolExecutor thread.
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
        logger.warning("Dossier validation failed: %d error(s)", exc.error_count())
        return ToolResult(
            json_response={
                "success": False,
                "error": str(exc),
                "hint": "Fix ALL validation errors listed above and call submit_dossier again.",
            }
        )
    except Exception as exc:
        # Catch-all: unexpected errors (TypeError from malformed input, etc.) must
        # not propagate out of dispatch — the loop cannot recover from an unhandled
        # exception in a thread (future.result() re-raises it, crashing run()).
        logger.error("submit_dossier raised unexpected error: %s", exc, exc_info=True)
        return ToolResult(
            json_response={
                "success": False,
                "error": f"Unexpected error during dossier validation: {exc}",
                "recoverable": False,
            }
        )


def _to_float(value) -> float | None:
    """Coerce a yfinance value to float, returning None for missing/invalid data."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
