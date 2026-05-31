"""Red-team checklist entry point (Spec 09).

Usage::

    uv run python -m app.redteam.run          # human-readable report
    uv run python -m app.redteam.run --ci      # headless gate (CI)
    uv run python -m app.redteam.run --json     # machine-readable

Exit code 0 if the block rate meets the threshold (PASS >= 90%), else 1, so it
can gate CI and the redteam-runner subagent can read the verdict from $?.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.redteam.runner import format_report, run_checklist


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the prompt-injection red-team checklist.")
    parser.add_argument("--ci", action="store_true", help="Headless mode for CI gating.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args()

    report = run_checklist()

    if args.json:
        print(
            json.dumps(
                {
                    "total": report.total,
                    "passed": report.passed,
                    "failed": [r.payload.id for r in report.failed],
                    "pass_rate": report.pass_rate,
                    "gate_ok": report.gate_ok,
                    "layers_covered": report.layers_covered(),
                    "results": [
                        {
                            "id": r.payload.id,
                            "category": r.payload.category,
                            "owasp": r.payload.owasp,
                            "expected_layer": r.payload.expected_layer,
                            "actual_layer": r.actual_layer,
                            "passed": r.passed,
                            "detail": r.detail,
                        }
                        for r in report.results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(report))

    return 0 if report.gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
