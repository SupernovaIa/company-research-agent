# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado según [SemVer](https://semver.org/lang/es/).

## [No publicado]

Próximas entradas por sesión.

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
