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

# Minimal fixture payloads used by the mock helpers below.
_MKT_FIXTURE = {
    "price": 100.0, "currency": "USD",
    "source": "Yahoo Finance", "as_of": "2026-06-01T00:00:00+00:00",
}
_WS_FIXTURE = {"results": [{"title": "Test", "url": "https://example.com", "snippet": "A test."}]}
_WF_FIXTURE = {"url": "https://example.com", "title": "Test article", "content": "Test content."}


def _patch_fixtures():
    """Context-manager that stubs all three fixture loaders."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("app.evals.runner._load_fixture", return_value=_MKT_FIXTURE))
    stack.enter_context(patch("app.evals.runner._load_web_search_fixture", return_value=_WS_FIXTURE))
    stack.enter_context(patch("app.evals.runner._load_web_fetch_fixture", return_value=_WF_FIXTURE))
    return stack


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

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        if ticker == "AAPL":
            if on_turn:
                on_turn(1, "tool_use", _full_aapl_content())
            return _loop_result("submit_dossier", cost=0.05)
        # INVALID_XYZ: only get_market_data, no dossier
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "get_market_data")])
        return _loop_result("end_turn", dossier=None, cost=0.01)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
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

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        call_n[0] += 1
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        if call_n[0] == 1:
            return _loop_result("submit_dossier", cost=0.05)
        return _loop_result("hard_limit", dossier=None, cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.task_completion_rate == pytest.approx(0.2)
    assert report.gate_pass is False
    assert any("task_completion_rate" in f for f in report.failures)


def test_run_eval_gate_fail_tool_accuracy(tmp_path):
    """Tool accuracy below threshold → gate fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY] * 5)

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        # Only submit_dossier — missing get_market_data and web_search.
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "submit_dossier")])
        return _loop_result("submit_dossier", cost=0.03)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.tool_use_accuracy == 0.0
    assert report.gate_pass is False
    assert any("tool_use_accuracy" in f for f in report.failures)


def test_run_eval_gate_fail_cost(tmp_path, monkeypatch):
    """Mean cost above budget → gate fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    monkeypatch.setattr("app.evals.runner.settings.agent_budget_usd", 0.50)

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=999.0)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.gate_pass is False
    assert any("mean_cost" in f for f in report.failures)


def test_error_entry_complete_when_no_dossier(tmp_path):
    """task_completion_expected=False entry passes when dossier is None."""
    gold = _gold_file(tmp_path, [ERROR_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "get_market_data")])
        return _loop_result("end_turn", dossier=None, cost=0.01)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.results[0].task_completion is True


def test_error_entry_fails_when_dossier_emitted(tmp_path):
    """task_completion_expected=False entry fails if a dossier is emitted."""
    gold = _gold_file(tmp_path, [ERROR_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        if on_turn:
            on_turn(1, "tool_use", [
                _Block("tool_use", "get_market_data"),
                _Block("tool_use", "submit_dossier"),
            ])
        # Model emitted a dossier despite an invalid ticker — this is wrong.
        return _loop_result("submit_dossier", dossier=_make_dossier(), cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.results[0].task_completion is False


def test_run_eval_empty_gold(tmp_path):
    """Empty gold set: zero metrics trigger both thresholds → gate fails."""
    gold = tmp_path / "empty.jsonl"
    gold.write_text("", encoding="utf-8")

    with patch("app.evals.runner.loop_run"):
        with _patch_fixtures():
            report = run_eval(gold_path=gold)

    assert report.total_entries == 0
    assert report.gate_pass is False  # 0% < 85% and 0% < 80%


def test_run_eval_entry_result_fields(tmp_path):
    """EntryResult carries all expected fields."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=0.07, turns=4)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
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
# Tests: missing fixture → loud error (review finding #3, extended to 3 types)
# ---------------------------------------------------------------------------

def _empty_fixture_dirs(tmp_path: Path):
    """Return (fixtures_dir, ws_dir, wf_dir) all empty."""
    d = tmp_path / "fixtures"
    d.mkdir()
    ws = d / "web_search"
    ws.mkdir()
    wf = d / "web_fetch"
    wf.mkdir()
    return d, ws, wf


def test_missing_market_data_fixture_raises(tmp_path, monkeypatch):
    """Missing get_market_data fixture → FileNotFoundError before API calls."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    d, ws, wf = _empty_fixture_dirs(tmp_path)
    # Provide web_search and web_fetch fixtures but NOT market data.
    (ws / "AAPL.json").write_text("{}")
    (wf / "AAPL.json").write_text("{}")
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", d)
    monkeypatch.setattr("app.evals.runner.WEB_SEARCH_FIXTURES_DIR", ws)
    monkeypatch.setattr("app.evals.runner.WEB_FETCH_FIXTURES_DIR", wf)

    with pytest.raises(FileNotFoundError, match="Missing fixtures"):
        run_eval(gold_path=gold)


def test_missing_web_search_fixture_raises(tmp_path, monkeypatch):
    """Missing web_search fixture → FileNotFoundError before API calls."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    d, ws, wf = _empty_fixture_dirs(tmp_path)
    (d / "AAPL.json").write_text("{}")
    # web_search missing; web_fetch present
    (wf / "AAPL.json").write_text("{}")
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", d)
    monkeypatch.setattr("app.evals.runner.WEB_SEARCH_FIXTURES_DIR", ws)
    monkeypatch.setattr("app.evals.runner.WEB_FETCH_FIXTURES_DIR", wf)

    with pytest.raises(FileNotFoundError, match="Missing fixtures"):
        run_eval(gold_path=gold)


def test_missing_web_fetch_fixture_raises(tmp_path, monkeypatch):
    """Missing web_fetch fixture → FileNotFoundError before API calls."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    d, ws, wf = _empty_fixture_dirs(tmp_path)
    (d / "AAPL.json").write_text("{}")
    (ws / "AAPL.json").write_text("{}")
    # web_fetch missing
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", d)
    monkeypatch.setattr("app.evals.runner.WEB_SEARCH_FIXTURES_DIR", ws)
    monkeypatch.setattr("app.evals.runner.WEB_FETCH_FIXTURES_DIR", wf)

    with pytest.raises(FileNotFoundError, match="Missing fixtures"):
        run_eval(gold_path=gold)


def test_fixture_error_fires_before_api_calls(tmp_path, monkeypatch):
    """The preflight check must fail before any loop_run call is made."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    d, ws, wf = _empty_fixture_dirs(tmp_path)
    monkeypatch.setattr("app.evals.runner.FIXTURES_DIR", d)
    monkeypatch.setattr("app.evals.runner.WEB_SEARCH_FIXTURES_DIR", ws)
    monkeypatch.setattr("app.evals.runner.WEB_FETCH_FIXTURES_DIR", wf)

    with patch("app.evals.runner.loop_run") as mock_loop:
        with pytest.raises(FileNotFoundError):
            run_eval(gold_path=gold)
    mock_loop.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: per-entry exception isolation + infra retry
# ---------------------------------------------------------------------------

def test_non_infra_exception_does_not_abort_gate(tmp_path):
    """A non-infra exception (RuntimeError) counts as behaviour failure; gate continues."""
    import anthropic as _anthropic
    gold = _gold_file(tmp_path, [AAPL_ENTRY, ERROR_ENTRY])
    call_n = [0]

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        call_n[0] += 1
        if ticker == "AAPL":
            raise RuntimeError("unexpected bug")
        if on_turn:
            on_turn(1, "tool_use", [_Block("tool_use", "get_market_data")])
        return _loop_result("end_turn", dossier=None, cost=0.01)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.total_entries == 2
    assert call_n[0] == 2  # both entries attempted

    aapl = report.results[0]
    assert aapl.terminated_by == "runner_error"  # non-infra failure label
    assert aapl.task_completion is False
    assert aapl.cost_usd == 0.0

    invalid = report.results[1]
    assert invalid.task_completion is True


def test_infra_timeout_retried_and_succeeds(tmp_path):
    """APITimeoutError on first attempt is retried; success on retry counts as completion."""
    import anthropic as _anthropic
    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    call_n = [0]

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        call_n[0] += 1
        if call_n[0] == 1:
            raise _anthropic.APITimeoutError(request=None)
        # Second attempt succeeds.
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert call_n[0] == 2  # one retry happened
    assert report.results[0].task_completion is True
    assert report.results[0].terminated_by == "submit_dossier"


def test_infra_timeout_exhausts_retries_counts_as_infra_failure(tmp_path):
    """APITimeoutError on all attempts marks entry as runner_infra_error, not runner_error."""
    import anthropic as _anthropic
    gold = _gold_file(tmp_path, [AAPL_ENTRY])

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        raise _anthropic.APITimeoutError(request=None)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    r = report.results[0]
    assert r.terminated_by == "runner_infra_error"
    assert r.task_completion is False


def test_all_entries_error_gate_fails(tmp_path):
    """If every entry raises, gate reports 0% completion and fails."""
    gold = _gold_file(tmp_path, [AAPL_ENTRY, AAPL_ENTRY])

    with patch("app.evals.runner.loop_run", side_effect=RuntimeError("timeout")):
        with _patch_fixtures():
            report = run_eval(gold_path=gold, max_turns=5)

    assert report.total_entries == 2
    assert report.task_completion_rate == 0.0
    assert report.gate_pass is False


# ---------------------------------------------------------------------------
# Tests: eval mode wiring — EVAL_TOOLS and temperature passed to loop_run
# ---------------------------------------------------------------------------

def test_loop_run_receives_eval_tools_and_temperature(tmp_path):
    """run_eval must pass EVAL_TOOLS and temperature=0 to loop_run."""
    from app.tools.inventory import EVAL_TOOLS
    from app.evals.runner import EVAL_TEMPERATURE

    gold = _gold_file(tmp_path, [AAPL_ENTRY])
    captured: dict = {}

    def fake_loop(ticker, *, max_turns=None, on_turn=None, tools=None, temperature=None):
        captured["tools"] = tools
        captured["temperature"] = temperature
        if on_turn:
            on_turn(1, "tool_use", _full_aapl_content())
        return _loop_result("submit_dossier", cost=0.05)

    with patch("app.evals.runner.loop_run", side_effect=fake_loop):
        with _patch_fixtures():
            run_eval(gold_path=gold, max_turns=5)

    assert captured["tools"] is EVAL_TOOLS
    assert captured["temperature"] == EVAL_TEMPERATURE
