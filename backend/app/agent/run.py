"""CLI entry point for the research agent.

Usage::

    uv run python -m app.agent.run --ticker AAPL
    uv run python -m app.agent.run --ticker SAP.DE --verbose

Requires ANTHROPIC_API_KEY in the environment.
Optionally: LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY for tracing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )
    # Quiet noisy third-party loggers in normal mode.
    if not verbose:
        for noisy in ("httpx", "httpcore", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _on_turn(turn: int, stop_reason: str, content: list) -> None:
    tool_names = [
        b.name for b in content if getattr(b, "type", None) == "tool_use"
    ]
    server_tools = [
        b.name
        for b in content
        if getattr(b, "type", None) == "server_tool_use"
    ]
    parts = [f"turn={turn}", f"stop={stop_reason}"]
    if tool_names:
        parts.append(f"client_tools={tool_names}")
    if server_tools:
        parts.append(f"server_tools={server_tools}")
    print(f"  [{', '.join(parts)}]", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research a publicly listed company and print a structured dossier."
    )
    parser.add_argument(
        "--ticker",
        required=True,
        help="Exchange ticker symbol, e.g. AAPL or SAP.DE",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    _configure_logging(args.verbose)

    # Lazy import so logging is configured first.
    from app.agent.loop import run

    ticker = args.ticker.strip().upper()
    print(f"Researching {ticker} …", flush=True)

    result = run(ticker, on_turn=_on_turn)

    print()
    print(f"Terminated by : {result.terminated_by}")
    print(f"Turns         : {result.turns}")
    print(f"Cost (est.)   : ${result.cost_usd:.4f} USD")
    print()

    if result.dossier is not None:
        print(
            json.dumps(
                result.dossier.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    else:
        _reasons = {
            "submit_dossier_failed": (
                "submit_dossier was called but failed schema validation twice. "
                "Check the validation errors above."
            ),
            "end_turn": "The model stopped without calling submit_dossier.",
            "hard_limit": "The loop hit the turn limit without calling submit_dossier.",
        }
        reason = _reasons.get(
            result.terminated_by,
            f"Loop ended with reason: {result.terminated_by!r}.",
        )
        print(f"No dossier produced. {reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
