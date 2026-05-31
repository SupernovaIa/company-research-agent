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
from app.tools.client import ToolResult, dispatch_client_tool, is_terminal_tool


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
