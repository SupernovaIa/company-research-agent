---
description: Reporte de coste por ejecución del agente
---

Report the cost per run of the research agent, aggregated from recent traces.

Execute these steps:

1. Pull the recent agent runs from Langfuse (default window: the last 7 days, or accept a window argument).
2. Aggregate the cost across those runs and show:
   - Mean cost per run in USD.
   - p95 cost per run in USD.
3. Break down the cost:
   - By model (the agent model, the guardrail classifier, any server-side tool usage).
   - By tool (which tools drive the most input and output tokens).
4. Read the per-run budget from the agent ADR and compare the observed mean and p95 against it.
5. If the p95 cost is within 20% of the budget cap, raise an alert and recommend tightening the turn cap or the tool result size.

Do not commit any changes from this command. The purpose is inspection and reporting.
