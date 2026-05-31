---
description: Resume la última ejecución del agente en Langfuse
---

Summarize the most recent agent run from Langfuse, turn by turn.

Execute these steps:

1. Fetch the latest trace from Langfuse for the research agent. If no trace is found, surface it and stop.
2. Walk the loop turn by turn and show, for each turn:
   - The tool calls made, with their input, latency and token count.
   - The model decision that followed each tool result.
3. Show the run totals:
   - Total tokens (input and output).
   - Total cost in USD.
   - End-to-end latency.
4. Flag anomalies explicitly:
   - Extra turns beyond the typical distribution.
   - A tool that failed or returned an error result.
   - A turn where the model changed task mid-loop.

Do not commit any changes from this command. The purpose is inspection and reporting.
