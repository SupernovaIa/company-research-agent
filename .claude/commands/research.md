---
description: Ejecuta el agente de research sobre un ticker o empresa y muestra el dossier y la traza del loop
---

Run the research agent against a ticker or company name and show the resulting dossier and the loop trace.

Execute these steps:

1. Read the input argument. Accept either a ticker (e.g. `SHOP`) or a company name (e.g. `Shopify`). If no argument is provided, ask the user for one. If the input is ambiguous (could match several companies), surface the candidates and ask for confirmation before running.
2. Run the agent against the `/research` endpoint (or the local runner if the server is not up).
3. Stream the loop events as they arrive over SSE, one line per turn:
   - The tool invoked, its validated input, and whether it ran client-side or server-side.
   - The tool result summary (truncated, not the raw blob).
   - The model decision for the next turn.
4. Once the loop reaches `end_turn`, show the final dossier only after it has passed Pydantic validation against the dossier schema. If validation failed, show the validation error and the partial output instead.
5. Show a loop summary table:
   - Turns used vs the configured turn cap.
   - Tools used and how many times each.
   - Total cost in USD (input + output tokens).
   - End-to-end latency.
6. Print the Langfuse trace URL for this run so the user can inspect it in detail.
