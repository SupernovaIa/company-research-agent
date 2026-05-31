"""Tests for the tool-use loop (Spec 03 acceptance criteria).

The Anthropic client is mocked so no real API calls are made.  Each test
drives a specific scenario through the loop and asserts the resulting state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agent.loop import (
    HARD_TURN_LIMIT,
    SOFT_TURN_LIMIT,
    _WRAP_UP_MESSAGE,
    LoopResult,
    _estimate_cost,
    _extract_client_tool_uses,
    _execute_tools_parallel,
    run,
)
from app.dossier.models import (
    Company,
    CompanyDossier,
    Fact,
    MarketData,
    RunMeta,
    Source,
)
from app.tools.client import (
    ToolResult,
    dispatch_client_tool,
    is_terminal_tool,
    _get_market_data,
    _submit_dossier,
)


# ---------------------------------------------------------------------------
# Helpers to build fake SDK response objects
# ---------------------------------------------------------------------------

@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _FakeTextBlock:
    type: str = "text"
    text: str = "Research complete."


@dataclass
class _FakeToolUseBlock:
    type: str = "tool_use"
    id: str = "tool_123"
    name: str = "get_market_data"
    input: dict = field(default_factory=lambda: {"ticker": "AAPL"})


@dataclass
class _FakeThinkingBlock:
    type: str = "thinking"
    thinking: str = "Let me analyze the company…"


@dataclass
class _FakeServerToolUseBlock:
    type: str = "server_tool_use"
    id: str = "srv_001"
    name: str = "web_search"
    input: dict = field(default_factory=lambda: {"query": "Apple Inc"})


@dataclass
class _FakeResponse:
    stop_reason: str = "end_turn"
    content: list = field(default_factory=lambda: [_FakeTextBlock()])
    usage: _FakeUsage = field(default_factory=_FakeUsage)
    model: str = "claude-sonnet-4-6"


def _valid_dossier_dict(ticker: str = "AAPL") -> dict:
    """Build the smallest valid CompanyDossier dict accepted by Pydantic."""
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "schema_version": "1.0.0",
        "company": {
            "name": "Apple Inc.",
            "ticker": ticker,
            "exchange": "NASDAQ",
            "sector": "Technology",
            "website": "https://www.apple.com",
        },
        "market_data": {
            "price": 189.5,
            "currency": "USD",
            "change_pct": 0.5,
            "market_cap": 2_900_000_000_000,
            "as_of": now,
            "source": "yfinance",
        },
        "business_overview": "Apple designs and sells consumer electronics and software.",
        "key_facts": [
            {"text": "iPhone revenue represents ~52% of total revenue.", "source_id": "src1"},
        ],
        "recent_news": [
            {
                "headline": "Apple reports record Q4",
                "date": "2025-11-01",
                "summary": "Revenue beat analyst expectations.",
                "source_id": "src1",
            }
        ],
        "sources": [
            {
                "id": "src1",
                "url": "https://example.com/apple-q4",
                "title": "Apple Q4 Report",
                "accessed_at": now,
            }
        ],
        "generated_at": now,
        "run": {"model": "claude-sonnet-4-6", "cost_usd": 0.25, "turns": 3},
    }


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------

def test_estimate_cost_positive():
    usage = _FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = _estimate_cost(usage)
    assert cost == pytest.approx(18.0, rel=1e-3)


def test_extract_client_tool_uses_filters_server_and_text():
    content = [
        _FakeTextBlock(),
        _FakeToolUseBlock(id="c1", name="get_market_data"),
        _FakeServerToolUseBlock(),
        _FakeToolUseBlock(id="c2", name="submit_dossier"),
        _FakeThinkingBlock(),
    ]
    tool_uses = _extract_client_tool_uses(content)
    assert len(tool_uses) == 2
    assert {b.id for b in tool_uses} == {"c1", "c2"}


def test_extract_client_tool_uses_thinking_block_ignored():
    content = [_FakeThinkingBlock(), _FakeTextBlock()]
    assert _extract_client_tool_uses(content) == []


def test_is_terminal_tool():
    assert is_terminal_tool("submit_dossier") is True
    assert is_terminal_tool("get_market_data") is False
    assert is_terminal_tool("web_search") is False


def test_execute_tools_parallel_dispatches_in_parallel():
    tool_uses = [
        _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"}),
        _FakeToolUseBlock(id="t2", name="get_market_data", input={"ticker": "MSFT"}),
    ]
    results = _execute_tools_parallel(tool_uses)
    assert set(results.keys()) == {"t1", "t2"}
    for r in results.values():
        assert isinstance(r, ToolResult)


def test_execute_tools_parallel_empty():
    assert _execute_tools_parallel([]) == {}


# ---------------------------------------------------------------------------
# Loop integration tests (mocked Anthropic client)
# ---------------------------------------------------------------------------

def _mock_client(responses: list[_FakeResponse]) -> MagicMock:
    """Return a mock Anthropic() instance whose messages.create yields *responses*."""
    client = MagicMock()
    client.messages.create.side_effect = responses
    return client


def _patch_client(responses):
    """Context manager: patches anthropic.Anthropic() with a pre-built mock."""
    mock = _mock_client(responses)
    return patch("app.agent.loop.anthropic.Anthropic", return_value=mock)


def test_loop_end_turn_immediately():
    """Model returns end_turn on the first call → loop exits with terminated_by=end_turn."""
    responses = [_FakeResponse(stop_reason="end_turn")]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "end_turn"
    assert result.turns == 1
    assert result.dossier is None
    assert result.cost_usd > 0


def test_loop_client_tool_then_end_turn():
    """Model calls get_market_data, receives tool_result, then ends."""
    tool_use_block = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[tool_use_block],
        ),
        _FakeResponse(stop_reason="end_turn"),
    ]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "end_turn"
    assert result.turns == 2


def test_loop_submit_dossier_terminates():
    """Model calls submit_dossier with a valid dossier → loop terminates and stores dossier."""
    dossier_data = _valid_dossier_dict()
    submit_block = _FakeToolUseBlock(
        id="sub1", name="submit_dossier", input=dossier_data
    )
    responses = [
        _FakeResponse(stop_reason="tool_use", content=[submit_block]),
    ]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "submit_dossier"
    assert result.dossier is not None
    assert result.dossier.company.ticker == "AAPL"
    assert result.turns == 1


def test_loop_submit_dossier_validation_failure_model_retries():
    """Invalid dossier → tool_result carries error → model gets another turn."""
    bad_dossier = {"company": {"name": "Broken"}}  # missing required fields
    submit_block = _FakeToolUseBlock(id="s1", name="submit_dossier", input=bad_dossier)

    valid_dossier = _valid_dossier_dict()
    submit_block_ok = _FakeToolUseBlock(id="s2", name="submit_dossier", input=valid_dossier)

    responses = [
        _FakeResponse(stop_reason="tool_use", content=[submit_block]),
        _FakeResponse(stop_reason="tool_use", content=[submit_block_ok]),
    ]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "submit_dossier"
    assert result.dossier is not None


def test_loop_hard_limit():
    """Loop that never submits hits HARD_TURN_LIMIT and exits with hard_limit."""
    tool_use_block = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    # Produce more responses than HARD_TURN_LIMIT; loop must stop on its own.
    responses = [
        _FakeResponse(stop_reason="tool_use", content=[tool_use_block])
    ] * (HARD_TURN_LIMIT + 5)

    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "hard_limit"
    assert result.turns == HARD_TURN_LIMIT
    assert result.dossier is None


def test_loop_soft_limit_injects_wrap_up_message():
    """At SOFT_TURN_LIMIT the wrap-up message is injected into the conversation."""
    tool_use_block = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    responses = [
        _FakeResponse(stop_reason="tool_use", content=[tool_use_block])
    ] * (HARD_TURN_LIMIT + 5)

    captured_calls = []
    original_create = None

    def _recording_create(**kwargs):
        captured_calls.append(kwargs.get("messages", []))
        return responses[len(captured_calls) - 1]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _recording_create

    with patch("app.agent.loop.anthropic.Anthropic", return_value=mock_client):
        run("AAPL")

    # The call made AT turn SOFT_TURN_LIMIT should have the wrap-up injected.
    # Calls are zero-indexed; turn N is call N-1.
    soft_call_messages = captured_calls[SOFT_TURN_LIMIT - 1]
    user_contents = [
        m["content"] for m in soft_call_messages if m["role"] == "user"
    ]
    flat = " ".join(
        c if isinstance(c, str) else ""
        for contents in user_contents
        for c in ([contents] if isinstance(contents, str) else [])
    )
    # Check that the wrap-up message appears somewhere in the user messages.
    assert any(
        _WRAP_UP_MESSAGE in (m["content"] if isinstance(m["content"], str) else "")
        for m in soft_call_messages
        if m["role"] == "user"
    )


def test_loop_parallel_tool_calls_same_turn():
    """Multiple tool_use blocks in a single turn are dispatched and all returned."""
    t1 = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    t2 = _FakeToolUseBlock(id="t2", name="get_market_data", input={"ticker": "MSFT"})

    responses = [
        _FakeResponse(stop_reason="tool_use", content=[t1, t2]),
        _FakeResponse(stop_reason="end_turn"),
    ]

    captured_messages = []

    def _recording_create(**kwargs):
        captured_messages.append(kwargs["messages"])
        return responses[len(captured_messages) - 1]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _recording_create

    with patch("app.agent.loop.anthropic.Anthropic", return_value=mock_client):
        result = run("AAPL")

    assert result.terminated_by == "end_turn"
    # The second call should include tool_results for BOTH t1 and t2.
    second_call_messages = captured_messages[1]
    last_user_msg = next(
        m for m in reversed(second_call_messages) if m["role"] == "user"
    )
    assert isinstance(last_user_msg["content"], list)
    assert len(last_user_msg["content"]) == 2
    ids_returned = {r["tool_use_id"] for r in last_user_msg["content"]}
    assert ids_returned == {"t1", "t2"}


def test_loop_thinking_block_in_response():
    """A response with thinking + text + tool_use is parsed without errors."""
    t1 = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[_FakeThinkingBlock(), _FakeTextBlock(), t1],
        ),
        _FakeResponse(stop_reason="end_turn"),
    ]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "end_turn"
    assert result.turns == 2


def test_loop_on_turn_callback():
    """on_turn callback is invoked once per API call."""
    responses = [
        _FakeResponse(stop_reason="tool_use", content=[
            _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
        ]),
        _FakeResponse(stop_reason="end_turn"),
    ]

    calls = []
    with _patch_client(responses):
        run("AAPL", on_turn=lambda turn, stop, content: calls.append((turn, stop)))

    assert len(calls) == 2
    assert calls[0] == (1, "tool_use")
    assert calls[1] == (2, "end_turn")


def test_loop_server_tool_use_blocks_ignored():
    """server_tool_use blocks in content are not dispatched as client tools."""
    srv = _FakeServerToolUseBlock()
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[srv, _FakeToolUseBlock(id="c1", name="get_market_data", input={"ticker": "AAPL"})],
        ),
        _FakeResponse(stop_reason="end_turn"),
    ]
    with _patch_client(responses):
        result = run("AAPL")

    # Loop completes without error; server block was ignored.
    assert result.turns == 2


# ---------------------------------------------------------------------------
# Fix 1: _submit_dossier catch-all (review finding confirmed)
# ---------------------------------------------------------------------------

def test_submit_dossier_non_validation_error_is_caught():
    """Non-ValidationError from model_validate is returned as error ToolResult, not raised."""
    with patch(
        "app.tools.client.CompanyDossier.model_validate",
        side_effect=TypeError("unexpected internal error"),
    ):
        result = _submit_dossier({})

    assert result.success is False
    assert "error" in result.json_response
    assert result.dossier is None
    # Must NOT raise — the loop cannot recover from an unhandled thread exception.


def test_dispatch_client_tool_submit_dossier_unexpected_error_does_not_raise():
    """dispatch_client_tool wraps _submit_dossier; non-ValidationError must not propagate."""
    with patch(
        "app.tools.client.CompanyDossier.model_validate",
        side_effect=RuntimeError("pydantic internals crashed"),
    ):
        result = dispatch_client_tool("submit_dossier", {})

    assert result.success is False
    assert result.dossier is None


# ---------------------------------------------------------------------------
# Fix 2: as_of is a real ISO datetime, not the literal string "now"
# ---------------------------------------------------------------------------

_MOCK_AAPL_INFO = {
    "currentPrice": 189.5,
    "currency": "USD",
    "regularMarketChangePercent": 0.5,
    "marketCap": 2_900_000_000_000,
    "trailingPE": 30.2,
    "forwardPE": 27.1,
    "trailingEps": 6.35,
    "dividendYield": 0.005,
    "fiftyTwoWeekHigh": 199.0,
    "fiftyTwoWeekLow": 164.0,
}


def test_get_market_data_as_of_is_iso_datetime():
    """get_market_data returns as_of as a valid ISO 8601 datetime, not 'now'."""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = _MOCK_AAPL_INFO
        result = _get_market_data({"ticker": "AAPL"})

    assert "as_of" in result.json_response
    as_of = result.json_response["as_of"]
    assert as_of != "now", "'now' literal must not appear; expected ISO 8601 string"
    parsed = datetime.fromisoformat(as_of)
    assert parsed.tzinfo is not None, "as_of must be timezone-aware"


def test_get_market_data_all_fields_populated():
    """get_market_data returns all MarketData fields when yfinance provides them."""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = _MOCK_AAPL_INFO
        result = _get_market_data({"ticker": "AAPL"})

    r = result.json_response
    assert r["price"] == pytest.approx(189.5)
    assert r["currency"] == "USD"
    assert r["change_pct"] == pytest.approx(0.5)
    assert r["market_cap"] == pytest.approx(2_900_000_000_000)
    assert r["pe_ratio"] == pytest.approx(30.2)
    assert r["forward_pe"] == pytest.approx(27.1)
    assert r["eps"] == pytest.approx(6.35)
    assert r["dividend_yield"] == pytest.approx(0.005)
    assert r["week52_high"] == pytest.approx(199.0)
    assert r["week52_low"] == pytest.approx(164.0)
    assert r["source"] == "Yahoo Finance"


def test_get_market_data_invalid_ticker_returns_recoverable_error():
    """A ticker with no price data returns recoverable=True, not an exception."""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = {}  # no price fields
        result = _get_market_data({"ticker": "ZZZZ"})

    assert "error" in result.json_response
    assert result.json_response["recoverable"] is True


def test_get_market_data_missing_ticker_is_not_recoverable():
    """Empty ticker input returns a non-recoverable error immediately."""
    result = _get_market_data({"ticker": ""})
    assert "error" in result.json_response
    assert result.json_response["recoverable"] is False


def test_get_market_data_null_fields_are_none():
    """Fields absent from yfinance info come back as None (not missing keys)."""
    minimal_info = {"currentPrice": 50.0, "currency": "EUR"}
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = minimal_info
        result = _get_market_data({"ticker": "SAP.DE"})

    r = result.json_response
    assert r["price"] == pytest.approx(50.0)
    assert r["change_pct"] is None
    assert r["pe_ratio"] is None
    assert r["forward_pe"] is None
    assert r["eps"] is None
    assert r["dividend_yield"] is None


# ---------------------------------------------------------------------------
# Fix 3: server-tool-only turn must not append empty user content (review finding)
# ---------------------------------------------------------------------------

def test_loop_server_only_turn_no_empty_user_message():
    """When a turn has only server_tool_use blocks, no user message with content:[] is sent."""
    srv = _FakeServerToolUseBlock()
    responses = [
        # Turn 1: only a server tool fires; stop_reason is still "tool_use"
        _FakeResponse(stop_reason="tool_use", content=[srv]),
        _FakeResponse(stop_reason="end_turn"),
    ]

    captured_calls: list[list] = []

    def _recording_create(**kwargs):
        captured_calls.append(list(kwargs["messages"]))
        return responses[len(captured_calls) - 1]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _recording_create

    with patch("app.agent.loop.anthropic.Anthropic", return_value=mock_client):
        result = run("AAPL")

    assert result.terminated_by == "end_turn"
    assert result.turns == 2

    # The second API call must NOT include a user message with an empty content list.
    second_call_messages = captured_calls[1]
    empty_user_msgs = [
        m for m in second_call_messages
        if m["role"] == "user" and m["content"] == []
    ]
    assert empty_user_msgs == [], (
        "Empty user content list must not be sent to the Anthropic API; "
        f"found: {empty_user_msgs}"
    )


# ---------------------------------------------------------------------------
# Fix 4: max_turns parameter controls the loop at call time (not baked constant)
# ---------------------------------------------------------------------------

def test_run_max_turns_parameter_overrides_baked_limit():
    """max_turns=2 stops the loop at 2 turns regardless of settings.agent_max_turns."""
    tool_use_block = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    responses = [_FakeResponse(stop_reason="tool_use", content=[tool_use_block])] * 10

    with _patch_client(responses):
        result = run("AAPL", max_turns=2)

    assert result.turns == 2
    assert result.terminated_by == "hard_limit"


# ---------------------------------------------------------------------------
# Block-D: submit_dossier retry logic (ADR-006, Spec 05)
# ---------------------------------------------------------------------------

def test_loop_submit_dossier_fails_twice_terminates_with_failed_status():
    """submit_dossier fails twice → loop exits with terminated_by=submit_dossier_failed."""
    bad_dossier = {"company": {"name": "Broken"}}  # missing required fields
    submit_block = _FakeToolUseBlock(id="s1", name="submit_dossier", input=bad_dossier)
    submit_block2 = _FakeToolUseBlock(id="s2", name="submit_dossier", input=bad_dossier)

    responses = [
        _FakeResponse(stop_reason="tool_use", content=[submit_block]),
        _FakeResponse(stop_reason="tool_use", content=[submit_block2]),
        _FakeResponse(stop_reason="end_turn"),  # should never be reached
    ]
    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "submit_dossier_failed"
    assert result.dossier is None


def test_loop_run_metadata_is_injected_by_loop():
    """run.model, cost_usd, turns, and generated_at are overwritten with actual loop values."""
    from datetime import datetime, timezone

    from app.tools.inventory import AGENT_MODEL

    dossier_data = _valid_dossier_dict()
    dossier_data["run"]["model"] = "wrong-model-from-llm"
    dossier_data["run"]["cost_usd"] = 999.0
    dossier_data["run"]["turns"] = 999
    dossier_data["generated_at"] = "2020-01-01T00:00:00+00:00"

    submit_block = _FakeToolUseBlock(id="sub1", name="submit_dossier", input=dossier_data)
    responses = [_FakeResponse(stop_reason="tool_use", content=[submit_block])]

    before = datetime.now(tz=timezone.utc)
    with _patch_client(responses):
        result = run("AAPL")
    after = datetime.now(tz=timezone.utc)

    assert result.terminated_by == "submit_dossier"
    assert result.dossier is not None
    assert result.dossier.run.model == AGENT_MODEL
    assert result.dossier.run.turns == 1
    assert result.dossier.run.cost_usd != 999.0
    assert before <= result.dossier.generated_at <= after


# ---------------------------------------------------------------------------
# Block-D: get_market_data yfinance timeout (Spec 02)
# ---------------------------------------------------------------------------

def test_get_market_data_timeout_returns_recoverable_error():
    """A yfinance call that hangs past the timeout returns a recoverable error without blocking."""
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    class _TimingOutExecutor:
        """Executor whose futures raise TimeoutError; shutdown is a no-op."""
        def submit(self, fn, *args, **kwargs):  # noqa: ARG002
            future = MagicMock()
            future.result.side_effect = FuturesTimeoutError()
            return future
        def shutdown(self, wait=True, **kwargs):
            pass  # must not block

    with patch("app.tools.client.ThreadPoolExecutor", return_value=_TimingOutExecutor()):
        result = _get_market_data({"ticker": "AAPL"})

    assert "error" in result.json_response
    assert result.json_response["recoverable"] is True


def test_get_market_data_price_zero_is_not_discarded():
    """A valid price of 0 must be returned, not silently dropped by a falsy `or`."""
    info_with_zero_price = {**_MOCK_AAPL_INFO, "currentPrice": 0, "regularMarketPrice": 0}
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = info_with_zero_price
        result = _get_market_data({"ticker": "HALT"})

    # price=0 is a valid value for a halted/suspended stock; must not be silently discarded.
    assert result.json_response.get("price") == pytest.approx(0.0)
    assert "error" not in result.json_response


def test_loop_generated_at_is_injected_by_loop():
    """generated_at in the dossier is overwritten by the loop with the actual run time."""
    from datetime import datetime, timezone

    dossier_data = _valid_dossier_dict()
    dossier_data["generated_at"] = "2020-01-01T00:00:00+00:00"  # stale / hallucinated

    submit_block = _FakeToolUseBlock(id="sub1", name="submit_dossier", input=dossier_data)
    responses = [_FakeResponse(stop_reason="tool_use", content=[submit_block])]

    before = datetime.now(tz=timezone.utc)
    with _patch_client(responses):
        result = run("AAPL")
    after = datetime.now(tz=timezone.utc)

    assert result.dossier is not None
    assert result.dossier.generated_at >= before
    assert result.dossier.generated_at <= after


# ---------------------------------------------------------------------------
# Block-E: budget hard cut (Spec 04, ADR-007)
# ---------------------------------------------------------------------------

def test_loop_budget_exceeded_stops_loop():
    """A loop whose per-turn cost exceeds the budget cap terminates with budget_exceeded."""
    from unittest.mock import patch as _patch
    from app.config import settings

    tool_use_block = _FakeToolUseBlock(id="t1", name="get_market_data", input={"ticker": "AAPL"})
    # Produce enough fake responses; the budget check must stop the loop before exhausting them.
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[tool_use_block],
            # 10M input + 10M output tokens → ~$180 per turn, well above any budget cap.
            usage=_FakeUsage(input_tokens=10_000_000, output_tokens=10_000_000),
        )
    ] * 10

    with _patch_client(responses):
        # Use a very low budget so a single expensive turn blows past it.
        with _patch.object(settings, "agent_budget_usd", 0.001):
            result = run("AAPL")

    assert result.terminated_by == "budget_exceeded"
    assert result.dossier is None
    # Loop must have stopped early — not gone the full default turn count.
    assert result.turns < settings.agent_max_turns


def test_loop_budget_not_exceeded_continues():
    """A loop that stays within budget completes normally (terminated_by != budget_exceeded)."""
    dossier_data = _valid_dossier_dict()
    submit_block = _FakeToolUseBlock(id="sub1", name="submit_dossier", input=dossier_data)
    # Small token counts → tiny cost well below any reasonable budget.
    responses = [_FakeResponse(stop_reason="tool_use", content=[submit_block])]

    with _patch_client(responses):
        result = run("AAPL")

    assert result.terminated_by == "submit_dossier"
    assert result.dossier is not None


# ---------------------------------------------------------------------------
# Block-E: model client timeout is wired (Spec 04)
# ---------------------------------------------------------------------------

def test_loop_client_timeout_kwarg_is_passed():
    """The Anthropic client is constructed with the agent_timeout_s from settings."""
    from unittest.mock import patch as _patch, MagicMock
    from app.config import settings

    responses = [_FakeResponse(stop_reason="end_turn")]
    captured_kwargs = {}

    def _fake_anthropic(**kwargs):
        captured_kwargs.update(kwargs)
        mock = MagicMock()
        mock.messages.create.side_effect = responses
        return mock

    with _patch("app.agent.loop.anthropic.Anthropic", side_effect=_fake_anthropic):
        run("AAPL")

    assert "timeout" in captured_kwargs, "anthropic.Anthropic must be called with timeout="
    assert captured_kwargs["timeout"] == settings.agent_timeout_s


# ---------------------------------------------------------------------------
# Block-E: tool output Pydantic validation (Spec 04)
# ---------------------------------------------------------------------------

def test_get_market_data_output_validation_bad_shape_returns_recoverable_error():
    """If the dict we build fails _MarketDataOutput validation, a recoverable error is returned."""
    from pydantic import ValidationError as PydanticValidationError
    from app.tools.client import _MarketDataOutput

    # Build a real ValidationError by validating an empty dict against the schema.
    try:
        _MarketDataOutput.model_validate({})
        raise AssertionError("Expected ValidationError from empty dict")
    except PydanticValidationError as exc:
        validation_error = exc

    with patch("app.tools.client._MarketDataOutput.model_validate", side_effect=validation_error):
        result = _get_market_data({"ticker": "AAPL"})

    # When output validation fails, a recoverable error is returned.
    assert "error" in result.json_response
    assert result.json_response.get("recoverable") is True
