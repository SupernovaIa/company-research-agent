# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado según [SemVer](https://semver.org/lang/es/).

## [No publicado]

---

## [1.0.1] - 2026-06-04

### Corregido

- **Costes inflados en Langfuse** (`backend/app/observability/tracer.py`,
  `backend/app/agent/loop.py`): causa raíz identificada y corregida en dos commits.

  **Causa raíz real** — dos bugs acumulados:

  1. Los tests de pytest que ejercen el límite de presupuesto usan
     `_FakeUsage(input_tokens=10_000_000, output_tokens=10_000_000)` para forzar
     un coste artificialmente alto. El `Tracer` es un singleton inicializado con
     las credenciales reales del `.env`. Al no estar aislado durante los tests,
     enviaba spans reales a Langfuse Cloud con 10 M tokens de usage falso. El
     servidor de Langfuse aplicaba sus precios correctos ($3/M, $15/M) y
     almacenaba `costDetails = {input: $30, output: $150}` → **$180 por cada run
     de pytest**. Cada ejecución de CI o `pytest tests/` generaba dos trazas de
     $180 en el dashboard.

  2. La instrumentación del tracer real tenía además tres errores menores que
     habrían inflado futuros runs de producción: incluía la clave `"total"` en
     `usage_details` (campo derivado, no dimensión), pasaba
     `cost_details={"total": cost_usd}` en lugar de un desglose por dimensión
     (dejando "input" y "output" expuestos al model pricing de Langfuse), y no
     incluía el coste de tokens de caché en `_estimate_cost`.

- **Aislamiento del tracer en tests** (`backend/tests/conftest.py`): fixture
  `autouse` `_null_tracer` que blanquea las credenciales de Langfuse y llama a
  `reset_tracer()` antes y después de cada test. Los tests ahora son herméticos
  respecto a Langfuse Cloud.

- **`_estimate_cost`** (`backend/app/agent/loop.py`): ahora incluye los tokens de
  caché en el cálculo (cache_creation a $3.75/M, cache_read a $0.30/M) y devuelve
  `(total, breakdown)` con desglose por dimensión para pasarlo a Langfuse.

- **`record_turn`** (`backend/app/observability/tracer.py`): `cost_details` con
  desglose completo por dimensión incluyendo la clave `total`; `model` restaurado
  en `start_observation` para poblar el panel "Cost by model" del dashboard.

- **`totalCost = 0` en el dashboard** (`backend/app/observability/tracer.py`,
  `backend/app/agent/loop.py`): `calculatedTotalCost` de cada generation se
  puebla desde `costDetails.total`. Sin esa clave, Langfuse deja
  `calculatedTotalCost = 0` aunque `calculatedInputCost` y
  `calculatedOutputCost` estén correctos, y el `totalCost` de la traza queda
  a cero. Añadir `total = sum(breakdown.values())` al breakdown y restaurar
  `model` en `start_observation` resuelve tanto `totalCost` como "Cost by model".

### Verificaciones

- **pytest**: 83 passed (sin API, ~33 s).
- **research end-to-end** (AAPL, `AGENT_TIMEOUT_S=180`): 2 turnos, $0.2199.
- **`totalCost` Langfuse** (traza `05fffbf2`, leído de `/api/public/traces`):
  `0.2199` — coincide con `run.cost_usd`.
- **`calculatedTotalCost`** por turno (leído de `/api/public/observations`):
  `0.0312 + 0.1886 = 0.2198` — sum = `totalCost` ✅
- **`model = "claude-sonnet-4-6"`** presente en observations — "Cost by model"
  poblado en el dashboard ✅
- **Trazas nuevas durante pytest**: **0** (tracer aislado).

---

## [1.0.0] - 2026-06-02

Primera release estable. Incluye todos los bloques A–H implementados y verificados.

### Añadido

- **README operativo final**: quickstart desde clone limpio, métricas alcanzadas (v1.0.0),
  tabla de estructura del repo, listado de deudas conocidas post-v1.0.0.
- **`.env.example` corregido**: `AGENT_TIMEOUT_S` cambiado de 30 s (insuficiente para
  web_search en ejecuciones reales) a 180 s, con comentario explicativo.
- **`docs/adr/ADR-007-loop-limits.md`**: estado actualizado con datos reales de calibración
  del eval set (p95 turnos=4, mean_cost=$0.043 con 13 entradas).
- **`specs/06-serving-metrics.md`**: estado actualizado a "aceptada" con nota de deuda
  post-v1.0.0 (desglose de coste por tool en `scripts/metrics.py`).

### Verificaciones de release

- **pytest**: 107 passed (sin API, ~28 s).
- **eval set** (13 entradas): task_completion 100%, tool_use_accuracy 100%, mean_cost
  $0.044. Gate PASS.
- **redteam gate**: 24/24 payloads bloqueados (100% block rate, umbral 90%). Exit 0.
- **research end-to-end** (AAPL): 2 turnos, $0.069, dossier Pydantic validado.
- **security review**: cero secretos en historial git ni en ficheros tracked.

### Deudas conocidas (post-v1.0.0, pendientes como issues)

1. Suite de tests y redteam no corren en CI (solo en local).
2. Prompt del clasificador Haiku necesita afinado (incidente FP-001).
3. Job nocturno end-to-end sin fixtures.

---

## [block-H] - 2026-06-01 / 2026-06-02

### Añadido

- **`evals/gold.jsonl`** (13 entradas firmadas): set de comportamiento anotado con dos invocaciones paralelas del subagente `gold-annotator` (lotes A y B); firmado humano. Cobertura: 6 cotizadas USA large-cap, 1 USA mid-cap, 1 europea completa (ASML.AS), 2 europeas con datos parciales (SAP.DE, MC.PA), 1 ticker japonés con datos parciales (7203.T), 2 tickers inexistentes. Cada entrada: `expected_tool_calls`, `optional_tool_calls`, `task_completion_expected`, `dossier_checks`, `category`, `annotation_notes`.
- **`evals/fixtures/`** (39 ficheros): market data (13), web_search (13 con ≥4 resultados y noticias fechadas), web_fetch (13 con hechos y fechas explícitas para poblar key_facts y recent_news con holgura). Tickers inexistentes con fixture de error y resultados vacíos.
- **`backend/app/tools/inventory.py`** — `EVAL_TOOLS`: versiones client-tool de `web_search` y `web_fetch` (mismo `name`, sin `type`, con `input_schema` y `description` escrita para el modelo). `code_execution` omitido en eval (nunca en `expected_tool_calls`). Comentario explicando el mecanismo y la diferencia vs server tools.
- **`backend/app/agent/loop.py`** — parámetros `tools: list[dict] | None = None` y `temperature: float | None = None` en `run()`. No-breaking: todos los callers existentes obtienen comportamiento por defecto. `_build_tools_with_cache` acepta una lista de tools opcional.
- **`backend/app/evals/runner.py`**: eval mode completo.
  - Dispatch extendido: market data, web_search, web_fetch sirven fixtures; `submit_dossier` corre en vivo (Pydantic validation).
  - Guardrail L3 (Haiku) bypaseado en eval: el gate mide comportamiento del agente, no el clasificador. Patrón idéntico al `conftest.py` autouse de tests unitarios.
  - Retry de infra: `APITimeoutError`/`APIConnectionError` → hasta 2 reintentos antes de marcar `runner_infra_error`. Otros errores → `runner_error` (fallo de comportamiento, sin retry). El log distingue claramente el origen.
  - Preflight ruidoso para los tres tipos de fixture (market data, web_search, web_fetch): lanza `FileNotFoundError` antes de gastar tokens.
  - `EVAL_TEMPERATURE = 0.0` para reducir varianza entre corridas.
  - `TASK_COMPLETION_THRESHOLD = 0.92` (≡ ≥12/13 con 13 entradas); `TOOL_ACCURACY_THRESHOLD = 0.80`.
  - `EvalReport` incluye `thresholds` y booleans por métrica para que el JS del workflow no hardcodee umbrales.
  - CLI: `--ci`, `--json`, `--max-turns`.
- **`backend/tests/evals/test_eval_runner.py`** (25 tests): cubre preflight de 3 tipos de fixture, wiring de EVAL_TOOLS y temperature, retry de infra (éxito en retry, agotamiento de retries, separación infra/behaviour), gate pass/fail, path resolution.
- **`.github/workflows/evals.yml`**: `AGENT_TIMEOUT_S: 300`, `AGENT_MAX_RETRIES: 1`. Umbrales leídos del JSON report (no hardcodeados en JS). Deuda CI anotada en comentario (suite tests + redteam no corren en CI aún).

### Cambiado

- **`backend/app/config.py`**: `agent_max_retries: int = 2` (nuevo campo, default SDK; CI lo sobreescribe a 1 via `AGENT_MAX_RETRIES`).
- **`specs/04-guardrails.md`**: incidente FP-001 registrado — clasificador Haiku bloqueando comparaciones precio/52-semanas en dossiers válidos.
- **`specs/07-evals-ci-gate.md`**: nota de divergencia eval mode vs producción; estado actualizado.
- **`specs/08-gold-dataset.md`**: estado `pre-construida` → `aceptada`.

### Decisiones documentadas

- **Server tools como client tools en eval**: web_search y web_fetch se reemplazan en eval por client tools homónimas. El modelo genera el mismo `tool_use` block; el runner sirve fixtures. Único mecanismo que intercepta server tools sin mockear la respuesta HTTP completa.
- **Bypass guardrail L3 en eval**: el gate mide tool selection y dossier quality; el guardrail tiene su propia redteam suite. Incluyéndolo se introduce non-determinismo del clasificador Haiku.
- **Retry de infra por entrada**: distingue fallos transitorios (timeout, red) de fallos de comportamiento. Evita que una racha de timeouts infle artificialmente el tase de fallos del gate.
- **`TASK_COMPLETION_THRESHOLD = 0.92`**: con 13 entradas, pasa si ≥12/13 completan; falla si ≤11. Calibrado contra corrida 13/13 confirmada.

### Verificaciones en vivo

- Gate verde: run CI `26807268026`, 13/13, task_completion 100%, tool_use_accuracy 100%, mean_cost $0.044.
- Gate bloquea: PR #10 (`test/eval-gate-blocks`, threshold=1.01), run CI `26808493987` FAILURE (exit 1). PR descartada.

### Notas

- Suite completa: **107 passed** (82 existentes + 25 del eval runner). Coste sesión: ~$4–5 USD (3 corridas locales + ~4 corridas CI incluyendo la PR de prueba).
- El workflow `eval-gate` requiere el secret `ANTHROPIC_API_KEY`. Sin él el job falla antes de correr entradas.

---

## [block-G] - 2026-06-01

### Añadido

- **SSE streaming en `/research`** (`backend/app/serving/main.py`): el endpoint `POST /research` se convierte a `StreamingResponse` con `media_type="text/event-stream"`. Emite un evento `turn` por turno del loop (stop_reason, tool names) y un evento final `done` (dossier completo) o `error` (terminated_by, cost, turns). El loop síncrono corre en `asyncio.to_thread`; los eventos se publican al event loop vía `asyncio.Queue` + `call_soon_threadsafe`.
- **Trazas Langfuse enriquecidas** (`observability/tracer.py`, `agent/loop.py`): el loop acumula `total_tool_calls` y `total_tool_errors` por ejecución (error = `"error" in result.json_response`). `run_trace.finish()` los incluye en el campo `output` de la traza junto con `terminated_by`, `total_cost_usd` y `total_turns`. Disponibles inmediatamente en Langfuse para el script de métricas.
- **`scripts/metrics.py`** (nuevo, solo stdlib): consulta la Langfuse REST API y calcula las seis métricas de agente definidas en Spec 06: (1) task completion rate con desglose por `terminated_by`; (2) tool error rate (errores / total tool calls); (3) latencia p50/p95/p99; (4) coste mean/p50/p95; (5) turnos mean/p50/p95; (6) nota sobre tool_use_accuracy (requiere set de eval). Alerta si p95 de coste o turnos supera el 80% del cap configurado. Uso: `cd backend && uv run python ../scripts/metrics.py [--days N] [--limit N]`.

### Cambiado

- **`tests/test_guardrails.py`**: `test_research_endpoint_exists` actualizado para verificar respuesta SSE (`200 text/event-stream`, evento `error` en el stream) en lugar de la antigua respuesta JSON 5xx.
- **`specs/06-serving-metrics.md`**: estado `pre-construida` → `aceptada parcialmente` (SSE ✓, trazas ✓, 5 métricas ✓; tool_use_accuracy y desglose de coste por tool pendientes de block-H).

### Notas

- Verificación en vivo: `AGENT_TIMEOUT_S=180 uv run python -m app.agent.run --ticker MSFT` → `terminated_by=submit_dossier`, 2 turnos, $0.074. Traza en Langfuse con `tool_calls=2, tool_errors=0`.
- `scripts/metrics.py` sobre 100 trazas (últimos 90 días): 33% completion rate, 5.1% tool error rate, latencia p50=0.5s/p95=14.8s, turnos p50=2/p95=20.
- Suite: **82 passed** (`--ignore=tests/evals`).
- Coste: ~$0.074 USD (una corrida real de verificación sobre MSFT).

---

## [block-F] - 2026-05-31

### Añadido

- **Defensa en capas frente a indirect prompt injection** (Spec 04, Spec 09, ADR-013):
  - **L1 · Delimitadores** (`backend/app/guardrails/injection.py`): `wrap_external_content` envuelve el contenido de tools en `<<UNTRUSTED_TOOL_CONTENT>> … <<END_UNTRUSTED_TOOL_CONTENT>>` y sanitiza la falsificación de la frontera y de turnos. Cableado en `agent/loop.py`.
  - **L2 · System prompt** (`prompts/system_prompt_v1.md`): sección "Untrusted tool content (security)" que marca el contenido externo como datos y prohíbe obedecer órdenes embebidas, filtrar el prompt, cambiar de tarea o emitir veredictos.
  - **L3 · Clasificador de output** (`backend/app/guardrails/classifier.py`): pre-filtro determinista (`heuristic_scan`) + backstop semántico con **Haiku 4.5** (`GUARDRAIL_MODEL`), cliente dedicado con `classifier_timeout_s`. El loop descarta el dossier inseguro (`terminated_by="guardrail_blocked"`). Degrada sin API key (modo solo-heurístico) y ante error del clasificador.
  - **L4 · Mínimo privilegio**: inventario read-only y `capability_is_available` (ADR-006, ADR-009, ADR-011).
- **Harness de red team** (`backend/app/redteam/`): `payloads.py` (24 payloads, fuente de verdad), `runner.py` (`THRESHOLD=0.90`, reporte PASS/FAIL y cobertura por capa), `run.py` (`python -m app.redteam.run [--ci|--json]`, exit 1 si < umbral).
- **Checklist de red team** (`security/red-team-checklist.md`): 24 payloads con OWASP LLM Top 10 (LLM01/02/05/06/09), categoría, vector, capa esperada y resultado. Sincronía con `payloads.py` verificada por test.
- **Slash command `/redteam`**: cableado al runner determinista (gate canónico) y al modo live, delegando en el subagente `redteam-runner`.
- **Observabilidad** (`observability/tracer.py`): `record_guardrail` añade el span `output_guardrail` (capa, allowed, reason) a la traza.
- **`terminated_by="guardrail_blocked"`**: nuevo estado en `LoopResult` y en el mapa de mensajes de `run.py`.
- **`classifier_timeout_s=15`** en `config.py`.
- **Tests** (84 total, todos verdes): `test_injection.py`, `test_classifier.py`, `test_redteam.py` y `conftest.py` (fixture autouse que neutraliza la llamada Haiku en los tests del loop).

### Cambiado

- **`specs/09-security-redteam.md`**: `pre-construida` → `aceptada` (implementada en block-F).
- **`specs/04-guardrails.md`**: `aceptada parcialmente` → `aceptada` (capa de inyección y clasificador de output implementados).

### Decisiones documentadas

- **ADR-013**: defensa en capas frente a indirect prompt injection y red team; gate determinista/offline como canónico, backstop semántico Haiku en modo live con evidencia en Langfuse; mapeo OWASP LLM Top 10.

### Notas

- Verificación en vivo: `python -m app.redteam.run` → **24/24 PASS, bloqueo 100.0%** (umbral 90%), cada capa bloquea su payload (`{L1:6, L2:5, L3:7, L4:6}`).
- Suite completa: 84 passed (`--ignore=tests/evals`).
- Coste: ~$0 USD; el gate canónico es determinista (sin llamadas al modelo).

---

## [block-E] - 2026-05-31

### Añadido

- **Presupuesto por ejecución con corte duro** (`backend/app/agent/loop.py`): el loop comprueba `total_cost >= settings.agent_budget_usd` tras cada turno. Al superarlo para con `terminated_by="budget_exceeded"`. Default ajustado de 1.0 a 0.50 USD (rango ADR-007: 0.30–0.80).
- **Timeout del cliente del modelo** (`loop.py`): `anthropic.Anthropic(timeout=settings.agent_timeout_s)`. El timeout per-request se pasa al constructor desde settings; el agente y el clasificador de output (block-F) usarán clientes separados con perfiles distintos.
- **Tenacity en `get_market_data`** (`backend/app/tools/client.py`): `@retry` con `retry_if_exception_type((ConnectionError, OSError, socket.timeout))`, 3 intentos, backoff exponencial (1 s / 2 s / 4 s). `RetryError` tras agotar intentos → error recuperable devuelto al modelo sin romper el loop. No reintenta `ValueError` (ticker inválido) ni errores 4xx.
- **Validación Pydantic del output de `get_market_data`** (`client.py`): `_MarketDataOutput` valida el dict construido antes de retornarlo al loop. Fallo de validación → error recuperable, no inyección silenciosa de datos corruptos al contexto.
- **Rate limiting en serving** (`backend/app/serving/main.py`): middleware `slowapi` con `Limiter(key_func=get_remote_address)`. El límite se lee de `settings.rate_limit_per_minute`. Upgrade a Redis (Upstash) documentado en Spec 04.
- **Endpoint `POST /research`** (`serving/main.py`): acepta `{"ticker": "AAPL"}`, aplica rate limiting, llama a `run()`, devuelve el dossier JSON o un error estructurado con `terminated_by`. SSE en block-F.
- **`terminated_by="budget_exceeded"`**: nuevo estado en `LoopResult` y en el mapa de mensajes de `run.py`.
- **Dependencias**: `tenacity>=8.2`, `slowapi>=0.1` añadidas a `pyproject.toml`.
- **Tests block-E** — 12 nuevos casos (62 total, todos verdes):
  - `test_loop.py`: budget cortado, budget respetado, timeout kwarg pasado al constructor Anthropic, output validation de `_MarketDataOutput`.
  - `test_guardrails.py` (nuevo): endpoint `/research` accesible, 422 para ticker vacío/ausente, limiter cableado a `app.state`, 429 ante `RateLimitExceeded`, Tenacity con 2 fallos + éxito en 3.er intento, retries agotados → error recuperable, CLI mapea `budget_exceeded` a mensaje de usuario.

### Cambiado

- **`agent_budget_usd` default** (`config.py`): `1.0` → `0.50` USD (rango ADR-007).
- **`specs/04-guardrails.md`**: estado `pre-construida` → `aceptada parcialmente` (guardrails operativos de block-E implementados; indirect prompt injection y clasificador Haiku pendientes de block-F).
- **`CLAUDE.md` y `.claude/commands/close-session.md`**: incoherencia corregida — skill de cierre actualizada de `review` a `code-review` (la skill multi-agente real usada en el gate de PR).

### Decisiones documentadas

- Tenacity solo para errores de red transitorios: no reintentar `ValueError` ni errores 4xx (input mal formado, ticker inválido).
- Rate limiting in-memory para block-E; Upstash Redis como upgrade de producción documentado en Spec 04.
- `_MarketDataOutput` distinto de `MarketData` del dossier: permite `currency: str | None` para tickers europeos y no impone las restricciones de citación del dossier final.

### Notas

- Verificación en vivo: `AGENT_BUDGET_USD=0.0001 uv run python -m app.agent.run --ticker AAPL` → `terminated_by=budget_exceeded`, turno 1, $0.0039 USD.
- Suite completa: 62 passed (12 nuevos + 50 de bloques anteriores).
- Coste de la sesión: ~$0.004 USD (1 corrida real con budget de prueba sobre AAPL).

---

## [block-D] - 2026-05-31

### Añadido

- **`get_market_data` de producción** (`backend/app/tools/client.py`): implementación completa vía `yf.Ticker(ticker).info`. Devuelve todos los campos de `MarketData`: `price`, `currency`, `change_pct`, `market_cap`, `pe_ratio`, `forward_pe`, `eps`, `dividend_yield`, `week52_high`, `week52_low`, `as_of`, `source`. Campos sin dato → `null`. Timeout de 10 s con `ThreadPoolExecutor.future.result(timeout=...)` que devuelve error recuperable en lugar de colgar el loop. Ticker vacío → error no recuperable.
- **Retry limitado de `submit_dossier`** (ADR-006): el loop rastrea `submit_attempts`; si `submit_dossier` falla una segunda vez se corta con `terminated_by="submit_dossier_failed"`. Un primer fallo devuelve el error de validación al modelo como `tool_result` para que lo corrija (un reintento, no indefinidos).
- **Inyección de metadatos reales en `run`**: el loop sobreescribe `run.model`, `run.cost_usd` y `run.turns` con los valores reales de la ejecución tras una validación exitosa. El modelo se auto-reportaba con valores inventados.
- **Estado `submit_dossier_failed`** en `LoopResult.terminated_by`: distingue cierre con dossier válido de cierre por fallo persistente de validación.
- **`_to_float` helper**: coerción null-safe de valores de yfinance (algunos campos llegan como `None` o tipos no numéricos).
- **Tests de block-D** (`backend/tests/test_loop.py`): 12 nuevos casos — todos los campos de `MarketData` con mock, ticker inválido → error recuperable, ticker vacío → no recuperable, campos `null` en ticker europeo, doble fallo `submit_dossier` → `submit_dossier_failed`, inyección de `run.model/cost_usd/turns`, timeout simulado con `FuturesTimeoutError`.

### Cambiado

- **`_get_market_data`**: migrado de `Ticker.fast_info` (solo precio básico) a `Ticker.info` (dict completo) para cubrir todos los campos del contrato `MarketData`.
- **`source`** en market data: `"Yahoo Finance"` (nombre del proveedor real) en lugar de `"yfinance"` (nombre de la librería).
- **`specs/05-structured-output.md`**: estado actualizado de `pre-construida` a `aceptada (implementada en block-D 2026-05-31)`.
- **Tests de block-C actualizados**: `test_get_market_data_as_of_is_iso_datetime` reescrito para mockear `Ticker.info` como dict (en lugar de `fast_info` como objeto).

### Decisiones documentadas

- Inyección de `run.cost_usd` y `run.turns` además de `run.model`: los tres campos del `RunMeta` son metadatos de la ejecución que el loop conoce con precisión y el modelo no.
- `source = "Yahoo Finance"`: el label visible en el dossier es el proveedor de datos, no la librería cliente.
- Un solo reintento de `submit_dossier` (ADR-006): mantiene el tope de turnos y el presupuesto sin permitir bucles infinitos de corrección.

### Notas

- Corrida real AAPL: 2 turnos, $0.0663 USD, `terminated_by=submit_dossier`. Todos los campos de `MarketData` poblados (price=312.06, currency=USD, change_pct=-0.14, market_cap=4.58T, pe_ratio=37.73, forward_pe=32.48, eps=8.27, dividend_yield=0.35, week52_high=315.0, week52_low=195.07).
- Suite completa: 48 passed (12 nuevos + 36 de bloques anteriores).
- Coste de la sesión: ~$0.07 USD (1 corrida real sobre AAPL).

---

## [block-C] - 2026-05-31

### Añadido

- **Loop de tool use** (`backend/app/agent/loop.py`): implementación a mano sobre el SDK de Anthropic (ADR-010). Ciclo `messages.create → stop_reason → tool_result`, tope blando (`HARD-5`) y duro (`AGENT_MAX_TURNS`, default 20) leídos de settings, tool calls paralelas con `ThreadPoolExecutor`. Helper `_extract_client_tool_uses` itera por `block.type` y maneja `text`, `tool_use`, `server_tool_use` y `thinking` sin asumir `content[0]`. Cache de system prompt y tools con `cache_control: ephemeral` en el último bloque estable.
- **CLI de research** (`backend/app/agent/run.py`): `python -m app.agent.run --ticker <TICKER> [-v]`. Callback `on_turn` por turno para futura integración SSE en serving.
- **Dispatch de client tools** (`backend/app/tools/client.py`): `dispatch_client_tool` enruta `get_market_data` y `submit_dossier`. Stubs funcionales: `get_market_data` con thin wrapper yfinance (block-D añade error handling y retries), `submit_dossier` con validación Pydantic mínima (block-D añade guardrail classifier y retry ADR-006).
- **Config module** (`backend/app/config.py`): pydantic-settings carga el `.env` de la raíz del repo de forma resoluble desde cualquier CWD; `loop.py` y `tracer.py` consumen `settings` en lugar de `os.environ.get` directamente.
- **Tracer Langfuse** (`backend/app/observability/tracer.py`): null-safe, reescrito para la API de Langfuse v4 (`start_observation` / `start_as_current_observation` sobre OTel). Una traza por ejecución, un span de generación por turno con `usage_details` y `cost_details`. Usa `base_url` (v4); fallback a `langfuse_host` (legacy).
- **System prompt** (`prompts/system_prompt_v1.md`): externalizado de `inventory.py` (criterio de aceptación de Spec 02). Escrito para el modelo en inglés, versionado.
- **Tests del loop** (`backend/tests/test_loop.py`): 16 casos con SDK mockeado cubriendo `end_turn`, `tool_use → end_turn`, `submit_dossier` válido, `submit_dossier` inválido (reintento), tope duro, inyección de mensaje de tope blando, paralelo de dos tool calls, bloque `thinking`, callback `on_turn`, y bloques `server_tool_use` ignorados.
- Dependencias añadidas al proyecto: `anthropic>=0.49`, `langfuse>=2.0`, `yfinance>=0.2`.

### Cambiado

- `backend/app/tools/inventory.py`: `GUARDRAIL_MODEL` pineado a `claude-haiku-4-5-20251001` (snapshot con fecha disponible en el SDK). Comentario de `AGENT_MODEL` actualizado: `claude-sonnet-4-6` es el alias estable actual; Anthropic no ha publicado snapshot con fecha para Sonnet 4.6 todavía.
- `docs/adr/ADR-007-loop-limits.md`: estado actualizado a "topes provisionales implementados en block-C; recalibración definitiva en block-E". Nota añadida sobre la incoherencia entre Spec 03 (topes en block-C) y ADR-007 (en block-E) y su resolución: block-C añade los topes provisionales configurables desde el `.env`; block-E recalibra los números con datos del eval set.
- `backend/app/agent/__init__.py` y `backend/app/observability/__init__.py`: exportan los símbolos públicos del módulo.

### Decisiones documentadas

- Stubs de client tools en block-C: implementaciones mínimas funcionales para correr el loop end-to-end. Producción (error handling, retries, guardrail) en block-D.
- Langfuse v4: API de `start_observation` sobre OTel; `base_url` preferido. Incompatible con v2/v3 (`.trace()` eliminado).
- `AGENT_MODEL` sin fecha: `claude-sonnet-4-6` es el ID correcto a fecha de block-C; pinear snapshot con fecha cuando Anthropic la publique.

### Notas

- Corrida real SHOP: 2 turnos, ~$0.08–0.10 USD por ejecución con Sonnet 4.6, `terminated_by=submit_dossier`, dossier Pydantic validado en vivo.
- Cache hit confirmado en el 3er run: `cache_read=7.303 tok` (turn 1) y `cache_read=275.997 tok` (turn 2); `cache_creation=0` en los runs posteriores al primero.
- 3 trazas visibles en Langfuse Cloud con spans anidados por turno.
- Suite completa: 36 passed (16 nuevos del loop + 20 previos de schema e inventario).
- Coste de la sesión: ~$0.30 USD en 3 corridas reales.

---

## [block-B] - 2026-05-31

### Añadido
- Modelo Pydantic v2 `CompanyDossier` con sus sub-schemas (`Company`, `MarketData`, `Fact`, `NewsItem`, `Source`, `RunMeta`) en `backend/app/dossier/models.py`. Validación cruzada: cada `source_id` citado resuelve a un `Source` listado (ids únicos); cada `Fact` lleva exactamente uno de `source_id` (web) o `basis` (cálculo); la procedencia de un `Fact` `computed` que referencie `market_data.<campo>` exige que ese campo exista y no sea `null`. `schema_version` validado como semver.
- JSON schema firmado del dossier en `backend/app/dossier/dossier.schema.json`, generado del modelo (artefacto versionado) con test anti-drift que lo mantiene sincronizado.
- Inventario `TOOLS` declarado en `backend/app/tools/inventory.py` (sin lógica): client tools `get_market_data` y `submit_dossier` (con el schema del dossier como `input_schema`, ADR-006) y server tools ancladas por tipo y versión (`web_search_20260209`, `web_fetch_20260209`, `code_execution_20260120`).
- Tests de schema (`tests/test_dossier_schema.py`) e inventario (`tests/test_tools_inventory.py`): 19 casos cubriendo los criterios de aceptación de la Spec 01 y el contrato de la Spec 02. Suite completa: 20 passed.

### Cambiado
- Specs 01 (schema), 02 (tools) y 03 (loop) y los 12 ADR pasan a estado **aceptado** (firmados en block-B, 2026-05-31); la implementación del loop (Spec 03) es block-C. `DECISIONS.md` actualizado.
- Corrección de coherencia en el C4 de contenedores (`docs/architecture/02-containers.md`): la sección *Dossier validator* afirmaba que cada `Fact` lleva `source_id`; ahora refleja que un `Fact` derivado de un cálculo lleva `basis` en su lugar (alineado con la Spec 01). Se añade `RunMeta` a los sub-schemas listados.

### Decisiones documentadas
- Specs 01, 02 y 03: aceptadas.
- ADR-001 a ADR-012: aceptados (firma de diseño de block-B).

### Notas
- Verificación en vivo: `model_validate` de un dossier de cotizada USA (AAPL, market data completo + `Fact` `computed`) y otro europeo (SAP.DE, `forward_pe` y `dividend_yield` en `null`); `submit_dossier.input_schema == dossier_json_schema()` confirmado.
- Decisión de diseño firmada con el humano: las invariantes de citación y procedencia viven en el validador Pydantic, no en el JSON Schema plano; el SDK valida la forma y `CompanyDossier.model_validate` (con el reintento de ADR-006) garantiza las reglas tras `submit_dossier`.
- No hay CI workflows ni linter configurados todavía (`.github/workflows/` solo con `.gitkeep`); el único check local disponible es pytest, que pasa.
- 0 USD de coste: no se ejecutó el agente, solo diseño del contrato y validación con Pydantic.

---

## [block-A] - 2026-05-31

### Añadido
- Scaffold de la estructura del repo: `backend/app/{agent,tools,guardrails,dossier,serving,evals,observability}/`, `backend/tests/`, `prompts/`, `scripts/`, `security/`, `evals/`, `.github/workflows/`.
- Backend como proyecto uv (Python 3.12, fijado en `backend/.python-version`) con FastAPI. Endpoint `GET /health` → 200, con test de humo y `uv.lock` committeado.
- `.env.example` con `ANTHROPIC_API_KEY`, las claves de Langfuse (nota de región EU/US) y los topes del agente (`AGENT_MAX_TURNS`, `AGENT_BUDGET_USD`, `AGENT_TIMEOUT_S`, `RATE_LIMIT_PER_MINUTE`). Sin keys de proveedores de datos.
- commitlint + husky (hook `commit-msg`) sobre el `commitlint.config.js` existente, vía `package.json` en la raíz.
- README con quickstart y aviso de coste.
- Branch protection en `main` (require PR, sin force-push ni borrado; `enforce_admins=false` para permitir merge/tag del autor humano).

### Cambiado
- `.gitignore` ampliado (artefactos de Python, caches de test, directorios de editor).
- `SESSION.md` actualizado al estado de block-A.

### Decisiones documentadas
- Sin ADR nuevo. Stack y topes del agente alineados con ADR-001 y ADR-007 (valores de arranque provisionales del `.env.example`).

### Notas
- Verificación en vivo: `uv sync` + uvicorn + `curl /health` → 200, y commit malformado (`arreglos varios`) rechazado por commitlint.
- 0 USD de coste: no se ejecutó el agente, solo infraestructura.

---

## Plantilla por sesión

```markdown
## [block-X] - YYYY-MM-DD

### Añadido
- ...

### Cambiado
- ...

### Eliminado
- ...

### Decisiones documentadas
- ADR-XXX: <título>
- Spec: <nombre>

### Notas
- ...
```
