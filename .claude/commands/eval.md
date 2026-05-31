---
description: Corre el set de evaluación contra el agente y muestra las métricas
---

Run the evaluation set against the agent and report the agent-specific metrics.

Execute these steps:

1. Verify the evaluation set exists at `evals/gold.jsonl` and has the expected count (~12-15 companies). If it is missing or empty, surface it explicitly and stop.
2. Run the evaluation runner against every company in the set. Stream progress so the user sees one line per company.
3. After completion, present the metrics table:
   - task completion rate
   - tool use accuracy
   - tool error rate
   - latency p95
   - mean cost per run
   - turns p95
4. Compare each metric to the thresholds defined for the agent. Mark PASS or FAIL per metric (use bold for FAIL).
5. If any threshold fails, report the overall run as FAIL.
6. List the failed runs by company, with the expected tool calls or dossier properties vs what the agent actually produced.

Do not silently skip companies. If an entry fails to parse or the agent errors out, surface it explicitly as a failed run.
