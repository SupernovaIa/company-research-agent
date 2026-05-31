# SESSION.md — Estado de la sesión actual

> Fichero dinámico. Se actualiza al inicio y al final de cada sesión de construcción. Cualquier agente que abra el repo lee este fichero para saber dónde se quedó el trabajo.

## Sesión actual

**Sesión:** block-F
**Estado:** gate_pending
**Fecha apertura:** 2026-05-31
**Última actualización:** 2026-05-31

## Objetivo de la sesión

Implementar la defensa en capas frente a indirect prompt injection (Spec 04, parte pendiente de block-E) y la checklist de red teaming con gate de bloqueo (Spec 09): system prompt que marca el contenido de tools como datos, delimitadores del contenido externo, clasificador de output con Haiku 4.5 y mínimo privilegio. Aceptar Spec 09 y completar Spec 04 (a aceptada del todo).

## Próxima acción concreta

Abrir la PR de `feat/injection-redteam` a `main`, correr **security-review** sobre la PR (gate de este bloque, no code-review), postear el resultado como comentario y parar. Merge (squash) + tag `06-block-F` son acción humana.

## Pendientes en esta sesión

- [ ] Merge (squash) de la PR a `main` y tag `06-block-F` (acción humana).
- [ ] (Opcional) Backstop live del clasificador Haiku con evidencia en trazas Langfuse, bajo presupuesto controlado (modo live de `/redteam`).

## Completado en esta sesión

- [x] **L1 · Delimitadores** (`backend/app/guardrails/injection.py`): `wrap_external_content` envuelve el contenido de tools en `<<UNTRUSTED_TOOL_CONTENT>> … <<END_UNTRUSTED_TOOL_CONTENT>>` y sanitiza falsificación de frontera y de turnos (`System:`/`User:`/`Assistant:`). Cableado en `agent/loop.py` al construir los `tool_result`.
- [x] **L2 · System prompt** (`prompts/system_prompt_v1.md`): sección "Untrusted tool content (security)" — contenido de tools como datos, prohibición de obedecer instrucciones embebidas, revelar el prompt, cambiar de tarea, usar code execution para recomendar, emitir veredictos de compra/venta.
- [x] **L3 · Clasificador de output** (`backend/app/guardrails/classifier.py`): pre-filtro determinista (`heuristic_scan`) + backstop semántico con **Haiku 4.5** (`GUARDRAIL_MODEL`), cliente dedicado con su propio timeout (`classifier_timeout_s=15`). El loop descarta el dossier (`terminated_by="guardrail_blocked"`) si no pasa. Degrada con elegancia: sin API key, modo solo-heurístico; error del clasificador no brickea el agente si la heurística pasó.
- [x] **L4 · Mínimo privilegio** (`injection.py`): inventario read-only declarado; `capability_is_available` confirma que ninguna capacidad con efectos secundarios (send_email, delete, http_post, …) tiene tool.
- [x] **Harness de red team** (`backend/app/redteam/`): `payloads.py` (24 payloads, fuente de verdad), `runner.py` (ejecuta cada payload contra su capa, `THRESHOLD=0.90`), `run.py` (`python -m app.redteam.run [--ci|--json]`, exit 1 si < umbral).
- [x] **Checklist** (`security/red-team-checklist.md`): 24 payloads con OWASP, categoría, vector, capa esperada y resultado; sincronía con `payloads.py` verificada por test.
- [x] **Slash command `/redteam`** cableado al runner determinista + modo live, delegando en el subagente `redteam-runner`.
- [x] **Observabilidad** (`observability/tracer.py`): `record_guardrail` añade el span `output_guardrail` (capa que actuó, allowed, reason) a la traza.
- [x] **ADR-013** (defensa en capas + red team, mapeo OWASP) e índice en `DECISIONS.md`.
- [x] **Specs**: Spec 09 → aceptada; Spec 04 → aceptada del todo (sección de la capa de inyección añadida).
- [x] **Tests** (todos verdes): `test_injection.py`, `test_classifier.py`, `test_redteam.py`, `conftest.py` (fixture autouse que neutraliza la llamada Haiku en los tests del loop). 84 passed.

## Subagentes usados en esta sesión

- `redteam-runner`: cableado vía `/redteam` para ejecutar el harness y reportar PASS/FAIL (gate humano sobre el resultado, ADR-009).

## Blockers

- Ninguno.

## Decisiones tomadas en esta sesión

- **Gate de red team determinista y offline como canónico** (ADR-013): el runner ejercita cada capa sin llamar al modelo → gratis, reproducible, gateable en CI. El backstop semántico de Haiku (L3b) se valida aparte en modo live con evidencia en Langfuse. Evita un gate que dependa de API y red.
- **Clasificador con Haiku 4.5** (distinto del agente Sonnet): sin sesgo de auto-aprobación (Spec 04).
- **Pre-filtro heurístico determinista** además del clasificador semántico: bloquea lo obvio sin coste y hace cada capa verificable offline.
- **Wrap uniforme de todos los `tool_result`**: defensa consistente; el delimitador solo enmarca datos.
- **`terminated_by="guardrail_blocked"`**: nuevo estado cuando el clasificador descarta un dossier schema-válido pero inseguro.

## Coste de la sesión

- ~$0 USD: el gate canónico es determinista (sin llamadas al modelo). No se ejecutó el agente en vivo (backstop Haiku/Langfuse documentado como paso complementario bajo presupuesto).

## Notas de handoff

- El backstop live del clasificador (Haiku + trazas Langfuse) está cableado (`record_guardrail`, span `output_guardrail`) pero no ejecutado en esta sesión para respetar la disciplina de coste. Modo live disponible en `/redteam`.
- La heurística L3 es por patrones (regex): cubre lo obvio; lo semántico depende del backstop Haiku.

## Comandos útiles ahora

```bash
cd backend

# Gate de red team (determinista)
uv run python -m app.redteam.run         # tabla
uv run python -m app.redteam.run --ci    # gate (exit 1 si < 90%)

# Suite de tests
uv run pytest -q --ignore=tests/evals
```

## Gate de revisión

- **Criterio:** `/redteam` da PASS ≥ 90% y cada capa (L1–L4) bloquea su payload; las cuatro capas implementadas y cableadas; suite verde. **Gate de este bloque: security-review** (no code-review).
- **Resultado:** pasa (pendiente gate de PR / security-review).
- **Evidencia:**
  - `python -m app.redteam.run` → **24/24 PASS, bloqueo 100.0%** (umbral 90%), cobertura por capa `{L1:6, L2:5, L3:7, L4:6}`, exit 0.
  - Suite completa: **84 passed** (`--ignore=tests/evals`).
  - Span `output_guardrail` añadido a la traza Langfuse para evidencia de capa en modo live.
