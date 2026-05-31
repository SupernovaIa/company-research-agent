# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado según [SemVer](https://semver.org/lang/es/).

## [No publicado]

Próximas entradas por sesión.

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
