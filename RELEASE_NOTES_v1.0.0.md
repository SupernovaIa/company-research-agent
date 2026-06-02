# Release Notes — v1.0.0 (2026-06-02)

## ¿Qué es esto?

**company-research-agent** es un agente de research financiero con tool use construido
sobre Claude Sonnet 4.6 y el Anthropic Python SDK. Dado el ticker de una empresa cotizada,
orquesta datos de mercado (yfinance), búsqueda web y profundización en fuentes dentro de
un loop controlado, y devuelve un dossier estructurado, citable y validado por Pydantic.

Es un caso práctico completo de un agente con tool use en producción: loop sobre el SDK
directo, guardrails en capas, output estructurado, serving con SSE, observabilidad con
Langfuse, y evaluación como gate de CI.

## Bloques incluidos

| Bloque | Contenido |
|---|---|
| **block-A** | Scaffold: FastAPI `/health`, uv, commitlint, .env.example |
| **block-B** | `CompanyDossier` Pydantic v2, JSON schema firmado, inventario de tools (13 ADRs) |
| **block-C** | Loop de tool use sobre el SDK, CLI de research, Langfuse base |
| **block-D** | `get_market_data` de producción (yfinance), retry de `submit_dossier`, output estructurado |
| **block-E** | Budget hard cut, timeout de cliente, retries Tenacity, rate limiting, endpoint `POST /research` |
| **block-F** | Defensa en capas (L1 delimitadores, L2 system prompt, L3 clasificador Haiku, L4 mínimo privilegio), harness red team (24 payloads) |
| **block-G** | SSE streaming, trazas Langfuse enriquecidas, `scripts/metrics.py` |
| **block-H** | Set de evaluación (13 entradas), fixtures (39 ficheros), eval runner, gate en GitHub Actions CI |

## Métricas de v1.0.0

Medidas en la corrida de release (2026-06-02):

- **Task completion rate**: 100% (13/13)
- **Tool use accuracy**: 100% (13/13)
- **Seguridad (block rate)**: 100% (24/24 payloads bloqueados)
- **Mean cost por ejecución**: $0.044
- **p95 cost por ejecución**: $0.055
- **Turnos típicos**: 2–4 (p95 = 4)
- **Suite de tests**: 107 passed

## Quickstart

```bash
git clone https://github.com/<org>/company-research-agent.git
cd company-research-agent
cp .env.example .env   # rellena ANTHROPIC_API_KEY
cd backend && uv sync
uv run python -m app.agent.run --ticker AAPL
```

Requisitos: uv 0.4+, Python 3.12 (gestionado por uv), Node.js ≥ 18 (hooks de commit),
`ANTHROPIC_API_KEY` activa.

## Preparar el zip para distribución

```bash
# Desde la raíz del repo, en el tag v1.0.0
git archive --format=zip --prefix=company-research-agent-v1.0.0/ v1.0.0 \
  -o company-research-agent-v1.0.0.zip

# Verificar el contenido
unzip -l company-research-agent-v1.0.0.zip | head -30
```

El zip excluye automáticamente los ficheros de `.gitignore` (incluyendo `.env` y el venv).

## Deudas conocidas (post-v1.0.0)

Estas tres deudas están documentadas y quedan pendientes como issues:

1. **Tests en CI**: `pytest` y `python -m app.redteam.run --ci` solo corren en local;
   pendiente añadir jobs `unit-tests` y `redteam` al workflow de PR.
2. **Clasificador Haiku**: el prompt del guardrail L3 bloquea comparaciones
   precio/52-semanas (incidente FP-001 en `specs/04-guardrails.md`); necesita afinado para
   distinguir datos descriptivos de recomendaciones de inversión.
3. **Job nocturno end-to-end**: el gate de CI usa fixtures; pendiente un job que corra el
   agente contra URLs reales para detectar regresiones de comportamiento en producción.

## Acciones humanas para cerrar la release

```bash
# 1. Revisar y aprobar la PR chore/release-v1
# 2. Merge squash a main
# 3. Crear el tag
git tag -s v1.0.0 -m "chore(release): v1.0.0"
git push origin v1.0.0

# 4. Crear la GitHub Release con estas notas
# 5. Generar y adjuntar el zip
git archive --format=zip --prefix=company-research-agent-v1.0.0/ v1.0.0 \
  -o company-research-agent-v1.0.0.zip
```
