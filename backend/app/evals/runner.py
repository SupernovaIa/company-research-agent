"""Eval dataset runner (Spec 07, Spec 08).

Loads evals/gold.jsonl, runs each entry through the loop with fixtures for
get_market_data (prevents yfinance failures from breaking the gate), tracks
tool calls via the on_turn callback, computes three gate metrics, and
optionally exits non-zero when the gate fails.

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

from app.agent.loop import run as loop_run
from app.config import settings
from app.tools.client import ToolResult, dispatch_client_tool as _orig_dispatch

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
GOLD_JSONL = _REPO_ROOT / "evals" / "gold.jsonl"
FIXTURES_DIR = _REPO_ROOT / "evals" / "fixtures"

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


def _load_fixture(ticker: str) -> dict | None:
    """Return the pre-recorded get_market_data payload for *ticker*, or None."""
    path = FIXTURES_DIR / f"{ticker}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


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
    """Run all gold-set entries and return an EvalReport.

    get_market_data is served from pre-recorded fixtures so yfinance or network
    failures don't break the CI gate. The model and server-side tools
    (web_search, web_fetch, code_execution) run live.
    """
    entries = load_gold_set(gold_path)
    cost_cap = settings.agent_budget_usd
    results: list[EntryResult] = []

    for entry in entries:
        ticker = entry["ticker"]
        expected_calls = set(entry["expected_tool_calls"])
        task_completion_expected: bool = entry["task_completion_expected"]

        actual_calls: list[str] = []

        def on_turn(turn, stop_reason, content, _log=actual_calls):
            _log.extend(_tool_names_from_content(content))

        fixture = _load_fixture(ticker)

        def _patched_dispatch(name, input_data, _fix=fixture):
            if name == "get_market_data" and _fix is not None:
                return ToolResult(json_response=_fix)
            return _orig_dispatch(name, input_data)

        with patch("app.agent.loop.dispatch_client_tool", side_effect=_patched_dispatch):
            loop_result = loop_run(ticker, max_turns=max_turns, on_turn=on_turn)

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

    failures: list[str] = []
    if task_completion_rate < TASK_COMPLETION_THRESHOLD:
        failures.append(
            f"task_completion_rate {task_completion_rate:.2%} < "
            f"{TASK_COMPLETION_THRESHOLD:.0%}"
        )
    if tool_use_accuracy < TOOL_ACCURACY_THRESHOLD:
        failures.append(
            f"tool_use_accuracy {tool_use_accuracy:.2%} < {TOOL_ACCURACY_THRESHOLD:.0%}"
        )
    if mean_cost > cost_cap:
        failures.append(f"mean_cost ${mean_cost:.4f} > budget ${cost_cap:.2f}")

    return EvalReport(
        task_completion_rate=task_completion_rate,
        tool_use_accuracy=tool_use_accuracy,
        mean_cost_usd=mean_cost,
        total_entries=n,
        gate_pass=not failures,
        failures=failures,
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
