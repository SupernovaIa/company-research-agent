"""Unit tests for the eval runner (Spec 07 acceptance criteria).

The loop is mocked so no real API calls are made. Tests verify metric
computation, gate threshold logic, and JSONL parsing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.loop import LoopResult
from app.dossier.models import Company, CompanyDossier, MarketData, RunMeta
from app.evals.runner import (
    GOLD_JSONL,
    TASK_COMPLETION_THRESHOLD,
    TOOL_ACCURACY_THRESHOLD,
    EvalReport,
    _tool_names_from_content,
    load_gold_set,
    run_eval,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dossier(ticker: str = "TEST") -> CompanyDossier:
    now = datetime.now(tz=timezone.utc)
    return CompanyDossier(
        company=Company(name="Test Corp", ticker=ticker, exchange="NASDAQ"),
        market_data=MarketData(
            price=100.0,
            currency="USD",
            as_of=now,
            source="Yahoo Finance",
        ),
        business_overview="A test company.",
        sources=[],
        key_facts=[],
        recent_news=[],
        generated_at=now,
        run=RunMeta(model="test-model", cost_usd=0.05, turns=2),
    )


def _loop_result(
    terminated_by: str = "submit_dossier",
    dossier: CompanyDossier | None = None,
    cost: float = 0.05,
    turns: int = 3,
) -> LoopResult:
    if terminated_by == "submit_dossier" and dossier is None:
        dossier = _make_dossier()
    return LoopResult(
        dossier=dossier,
        turns=turns,
        cost_usd=cost,
        terminated_by=terminated_by,
    )


def _gold_file(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return path


# Gold entry templates
AAPL_ENTRY = {
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "category": "usa_large_cap",
    "expected_tool_calls": ["get_market_data", "web_search", "submit_dossier"],
    "optional_tool_calls": ["web_fetch"],
    "task_completion_expected": True,
    "dossier_checks": {},
    "annotation_notes": "",
}

ERROR_ENTRY = {
    "ticker": "INVALID_XYZ",
    "company_name": None,
    "category": "error_invalid_ticker",
    "expected_tool_calls": ["get_market_data"],
    "optional_tool_calls": ["web_search"],
    "task_completion_expected": False,
    "dossier_checks": None,
    "annotation_notes": "",
}


# ---------------------------------------------------------------------------
# Fake content blocks
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    type: str
    name: str = ""


# ---------------------------------------------------------------------------
# Tests: load_gold_set
# ---------------------------------------------------------------------------

def test_load_gold_set_parses_entries(tmp_path):
    path = _gold_file(tmp_path, [AAPL_ENTRY, ERROR_ENTRY])
    entries = load_gold_set(path)
    assert len(entries) == 2
    assert entries[0]["ticker"] == "AAPL"
    assert entries[1]["ticker"] == "INVALID_XYZ"


def test_load_gold_set_skips_blank_lines(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text(
        "\n"
        + json.dumps(AAPL_ENTRY)
        + "\n\n"
        + json.dumps(ERROR_ENTRY)
        + "\n\n",
        encoding="utf-8",
    )
    assert len(load_gold_set(path)) == 2


def test_load_gold_set_empty(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text("  \n\n", encoding="utf-8")
    assert load_gold_set(path) == []


# ---------------------------------------------------------------------------
# Tests: _tool_names_from_content
# ---------------------------------------------------------------------------

def test_tool_names_client_and_server():
    content = [
        _Block("tool_use", "get_market_data"),
        _Block("server_tool_use", "web_search"),
        _Block("text"),
    ]
    names = _tool_names_from_content(content)
    assert set(names) == {"get_market_data", "web_search"}


def test_tool_names_empty_content():
    assert _tool_names_from_content([]) == []


def test_tool_names_no_tools():
    assert _tool_names_from_content([_Block("text"), _Block("thinking")]) == []


def test_tool_names_unnamed_block_ignored():
    # A block with type tool_use but no name attribute is silently skipped.
    class _NoName:
        type = "tool_use"
    assert _tool_names_from_content([_NoName()]) == []


# ---------------------------------------------------------------------------
# Tests: run_eval — metric computation (loop mocked)
# ---------------------------------------------------------------------------

def _full_aapl_content():
    return [
        _Block("tool_use", "get_market_data"),
        _Block("server_tool_use", "web_search"),
        _Block("tool_use", "submit_dossier"),
    ]


def test_run_eval_all_pass(tmp_path):
    """All entries behave correctly → gate pass."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY, ERROR_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        if ticker == "AAPL":
            if on_turn:
                on_turn(1, "tool_use", _full_aapl_content())
            return _loop_result("submit_dossier", cost=0.05)
        # INVALID_XYZ: only get_market_data, no dossier
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "get_market_data")])
        return _loop_result("end_turn", dossier=None, cost=0.01)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.total_entries == 2
    assert report.task_completion_rate == 1.0
    assert report.tool_use_accuracy == 1.0
    assert report.gate_pass is True
    assert report.failures == []


def test_run_eval_gate_fail_completion(tmp_path):
    """Completion rate below threshold → gate fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY] * 5)
    call_n = [0]

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        call_n[0] += 1
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        if call_n[0] == 1:
            return _loop_result("submit_dossier", cost=0.05)
        return _loop_result("hard_limit", dossier=None, cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.task_completion_rate == pytest.approx(0.2)
    assert report.gate_pass is False
    assert any("task_completion_rate" in f for f in report.failures)


def test_run_eval_gate_fail_tool_accuracy(tmp_path):
    """Tool accuracy below threshold → gate fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY] * 5)

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        # Only submit_dossier — missing get_market_data and web_search.
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "submit_dossier")])
        return _loop_result("submit_dossier", cost=0.03)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.tool_use_accuracy == 0.0
    assert report.gate_pass is False
    assert any("tool_use_accuracy" in f for f in report.failures)


def test_run_eval_gate_fail_cost(tmp_path, monkeypatch):
    """Mean cost above budget → gate fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    monkeypatch.setattr("app.evals.runner.settings.agent_budget_usd", 0.50)

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=999.0)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.gate_pass is False
    assert any("mean_cost" in f for f in report.failures)


def test_error_entry_complete_when_no_dossier(tmp_path):
    """task_completion_expected=False entry passes when dossier is None."""
    gold = _gold_file(tmp_path, [ERROR_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "get_market_data")])
        return _loop_result("end_turn", dossier=None, cost=0.01)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.results[0].task_completion is True


def test_error_entry_fails_when_dossier_emitted(tmp_path):
    """task_completion_expected=False entry fails if a dossier is emitted."""
    gold = _gold_file(tmp_path, [ERROR_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        if on_turn:
            on_turn(1, "tool_use", [
                _Block("tool_use", "get_market_data"),
                _Block("tool_use", "submit_dossier"),
            ])
        # Model emitted a dossier despite an invalid ticker — this is wrong.
        return _loop_result("submit_dossier", dossier=_make_dossier(), cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.results[0].task_completion is False


def test_run_eval_empty_gold(tmp_path):
    """Empty gold set: zero metrics trigger both thresholds → gate fails."""
    gold = tmp_path / "empty.jsonl"
    gold.write_text("", encoding="utf-8")

    with patch("app.evals.runner.loop_run"):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold)

    assert report.total_entries == 0
    assert report.gate_pass is False  # 0% < 85% and 0% < 80%


def test_run_eval_entry_result_fields(tmp_path):
    """EntryResult carries all expected fields."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None):
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=0.07, turns=4)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with patch("app.evals.runner._load_fixture", return_value={"price": 100.0, "currency": "USD", "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00"}):
            report = run_eval(gold_path=gold, max_turns=5)

    r = report.results[0]
    assert r.ticker == "AAPL"
    assert r.category == "usa_large_cap"
    assert r.task_completion_expected is True
    assert r.terminated_by == "submit_dossier"
    assert r.task_completion is True
    assert r.turns == 4
    assert r.cost_usd == pytest.approx(0.07)
    assert "get_market_data" in r.actual_tool_calls


# ---------------------------------------------------------------------------
# Tests: path resolution (review finding #1)
# ---------------------------------------------------------------------------

def test_gold_jsonl_resolves_to_repo_root():
    """GOLD_JSONL must resolve inside the repo, not its parent directory."""
    # parents[3] from backend/app/evals/runner.py reaches the repo root.
    # If parents[4] were used, the path would point outside the repo and
    # gold.jsonl would not exist.
    assert GOLD_JSONL.exists(), (
        f"GOLD_JSONL does not exist: {GOLD_JSONL}\n"
        "This usually means _REPO_ROOT uses the wrong parents[] depth."
    )
    # Sanity: the resolved path must contain the project directory name.
    assert "company-research-agent" in str(GOLD_JSONL)


# ---------------------------------------------------------------------------
# Tests: missing fixture → loud error (review finding #3)
# ---------------------------------------------------------------------------

def test_missing_fixture_raises(tmp_path, monkeypatch):
    """run_eval raises FileNotFoundError when a gold entry has no fixture file."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    # Point FIXTURES_DIR to an empty directory so AAPL has no fixture.
    empty = tmp_path / "fixtures"
    empty.mkdir()
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", empty)

    with pytest.raises(FileNotFoundError, match="Missing fixtures for tickers"):
        run_eval(gold_path=gold)


def test_fixture_error_fires_before_api_calls(tmp_path, monkeypatch):
    """The fixture check must fail before any loop_run call is made."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    empty = tmp_path / "fixtures"
    empty.mkdir()
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", empty)

    with patch("app.evals.runner.loop_run") as mock_loop:
        with pytest.raises(FileNotFoundError):
            run_eval(gold_path=gold)
    mock_loop.assert_not_called()
