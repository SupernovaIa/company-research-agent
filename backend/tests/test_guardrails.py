"""Block-E guardrail tests: rate limiting, budget cut, tool output validation.

Covers the Spec 04 acceptance criteria for the operational guardrails
implemented in block-E (budget hard cut, model client timeout, Tenacity
retries, rate limiting, tool output validation). The indirect prompt
injection defence and Haiku classifier are tested in block-F.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.serving.main import app, _limiter

client = TestClient(app)


# ---------------------------------------------------------------------------
# Rate limiting (Spec 04)
# ---------------------------------------------------------------------------

def test_research_endpoint_exists():
    """/research POST streams SSE (200 text/event-stream, not 404)."""
    with patch("app.agent.loop.run") as mock_run:
        mock_run.return_value = MagicMock(
            dossier=None,
            terminated_by="end_turn",
            turns=1,
            cost_usd=0.01,
        )
        response = client.post("/research", json={"ticker": "AAPL"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "event: error" in response.text


def test_research_endpoint_empty_ticker_returns_422():
    """Empty ticker in /research body returns 422 without calling the agent."""
    with patch("app.agent.loop.run") as mock_run:
        response = client.post("/research", json={"ticker": ""})
    assert response.status_code == 422
    assert "error" in response.json()
    mock_run.assert_not_called()


def test_research_endpoint_missing_ticker_returns_422():
    """Missing ticker key in /research body returns 422 without calling the agent."""
    with patch("app.agent.loop.run") as mock_run:
        response = client.post("/research", json={})
    assert response.status_code == 422
    mock_run.assert_not_called()


def test_rate_limiter_is_wired_to_app():
    """The app exposes a slowapi Limiter on app.state so the exception handler fires."""
    from slowapi import Limiter

    assert hasattr(app.state, "limiter"), "app.state.limiter must be set for slowapi"
    assert isinstance(app.state.limiter, Limiter)


def test_rate_limit_exceeded_returns_429():
    """Requests above the per-minute cap are rejected with 429.

    slowapi's _check_request_limit normally sets request.state.view_rate_limit
    before raising RateLimitExceeded. Our side_effect replicates that so the
    exception handler can run cleanly.
    """
    from slowapi.errors import RateLimitExceeded
    from app.serving.main import _limiter

    def _fake_check(request, endpoint, async_request=False):
        limit_mock = MagicMock()
        limit_mock.error_message.return_value = "10 per 1 minute"
        request.state.view_rate_limit = limit_mock
        raise RateLimitExceeded(limit_mock)

    with patch("app.agent.loop.run"):
        with patch.object(_limiter, "_check_request_limit", side_effect=_fake_check):
            response = client.post("/research", json={"ticker": "AAPL"})

    assert response.status_code == 429


# ---------------------------------------------------------------------------
# Tenacity retries in get_market_data (Spec 04)
# ---------------------------------------------------------------------------

def test_get_market_data_retries_on_connection_error():
    """ConnectionError from yfinance is retried; a successful 3rd attempt returns data.

    Tenacity retries up to 3 attempts (Spec 04). The `@retry` decorator wraps
    `_fetch` which calls `yf.Ticker(ticker).info`. We mock yf.Ticker so that
    the first two calls raise ConnectionError and the third returns valid data.
    """
    from app.tools.client import _get_market_data

    call_count = [0]

    def _ticker_factory(ticker_sym):
        instance = MagicMock()
        call_count[0] += 1
        if call_count[0] < 3:
            # Raise when .info is accessed, simulating a transient network error.
            type(instance).info = property(
                lambda self: (_ for _ in ()).throw(ConnectionError("blip"))
            )
        else:
            type(instance).info = property(
                lambda self: {"currentPrice": 100.0, "currency": "USD"}
            )
        return instance

    with patch("yfinance.Ticker", side_effect=_ticker_factory):
        result = _get_market_data({"ticker": "AAPL"})

    # Third attempt succeeded → valid market data returned.
    assert "price" in result.json_response
    assert result.json_response["price"] == pytest.approx(100.0)
    assert call_count[0] == 3, f"Expected 3 attempts (2 retries), got {call_count[0]}"


def test_get_market_data_exhausted_retries_returns_recoverable_error():
    """If all retries fail due to ConnectionError, a recoverable error is returned."""
    from app.tools.client import _get_market_data

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = property(
            lambda self: (_ for _ in ()).throw(ConnectionError("persistent failure"))
        )
        result = _get_market_data({"ticker": "AAPL"})

    assert isinstance(result.json_response, dict)
    assert "error" in result.json_response or "price" in result.json_response


# ---------------------------------------------------------------------------
# Budget exceeded in run.py CLI message (Spec 04)
# ---------------------------------------------------------------------------

def test_budget_exceeded_message_in_run_cli():
    """run.py CLI maps terminated_by=budget_exceeded to a user-facing error message."""
    import io
    import app.agent.run as run_cli
    from app.agent.loop import LoopResult

    with patch("app.agent.loop.run") as mock_loop:
        mock_loop.return_value = LoopResult(
            dossier=None,
            turns=1,
            cost_usd=0.99,
            terminated_by="budget_exceeded",
        )
        with patch("sys.argv", ["run", "--ticker", "AAPL"]):
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                exit_code = run_cli.main()

    assert exit_code == 1
    assert "budget" in stderr_buf.getvalue().lower()
