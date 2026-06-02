# SESSION.md — Estado de la sesión actual

> Fichero dinámico. Se actualiza al inicio y al final de cada sesión de construcción. Cualquier agente que abra el repo lee este fichero para saber dónde se quedó el trabajo.

## Sesión actual

**Sesión:** block-H
**Estado:** gate_pending (PR #9 abierta, gate eval-gate verde)
**Fecha apertura:** 2026-06-01
**Última actualización:** 2026-06-02

## Objetivo de la sesión

Implementar Spec 07 (Evals en CI como gate de PR) y Spec 08 (Set de evaluación del agente): set de comportamiento en `evals/gold.jsonl`, fixtures de datos de mercado + web_search + web_fetch, runner de evals con métricas de gate en eval mode (server tools sustituidas por client tools fixturizadas), y workflow de GitHub Actions que bloquea el merge si las métricas caen por debajo del umbral.

## Próxima acción concreta

Merge (squash) de PR #9 (`feat/evals-ci`) a `main` y tag `08-block-H` (acción humana). El gate eval-gate está verde (run 26807268026 SUCCESS, 13/13, $0.44).

## Pendientes en esta sesión

- [ ] Merge (squash) de la PR #9 a `main` y tag `08-block-H` (acción humana).
- [ ] (Deuda, block-I) **Suite de tests y redteam no corren en CI**: `pytest` y `python -m app.redteam.run --ci` solo se ejecutan en local. Tras el bypass del clasificador L3 en eval mode, el CI no tiene red de seguridad automática ante regresiones del guardrail. Pendiente: añadir jobs `unit-tests` y `redteam` al workflow de PR. Anotado en `.github/workflows/evals.yml`.
- [ ] (Deuda, block-I) **Afinar el prompt del clasificador Haiku** para distinguir *reporte de datos de mercado* (hechos descriptivos) de *recomendación de inversión* (verdicto explícito). Ver incidente FP-001 en `specs/04-guardrails.md`.
- [ ] (Deuda, block-I) **Job nocturno end-to-end**: evaluación live sin fixtures (web_search y web_fetch contra URLs reales). El gate de PR usa eval mode con fixtures; el job nocturno medirá comportamiento real con datos vivos.

## Completado en esta sesión

- [x] **`evals/gold.jsonl`** (13 entradas firmadas): set de comportamiento anotado con dos lotes en paralelo (`gold-annotator` A y B). Cobertura: USA large-cap ×6, USA mid-cap ×1, europea completa ×1, datos parciales ×3, tickers inexistentes ×2. Firmado humano.
- [x] **`evals/fixtures/`** (39 ficheros): market data (13), web_search (13), web_fetch (13). Fixtures ricos: ≥4 resultados de búsqueda con hechos y fechas explícitas. Tickers inexistentes con fixture de error y resultados vacíos.
- [x] **`backend/app/tools/inventory.py`** — `EVAL_TOOLS`: versiones client-tool de web_search y web_fetch con descriptions escritas para el modelo. `code_execution` omitido en eval (nunca en `expected_tool_calls`).
- [x] **`backend/app/agent/loop.py`** — parámetros `tools` y `temperature` opcionales en `run()`. No-breaking: todos los callers existentes obtienen el comportamiento por defecto.
- [x] **`backend/app/evals/runner.py`**: eval mode completo. Dispatch extendido (market data + web_search + web_fetch via fixtures). Guardrail L3 bypaseado en eval (fuente de inestabilidad: clasificador Haiku con su propio non-determinismo). Retry de infra: `APITimeoutError`/`APIConnectionError` → hasta 2 reintentos antes de marcar `runner_infra_error` (distinguido de `runner_error`, fallo de comportamiento). Preflight ruidoso para los tres tipos de fixture. `EVAL_TEMPERATURE=0.0`. Umbrales: task_completion ≥ 92% (≡ 12/13), tool_use_accuracy ≥ 80%, cost ≤ budget. `EvalReport` incluye `thresholds` y booleans por métrica para que el JS del workflow no hardcodee umbrales.
- [x] **`backend/tests/evals/test_eval_runner.py`** (25 tests): includes tests para el retry de infra (intento + éxito, agotamiento), separación behaviour vs infra errors, wiring de EVAL_TOOLS y temperature.
- [x] **`.github/workflows/evals.yml`**: `AGENT_TIMEOUT_S: 300`, `AGENT_MAX_RETRIES: 1`. Umbrales leídos del JSON report. Deuda CI anotada en comentario.
- [x] **Fixes del code-review**: `parents[3]`, fixture faltante lanza error antes de primer API call, thresholds en JSON, cost gate `>=`, descriptions de EVAL_TOOLS escritas.
- [x] **Verificación gate bloquea**: PR #10 (`test/eval-gate-blocks`) con threshold=1.01 → eval-gate falló (exit 1, run 26808493987) → merge bloqueado. PR descartada.
- [x] **Gate verde en PR #9**: run 26807268026 SUCCESS, 13/13, tool_use_accuracy 100%, mean_cost $0.044.
- [x] **`specs/04-guardrails.md`**: incidente FP-001 registrado (clasificador Haiku bloqueando comparaciones precio/52-semanas en dossiers válidos).
- [x] **Suite**: **107 passed** (82 existentes + 25 del eval runner).

## Subagentes usados en esta sesión

- **`gold-annotator` × 2** (lotes A y B, en paralelo): anotaron las 13 entradas del set. Borrador JSONL producido por los subagentes; firmado humano antes de integrar.

## Blockers

- **Guardrail Haiku demasiado agresivo**: clasificador L3 bloqueó dossiers válidos (AAPL, MSFT, NVDA, TSLA, BRK-B) en corridas de eval porque el modelo computó comparaciones precio/52-semanas desde los market data fixtures. Resuelto bypassando el clasificador en eval mode. Incidente documentado en `specs/04-guardrails.md` como FP-001.
- **`APITimeoutError` en CI**: web_search como server tool bloqueaba la respuesta HTTP >120s. Resuelto sustituyendo server tools por client tools con fixtures (EVAL_TOOLS) + timeout 300s + max_retries=1 + retry por entrada.

## Decisiones tomadas en esta sesión

- **Server tools como client tools en eval**: web_search y web_fetch se reemplazan por client tools homónimas en eval mode (mismo `name`, sin `type`, con `input_schema`). El modelo genera el mismo `tool_use` block; el runner sirve fixtures. Único mecanismo que permite interceptar y fixturizar server tools sin mockear la respuesta HTTP completa.
- **Bypass del guardrail L3 en eval**: el gate mide comportamiento del agente (tool selection, dossier quality); el guardrail tiene su propia test suite. Incluyéndolo en el gate se introduce non-determinismo del clasificador Haiku. Mismo patrón que `conftest.py` autouse en tests unitarios.
- **Retry de infra separado de fallo de comportamiento**: `APITimeoutError`/`APIConnectionError` → `runner_infra_error` (retriable, transient); otros errores → `runner_error` (no retriable, indicates a bug). El log distingue claramente el origen.
- **`TASK_COMPLETION_THRESHOLD = 0.92`**: con 13 entradas, pasa si ≥12/13 completan (12/13 = 0.923 > 0.92); falla si ≤11/13 (11/13 = 0.846 < 0.92). Tolera exactamente 1 entry fallida sin bloquear el merge.

## Coste de la sesión

- ~$4–5 USD total estimado: 3 corridas locales completas (~$1.4), 4 corridas CI completas en PR #9 (~$2.3), 1 corrida CI de prueba en PR #10 (~$0.6). Los tests del runner mockean el loop; el gasto es de corridas reales del agente en CI y local para calibrar.

## Notas de handoff

- El gate eval-gate ya está verde en PR #9. La siguiente acción es humana: merge (squash) + tag `08-block-H`.
- El workflow en CI tarda ~7-8 min para 13 entradas. Cost por corrida CI: ~$0.55-0.60.
- EVAL_TOOLS y los fixtures de web_search/web_fetch son la pieza nueva clave. Si se añade una entry al gold set: crear los 3 fixtures correspondientes o el preflight lanzará `FileNotFoundError` antes de gastar tokens.
- El incidente FP-001 del guardrail está en `specs/04-guardrails.md`. Para producción: afinar el prompt del clasificador para no bloquear comparaciones de datos de mercado descriptivos.

## Comandos útiles ahora

```bash
cd backend

# Correr el gate en local (necesita ANTHROPIC_API_KEY en .env)
uv run python -m app.evals.runner --max-turns 8

# Solo tests del runner (sin API)
uv run pytest tests/evals/test_eval_runner.py -v

# Suite completa (sin API)
uv run pytest -q
```

## Gate de revisión

- **Criterio:** 107 tests verdes; gate eval-gate pasa en CI con 13/13 entradas; gate bloquea confirmado con PR #10; guardrail FP-001 documentado. Gate de este bloque: **code-review en PR #9**.
- **Resultado:** eval-gate run 26807268026 SUCCESS (13/13, task_completion 100%, tool_use_accuracy 100%, mean_cost $0.044). Gate bloquea confirmado (run 26808493987 FAILURE con threshold=1.01).
