"""Eval dataset runner (Spec 07, Spec 08).

Loads evals/gold.jsonl, runs each entry through the loop in **eval mode**, and
computes three gate metrics: task_completion_rate, tool_use_accuracy, and
mean_cost_usd.  Optionally exits non-zero when a gate threshold is missed.

## Eval mode vs production

In production the loop uses Anthropic server tools (web_search, web_fetch,
code_execution) that Anthropic executes inline — their results arrive already
resolved in the same HTTP response and cannot be intercepted by the client.

In eval mode these are replaced by semantically-equivalent **client tools**
(EVAL_TOOLS) with the same ``name``.  The model generates the same
``tool_use`` blocks; the runner intercepts them and returns pre-recorded
fixtures from ``evals/fixtures/web_search/<TICKER>.json`` and
``evals/fixtures/web_fetch/<TICKER>.json``.  get_market_data likewise uses
its fixture from ``evals/fixtures/<TICKER>.json``.

This makes the external data layer fully deterministic so a yfinance or web
outage cannot break the gate.  The **model is still called live** — that is
what the gate measures: which tools the model chooses to call and whether it
produces a valid dossier from the fixture content.

The **output guardrail classifier** (Haiku) is bypassed in eval mode.
Rationale: the gate measures research agent behaviour (tool selection, dossier
validity); the guardrail has its own dedicated tests (redteam suite and
``test_classifier.py``).  Including the guardrail in the gate would add
non-determinism from the Haiku classifier's own sampling variance and would
cause false negatives when valid research dossiers are blocked for stylistic
reasons.  The bypass mirrors the ``conftest.py`` autouse fixture used in unit
tests.

The model is called at temperature=0 to reduce between-run variance and
keep gate thresholds stable across re-runs.

End-to-end evaluation against live data (web_search and web_fetch calling real
URLs, no fixtures) is reserved for the scheduled nightly job, not the PR gate.

Usage (from backend/):
    uv run python -m app.evals.runner            # print report
    uv run python -m app.evals.runner --ci       # exit 1 if gate fails
    uv run python -m app.evals.runner --json     # also write eval-report.json
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from unittest.mock import patch

import anthropic as _anthropic

from app.agent.loop import run as loop_run
from app.config import settings
from app.guardrails.classifier import Verdict
from app.tools.client import ToolResult, dispatch_client_tool as _orig_dispatch
from app.tools.inventory import EVAL_TOOLS

# Transient infrastructure exceptions that warrant an entry-level retry.
_INFRA_EXCEPTIONS = (
    _anthropic.APITimeoutError,
    _anthropic.APIConnectionError,
)
# Max per-entry retries for transient infra errors before counting as failed.
EVAL_ENTRY_MAX_RETRIES = 2

# Guardrail verdict injected in eval mode: always allow so gate variance comes
# only from the model, not from the Haiku classifier's own sampling.
_EVAL_GUARDRAIL_VERDICT = Verdict(allowed=True, reason="eval-mode bypass", layer="eval")

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLD_JSONL = _REPO_ROOT / "evals" / "gold.jsonl"
FIXTURES_DIR = _REPO_ROOT / "evals" / "fixtures"
WEB_SEARCH_FIXTURES_DIR = FIXTURES_DIR / "web_search"
WEB_FETCH_FIXTURES_DIR = FIXTURES_DIR / "web_fetch"

# Temperature used for all eval runs. 0 = greedy decoding; minimises
# between-run variance so gate thresholds remain stable (refinement #4).
EVAL_TEMPERATURE = 0.0

# Gate thresholds (Spec 07).
TASK_COMPLETION_THRESHOLD = 0.85
TOOL_ACCURACY_THRESHOLD = 0.80

# Per-entry turn limit for eval runs (keeps cost bounded).
EVAL_MAX_TURNS = 10


@dataclass
class EntryResult:
    ticker: str
    category: str
    task_completion_expected: bool
    terminated_by: str
    task_completion: bool
    tool_use_accurate: bool
    actual_tool_calls: list[str]
    expected_tool_calls: list[str]
    cost_usd: float
    turns: int


@dataclass
class EvalReport:
    task_completion_rate: float
    tool_use_accuracy: float
    mean_cost_usd: float
    total_entries: int
    gate_pass: bool
    failures: list[str]
    # Per-metric pass booleans — single source of truth for the CI JS badge.
    # Avoids hardcoding Python threshold constants in the workflow script.
    task_completion_pass: bool = True
    tool_accuracy_pass: bool = True
    cost_pass: bool = True
    # Threshold values at eval time — read by CI JS for the threshold column.
    thresholds: dict = field(default_factory=dict)
    results: list[EntryResult] = field(default_factory=list)


def load_gold_set(path: Path | None = None) -> list[dict]:
    """Load JSONL entries from *path* (defaults to evals/gold.jsonl)."""
    gold_path = path or GOLD_JSONL
    entries = []
    with gold_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _load_fixture(ticker: str) -> dict:
    """Return the pre-recorded get_market_data payload for *ticker*.

    Raises FileNotFoundError if the fixture is absent — called by the preflight
    check; individual per-entry loads are covered by _load_web_* helpers below.
    """
    path = FIXTURES_DIR / f"{ticker}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing get_market_data fixture for '{ticker}': {path}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_web_search_fixture(ticker: str) -> dict:
    """Return the pre-recorded web_search payload for *ticker*."""
    path = WEB_SEARCH_FIXTURES_DIR / f"{ticker}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing web_search fixture for '{ticker}': {path}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_web_fetch_fixture(ticker: str) -> dict:
    """Return the pre-recorded web_fetch payload for *ticker*."""
    path = WEB_FETCH_FIXTURES_DIR / f"{ticker}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing web_fetch fixture for '{ticker}': {path}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_names_from_content(content: list) -> list[str]:
    """Extract tool names from an assistant turn's content blocks.

    Captures both client (type='tool_use') and server-side calls
    (type='server_tool_use') so expected_tool_calls can match web_search etc.
    """
    names = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype in ("tool_use", "server_tool_use"):
            name = getattr(block, "name", None)
            if name:
                names.append(name)
    return names


def run_eval(
    gold_path: Path | None = None,
    max_turns: int = EVAL_MAX_TURNS,
) -> EvalReport:
    """Run all gold-set entries in eval mode and return an EvalReport.

    All three external data sources (get_market_data, web_search, web_fetch)
    are served from pre-recorded fixtures so network failures cannot break the
    gate.  The model is called live at temperature=0 via EVAL_TOOLS (client
    tool equivalents of the production server tools).  See module docstring.
    """
    entries = load_gold_set(gold_path)

    # Pre-flight: verify all three fixture types exist for every gold-set ticker
    # before spending any API tokens (Spec 07 determinism guarantee).
    missing: list[str] = []
    for e in entries:
        t = e["ticker"]
        if not (FIXTURES_DIR / f"{t}.json").exists():
            missing.append(f"{t} (get_market_data)")
        if not (WEB_SEARCH_FIXTURES_DIR / f"{t}.json").exists():
            missing.append(f"{t} (web_search)")
        if not (WEB_FETCH_FIXTURES_DIR / f"{t}.json").exists():
            missing.append(f"{t} (web_fetch)")
    if missing:
        raise FileNotFoundError(
            f"Missing fixtures: {missing}\n"
            "Create the corresponding files under evals/fixtures/ before "
            "running the eval gate."
        )

    cost_cap = settings.agent_budget_usd
    results: list[EntryResult] = []

    for entry in entries:
        ticker = entry["ticker"]
        expected_calls = set(entry["expected_tool_calls"])
        task_completion_expected: bool = entry["task_completion_expected"]

        actual_calls: list[str] = []

        def on_turn(turn, stop_reason, content, _log=actual_calls):
            _log.extend(_tool_names_from_content(content))

        mkt_fixture = _load_fixture(ticker)
        ws_fixture = _load_web_search_fixture(ticker)
        wf_fixture = _load_web_fetch_fixture(ticker)

        def _patched_dispatch(
            name, input_data,
            _mkt=mkt_fixture, _ws=ws_fixture, _wf=wf_fixture,
        ):
            # All external data is served from fixtures (Spec 07 determinism).
            # submit_dossier falls through to the real dispatcher for Pydantic
            # validation — that is intentional and must stay live.
            if name == "get_market_data":
                return ToolResult(json_response=_mkt)
            if name == "web_search":
                return ToolResult(json_response=_ws)
            if name == "web_fetch":
                return ToolResult(json_response=_wf)
            return _orig_dispatch(name, input_data)

        with patch("app.agent.loop.dispatch_client_tool", side_effect=_patched_dispatch), \
             patch("app.agent.loop.classify_dossier",
                   side_effect=lambda dossier, **kw: _EVAL_GUARDRAIL_VERDICT):
            loop_result = None
            for attempt in range(1, EVAL_ENTRY_MAX_RETRIES + 2):  # attempts = retries + 1
                actual_calls.clear()
                try:
                    loop_result = loop_run(
                        ticker,
                        max_turns=max_turns,
                        on_turn=on_turn,
                        tools=EVAL_TOOLS,
                        temperature=EVAL_TEMPERATURE,
                    )
                    break  # success — exit retry loop
                except _INFRA_EXCEPTIONS as exc:
                    # Transient infra error (timeout, connection drop).
                    # Retry up to EVAL_ENTRY_MAX_RETRIES times before giving up.
                    if attempt <= EVAL_ENTRY_MAX_RETRIES:
                        logger.warning(
                            "[%s] infra error on attempt %d/%d (%s: %s) — retrying",
                            ticker, attempt, EVAL_ENTRY_MAX_RETRIES + 1,
                            type(exc).__name__, exc,
                        )
                    else:
                        logger.error(
                            "[%s] infra error after %d attempts (%s: %s) — "
                            "counting as failed entry (infra, not behaviour)",
                            ticker, attempt, type(exc).__name__, exc,
                        )
                        results.append(EntryResult(
                            ticker=ticker,
                            category=entry["category"],
                            task_completion_expected=task_completion_expected,
                            terminated_by="runner_infra_error",
                            task_completion=False,
                            tool_use_accurate=False,
                            actual_tool_calls=[],
                            expected_tool_calls=sorted(expected_calls),
                            cost_usd=0.0,
                            turns=0,
                        ))
                        loop_result = None
                        break
                except Exception as exc:
                    # Non-infra exception (e.g. bug in the runner, validation error).
                    # Do not retry — log and mark as behaviour failure.
                    logger.error(
                        "[%s] unexpected error (%s: %s) — "
                        "counting as failed entry (behaviour, not infra)",
                        ticker, type(exc).__name__, exc,
                    )
                    results.append(EntryResult(
                        ticker=ticker,
                        category=entry["category"],
                        task_completion_expected=task_completion_expected,
                        terminated_by="runner_error",
                        task_completion=False,
                        tool_use_accurate=False,
                        actual_tool_calls=[],
                        expected_tool_calls=sorted(expected_calls),
                        cost_usd=0.0,
                        turns=0,
                    ))
                    loop_result = None
                    break

            if loop_result is None:
                continue

        actual_set = set(actual_calls)

        if task_completion_expected:
            task_complete = loop_result.terminated_by == "submit_dossier"
        else:
            # Error entries pass when the agent does NOT emit a dossier.
            task_complete = loop_result.dossier is None

        tool_accurate = expected_calls.issubset(actual_set)

        results.append(EntryResult(
            ticker=ticker,
            category=entry["category"],
            task_completion_expected=task_completion_expected,
            terminated_by=loop_result.terminated_by,
            task_completion=task_complete,
            tool_use_accurate=tool_accurate,
            actual_tool_calls=sorted(actual_set),
            expected_tool_calls=sorted(expected_calls),
            cost_usd=loop_result.cost_usd,
            turns=loop_result.turns,
        ))
        logger.info(
            "[%s] terminated=%s accurate=%s cost=$%.4f turns=%d",
            ticker, loop_result.terminated_by, tool_accurate,
            loop_result.cost_usd, loop_result.turns,
        )

    n = len(results)
    task_completion_rate = sum(r.task_completion for r in results) / n if n else 0.0
    tool_use_accuracy = sum(r.tool_use_accurate for r in results) / n if n else 0.0
    mean_cost = sum(r.cost_usd for r in results) / n if n else 0.0

    task_completion_pass = task_completion_rate >= TASK_COMPLETION_THRESHOLD
    tool_accuracy_pass = tool_use_accuracy >= TOOL_ACCURACY_THRESHOLD
    cost_pass = mean_cost <= cost_cap

    failures: list[str] = []
    if not task_completion_pass:
        failures.append(
            f"task_completion_rate {task_completion_rate:.2%} < "
            f"{TASK_COMPLETION_THRESHOLD:.0%}"
        )
    if not tool_accuracy_pass:
        failures.append(
            f"tool_use_accuracy {tool_use_accuracy:.2%} < {TOOL_ACCURACY_THRESHOLD:.0%}"
        )
    if not cost_pass:
        failures.append(f"mean_cost ${mean_cost:.4f} >= budget ${cost_cap:.2f}")

    return EvalReport(
        task_completion_rate=task_completion_rate,
        tool_use_accuracy=tool_use_accuracy,
        mean_cost_usd=mean_cost,
        total_entries=n,
        gate_pass=not failures,
        failures=failures,
        task_completion_pass=task_completion_pass,
        tool_accuracy_pass=tool_accuracy_pass,
        cost_pass=cost_pass,
        thresholds={
            "task_completion": TASK_COMPLETION_THRESHOLD,
            "tool_accuracy": TOOL_ACCURACY_THRESHOLD,
            "cost_budget": cost_cap,
        },
        results=results,
    )


def print_report(report: EvalReport) -> None:
    status = "PASS" if report.gate_pass else "FAIL"
    print(f"\n{'='*62}")
    print(f"Eval Gate: {status}  ({report.total_entries} entries)")
    print(f"  task_completion_rate : {report.task_completion_rate:.2%}"
          f"  (threshold {TASK_COMPLETION_THRESHOLD:.0%})")
    print(f"  tool_use_accuracy    : {report.tool_use_accuracy:.2%}"
          f"  (threshold {TOOL_ACCURACY_THRESHOLD:.0%})")
    print(f"  mean_cost_usd        : ${report.mean_cost_usd:.4f}")
    if report.failures:
        print("\nFailed gates:")
        for f in report.failures:
            print(f"  ✗ {f}")
    print(f"\n{'─'*62}")
    print(f"{'TICKER':<12} {'CATEGORY':<22} {'DONE':>4} {'ACC':>4} "
          f"{'COST':>8} {'TURNS':>5}")
    print(f"{'─'*62}")
    for r in report.results:
        done = "✓" if r.task_completion else "✗"
        acc = "✓" if r.tool_use_accurate else "✗"
        print(
            f"{r.ticker:<12} {r.category:<22} {done:>4} {acc:>4} "
            f"${r.cost_usd:>6.4f} {r.turns:>5}"
        )
    print(f"{'='*62}\n")


def build_markdown_summary(report: EvalReport) -> str:
    badge = "✅ PASS" if report.gate_pass else "❌ FAIL"
    cost_cap = settings.agent_budget_usd
    lines = [
        f"## Eval Gate: {badge}",
        "",
        "| Metric | Value | Threshold | Status |",
        "|--------|-------|-----------|--------|",
        (f"| task_completion_rate | {report.task_completion_rate:.2%} "
         f"| ≥{TASK_COMPLETION_THRESHOLD:.0%} "
         f"| {'✅' if report.task_completion_rate >= TASK_COMPLETION_THRESHOLD else '❌'} |"),
        (f"| tool_use_accuracy | {report.tool_use_accuracy:.2%} "
         f"| ≥{TOOL_ACCURACY_THRESHOLD:.0%} "
         f"| {'✅' if report.tool_use_accuracy >= TOOL_ACCURACY_THRESHOLD else '❌'} |"),
        (f"| mean_cost_usd | ${report.mean_cost_usd:.4f} "
         f"| ≤{cost_cap:.2f} "
         f"| {'✅' if report.mean_cost_usd <= cost_cap else '❌'} |"),
        "",
        "<details><summary>Per-entry results</summary>",
        "",
        "| Ticker | Category | Done | Accurate | Cost | Turns |",
        "|--------|----------|------|----------|------|-------|",
    ]
    for r in report.results:
        done = "✅" if r.task_completion else "❌"
        acc = "✅" if r.tool_use_accurate else "❌"
        lines.append(
            f"| {r.ticker} | {r.category} | {done} | {acc} "
            f"| ${r.cost_usd:.4f} | {r.turns} |"
        )
    lines += ["", "</details>"]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run the eval gate against evals/gold.jsonl"
    )
    parser.add_argument(
        "--ci", action="store_true", help="Exit 1 if gate fails (for CI use)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Write JSON report to eval-report.json"
    )
    parser.add_argument(
        "--max-turns", type=int, default=EVAL_MAX_TURNS,
        help="Max turns per entry (default: %(default)s)"
    )
    args = parser.parse_args()

    report = run_eval(max_turns=args.max_turns)
    print_report(report)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(build_markdown_summary(report))
            fh.write("\n")

    if args.json:
        report_path = Path("eval-report.json")
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(report), fh, indent=2)
        print(f"Report written to {report_path}")

    if args.ci and not report.gate_pass:
        sys.exit(1)
