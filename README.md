# company-research-agent

Agente de research financiero con tool use. Dado el nombre o el ticker de una empresa
cotizada, orquesta datos de mercado, búsqueda web y profundización en fuentes dentro de
un loop controlado, y devuelve un dossier estructurado y citable a fecha de hoy.

El agente es **stateless por diseño**: una ejecución produce un dossier y termina.

> **Aviso de coste.** Cada ejecución del agente gasta API de pago (Anthropic). El
> presupuesto por ejecución es parte del diseño: hay un tope de turnos y un tope de coste
> (ver `AGENT_MAX_TURNS` / `AGENT_BUDGET_USD` y ADR-007). Una ejecución típica con
> Sonnet 4.6 y 2–4 turnos cuesta entre 0,04 y 0,10 dólares. Respeta el tope también en
> desarrollo.

## Stack

- Python 3.12 + FastAPI + Anthropic Python SDK.
- Modelo del agente: Claude Sonnet 4.6 (`web_search`, `web_fetch`, code execution
  server-side). Clasificador de guardrails: Claude Haiku 4.5.
- Validación con Pydantic v2. Observabilidad con Langfuse. CI en GitHub Actions con evals
  como gate. Package manager: uv.

Decisiones de diseño en `docs/adr/` (índice en `DECISIONS.md`) y arquitectura en
`docs/architecture/`.

## Quickstart desde cero

Requisitos: [uv](https://docs.astral.sh/uv/) 0.4+, Node.js ≥ 18 (hooks de commit) y
una `ANTHROPIC_API_KEY` activa (cuenta Anthropic con crédito de API).

```bash
# 1. Clonar el repositorio
git clone https://github.com/<org>/company-research-agent.git
cd company-research-agent

# 2. Variables de entorno
cp .env.example .env
# Abre .env y rellena al menos ANTHROPIC_API_KEY.
# Langfuse es opcional: sin él las trazas no se envían pero el agente funciona.

# 3. Instalar dependencias del backend (crea el venv con Python 3.12)
cd backend
uv sync

# 4. Hooks de commit (commitlint + husky) — desde la raíz del repo
cd ..
npm install

# 5. Verificar que el backend arranca
cd backend
uv run uvicorn app.serving.main:app --reload &
curl http://127.0.0.1:8000/health   # → {"status":"ok"}

# 6. Primera ejecución del agente (sobre Apple, ~2 turnos, ~$0.07)
uv run python -m app.agent.run --ticker AAPL
```

La salida es un dossier JSON validado con datos de mercado, resumen de negocio, hechos
clave y noticias recientes, todo con fuentes citables. El coste estimado aparece al final.

## Comandos rápidos

```bash
# Ejecutar el agente sobre cualquier empresa (ticker de cualquier bolsa)
cd backend
uv run python -m app.agent.run --ticker SHOP     # Shopify (NYSE)
uv run python -m app.agent.run --ticker SAP.DE   # SAP (Xetra)
uv run python -m app.agent.run --ticker 7203.T   # Toyota (Tokyo)

# Tests del backend (sin llamadas al modelo, 107 tests, ~28 s)
uv run pytest -q

# Correr el set de evaluación contra el agente (~13 entradas, ~$0.55, ~8 min)
uv run python -m app.evals.runner --max-turns 8

# Solo los tests del eval runner (sin API)
uv run pytest tests/evals -v

# Gate de seguridad (determinista, sin coste, bloquea si block rate < 90%)
uv run python -m app.redteam.run --ci

# Levantar el endpoint SSE
uv run uvicorn app.serving.main:app --reload
# POST /research {"ticker": "AAPL"} → stream SSE con eventos por turno + dossier final

# Métricas de las últimas ejecuciones vía Langfuse (requiere claves Langfuse en .env)
cd ..
uv run python scripts/metrics.py --days 7
```

## Métricas alcanzadas (v1.0.0)

Medidas sobre el set de evaluación de 13 empresas (6 USA large-cap, 1 mid-cap, 1 europea
completa, 3 datos parciales, 2 tickers inexistentes):

| Métrica | Valor |
|---|---|
| Task completion rate | **100%** (13/13) |
| Tool use accuracy | **100%** (13/13) |
| Seguridad (block rate) | **100%** (24/24 payloads bloqueados) |
| Mean cost por ejecución | **$0.044** |
| p95 cost por ejecución | **$0.053** |
| Turnos típicos | 2–4 (p95 = 4) |
| Budget cap por ejecución | $0.80 |
| Suite de tests | **107 passed** |

## Estructura

```
.
├── backend/
│   ├── app/
│   │   ├── agent/          # Loop de tool use, control de turnos, presupuesto
│   │   ├── tools/          # get_market_data, submit_dossier (client); web_search,
│   │   │                   # web_fetch, code execution (server-side Anthropic)
│   │   ├── guardrails/     # Timeouts, backoff, rate limiting, clasificador de output
│   │   ├── dossier/        # Schema Pydantic del dossier, validación
│   │   ├── serving/        # Endpoint FastAPI /research, streaming SSE
│   │   ├── evals/          # Dataset runner, métricas de gate
│   │   └── observability/  # Instrumentación Langfuse del loop
│   └── tests/              # Pytest (107 tests; mocking de tools y del modelo)
├── prompts/                # System prompt del agente y descriptions de tools
├── evals/
│   ├── gold.jsonl          # Set de evaluación (13 entradas firmadas)
│   └── fixtures/           # Fixtures de market data, web_search y web_fetch (39 ficheros)
├── security/
│   └── red-team-checklist.md  # Checklist de prompt injection (24 payloads)
├── docs/
│   ├── adr/                # Architecture Decision Records (13 ADRs)
│   └── architecture/       # C4 model en Mermaid
├── specs/                  # Specs de features (9 specs)
├── scripts/
│   └── metrics.py          # Métricas de agente vía Langfuse REST API
└── .github/workflows/      # CI: eval-gate bloquea merge si métricas caen
```

## Disciplina de trabajo

El proyecto se construye por bloques (`block-A` … `block-H`): un bloque = una rama = una
PR = un tag. Antes de empezar, lee `SESSION.md` (estado actual) y la última entrada de
`CHANGELOG.md`. La "Disciplina de sesión" completa está en `CLAUDE.md`.

## Deudas conocidas (post-v1.0.0)

- Suite de tests y redteam no corren en CI (solo en local); pendiente añadir jobs al
  workflow de GitHub Actions.
- Prompt del clasificador Haiku necesita afinado para distinguir datos de mercado
  descriptivos de recomendaciones de inversión (incidente FP-001 en `specs/04-guardrails.md`).
- Job nocturno end-to-end sin fixtures (web_search y web_fetch contra URLs reales).
