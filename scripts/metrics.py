"""Agent metrics from Langfuse traces (Spec 06, ADR-008, block-G).

Fetches recent ``research`` traces from Langfuse and computes the six
agent-specific metrics defined in Spec 06:

  1. task_completion_rate   — % runs that produced a valid dossier
  2. tool_error_rate        — tool errors / total client tool calls, by tool
  3. latency p50/p95/p99    — end-to-end seconds per execution
  4. cost mean/p50/p95      — USD per execution
  5. turns mean/p50/p95     — loop turns per execution
  6. tool_use_accuracy      — requires annotated eval set; see /eval

Usage (from repo root):
    cd backend && uv run python ../scripts/metrics.py
    cd backend && uv run python ../scripts/metrics.py --days 7 --limit 50
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


# ---------------------------------------------------------------------------
# .env loader (no pydantic dependency at script level)
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Langfuse REST client (stdlib only)
# ---------------------------------------------------------------------------

def _lf_get(base_url: str, public_key: str, secret_key: str, path: str, params: dict) -> dict:
    creds = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    query = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items())
    url = f"{base_url.rstrip('/')}{path}?{query}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Langfuse API returned {exc.code} — check credentials and base URL", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"ERROR: Cannot reach Langfuse ({exc.reason})", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Percentile helper (stdlib statistics is p50 only)
# ---------------------------------------------------------------------------

def _pct(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    # Linear interpolation index
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _mean(data: list[float]) -> float:
    return sum(data) / len(data) if data else 0.0


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    # Langfuse timestamps: "2024-01-15T12:34:56.789Z" or "…+00:00"
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts[:26], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print agent metrics from Langfuse traces."
    )
    parser.add_argument("--days", type=int, default=30, help="Lookback window (default: 30)")
    parser.add_argument("--limit", type=int, default=100, help="Max traces to fetch (default: 100, Langfuse max per page: 100)")
    args = parser.parse_args()

    env = _load_dotenv(_ENV_FILE)
    # Shell env vars override .env (12-factor)
    env.update({k: v for k, v in os.environ.items()})

    public_key = env.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = env.get("LANGFUSE_SECRET_KEY", "")
    base_url = (
        env.get("LANGFUSE_BASE_URL")
        or env.get("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    )

    if not public_key or not secret_key:
        print(
            "ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set "
            "(in .env or shell environment)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Langfuse expects ISO 8601 with milliseconds: "2024-01-15T12:00:00.000Z"
    from_ts = (
        datetime.now(tz=timezone.utc) - timedelta(days=args.days)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    print(f"Querying Langfuse ({base_url}) — last {args.days} days, up to {args.limit} traces…")

    limit = min(args.limit, 100)  # Langfuse API caps at 100 per page
    data = _lf_get(
        base_url,
        public_key,
        secret_key,
        "/api/public/traces",
        {
            "name": "research",
            "fromTimestamp": from_ts,
            "limit": limit,
            "page": 1,
        },
    )

    traces = data.get("data", [])
    if not traces:
        print(f"\nNo 'research' traces found in the last {args.days} days.")
        print("Run the agent first: cd backend && uv run python -m app.agent.run --ticker AAPL")
        return

    # ---------------------------------------------------------------------------
    # Extract per-trace values
    # ---------------------------------------------------------------------------
    total = len(traces)
    completed = 0
    costs: list[float] = []
    latencies_s: list[float] = []
    turns_list: list[int] = []
    total_tool_calls = 0
    total_tool_errors = 0
    terminated_by_counts: dict[str, int] = {}

    for t in traces:
        output = t.get("output") or {}
        terminated_by = output.get("terminated_by", "unknown")
        terminated_by_counts[terminated_by] = terminated_by_counts.get(terminated_by, 0) + 1

        if terminated_by == "submit_dossier":
            completed += 1

        # Cost: prefer totalCost from Langfuse aggregation; fall back to metadata
        cost = t.get("totalCost") or output.get("total_cost_usd") or 0.0
        costs.append(float(cost))

        # Latency
        t0 = _parse_ts(t.get("createdAt") or t.get("created_at"))
        t1 = _parse_ts(t.get("updatedAt") or t.get("updated_at"))
        if t0 and t1 and t1 >= t0:
            latencies_s.append((t1 - t0).total_seconds())

        # Turns
        turns = output.get("total_turns")
        if turns is not None:
            try:
                turns_list.append(int(turns))
            except (TypeError, ValueError):
                pass

        # Tool error rate (stored in finish() output since block-G)
        tc = output.get("tool_calls") or 0
        te = output.get("tool_errors") or 0
        total_tool_calls += int(tc)
        total_tool_errors += int(te)

    # ---------------------------------------------------------------------------
    # Render
    # ---------------------------------------------------------------------------
    sep = "─" * 62
    print(f"\n{'AGENT METRICS':^62}")
    print(sep)
    print(f"  Traces analysed : {total}  (last {args.days} days)")
    print(sep)

    # 1. Task completion rate
    rate = completed / total if total > 0 else 0.0
    print(f"\n  1. Task completion rate")
    print(f"       {rate:.1%}  ({completed} / {total} runs produced a valid dossier)")
    print(f"       Breakdown by terminated_by:")
    for reason, cnt in sorted(terminated_by_counts.items(), key=lambda x: -x[1]):
        print(f"         {reason:<30s}  {cnt:>4}  ({cnt/total:.0%})")

    # 2. Tool error rate
    print(f"\n  2. Tool error rate (client tools only)")
    if total_tool_calls > 0:
        err_rate = total_tool_errors / total_tool_calls
        print(f"       {err_rate:.1%}  ({total_tool_errors} errors / {total_tool_calls} calls)")
    else:
        print("       n/a  (no tool_calls recorded — needs block-G traces)")

    # 3. Latency
    print(f"\n  3. Latency per execution")
    if latencies_s:
        print(f"       p50 = {_pct(latencies_s, 50):.1f}s")
        print(f"       p95 = {_pct(latencies_s, 95):.1f}s")
        print(f"       p99 = {_pct(latencies_s, 99):.1f}s")
        print(f"       min = {min(latencies_s):.1f}s   max = {max(latencies_s):.1f}s")
    else:
        print("       n/a  (no timestamp data found in traces)")

    # 4. Cost
    print(f"\n  4. Cost per execution (USD)")
    if costs:
        nonzero = [c for c in costs if c > 0]
        if nonzero:
            print(f"       mean = ${_mean(nonzero):.4f}")
            print(f"       p50  = ${_pct(nonzero, 50):.4f}")
            print(f"       p95  = ${_pct(nonzero, 95):.4f}")
            # Budget alert
            from_config = float(env.get("AGENT_BUDGET_USD", "0.50"))
            p95 = _pct(nonzero, 95)
            if p95 >= from_config * 0.80:
                print(
                    f"       ⚠  p95 (${p95:.4f}) is ≥80% of the budget cap (${from_config:.2f}). "
                    "Consider tightening the turn cap or tool result size."
                )
        else:
            print("       all traces report $0 cost (Langfuse cost tracking not configured)")
    else:
        print("       n/a")

    # 5. Turns
    print(f"\n  5. Turns per execution")
    if turns_list:
        print(f"       mean = {_mean([float(t) for t in turns_list]):.1f}")
        print(f"       p50  = {_pct([float(t) for t in turns_list], 50):.1f}")
        print(f"       p95  = {_pct([float(t) for t in turns_list], 95):.1f}")
        print(f"       min = {min(turns_list)}   max = {max(turns_list)}")
        # Turn limit alert: read from config or default 20
        hard_limit = int(env.get("AGENT_MAX_TURNS", "20"))
        p95_turns = _pct([float(t) for t in turns_list], 95)
        if p95_turns >= hard_limit * 0.80:
            print(
                f"       ⚠  p95 ({p95_turns:.1f} turns) is ≥80% of the hard limit ({hard_limit}). "
                "Consider raising the limit or improving agent efficiency."
            )
    else:
        print("       n/a  (total_turns not present in older traces)")

    # 6. Tool use accuracy
    print(f"\n  6. Tool use accuracy")
    print("       Requires annotated eval set. Run: cd backend && uv run pytest tests/evals -v")
    print("       Or use the /eval slash command for the full metric.")

    print(f"\n{sep}")
    print(f"  Langfuse dashboard: {base_url.rstrip('/')}/")
    print(sep)


if __name__ == "__main__":
    main()
