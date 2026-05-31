# company-research-agent

Agente de research financiero con tool use. Dado el nombre o el ticker de una empresa
cotizada, orquesta datos de mercado, búsqueda web y profundización en fuentes dentro de
un loop controlado, y devuelve un dossier estructurado y citable a fecha de hoy.

El agente es **stateless por diseño**: una ejecución produce un dossier y termina.

> ⚠️ **Aviso de coste.** Cada ejecución del agente gasta API de pago (Anthropic). El
> presupuesto por ejecución es parte del diseño: hay un tope de turnos y un tope de coste
> por ejecución (ver `AGENT_MAX_TURNS` / `AGENT_BUDGET_USD` y el ADR-007). Una ejecución
> típica con Sonnet 4.6 y 8-12 turnos cuesta entre 0,20 y 0,40 dólares. Respeta el tope
> también en desarrollo.

## Stack

- Python 3.12 + FastAPI + Anthropic Python SDK.
- Modelo del agente: Claude Sonnet 4.6 (tool use, `web_search`/`web_fetch`/code execution
  server-side). Clasificador de guardrails: Claude Haiku 4.5.
- Validación con Pydantic v2. Observabilidad con Langfuse. CI en GitHub Actions con evals
  como gate. Package manager: uv.

Detalle en `CLAUDE.md`, las decisiones en `docs/adr/` (índice en `DECISIONS.md`) y la
arquitectura en `docs/architecture/`.

## Quickstart

Requisitos: [uv](https://docs.astral.sh/uv/), Node.js (solo para los hooks de commit) y
una `ANTHROPIC_API_KEY`.

```bash
# 1. Variables de entorno
cp .env.example .env   # rellena ANTHROPIC_API_KEY (y Langfuse si vas a trazar)

# 2. Dependencias del backend (crea el venv con Python 3.12)
cd backend && uv sync

# 3. Hooks de commit (commitlint + husky) — desde la raíz del repo
cd .. && npm install

# 4. Levantar el endpoint
cd backend && uv run uvicorn app.serving.main:app --reload
curl http://127.0.0.1:8000/health   # -> {"status":"ok"}
```

## Comandos rápidos

```bash
# Tests del backend
cd backend && uv run pytest -q

# Ejecutar el agente sobre una empresa (disponible a partir del block del loop)
cd backend && uv run python -m app.agent.run --ticker SHOP

# Evals
cd backend && uv run pytest tests/evals -v
```

## Estructura

El repo sigue la estructura descrita en `CLAUDE.md`. Resumen:

- `backend/app/` — `agent`, `tools`, `guardrails`, `dossier`, `serving`, `evals`,
  `observability`.
- `prompts/` — system prompt y descriptions de tools (versionados).
- `evals/`, `security/`, `docs/`, `specs/` — evaluación, red teaming, arquitectura y specs.

## Disciplina de trabajo

El proyecto se construye por bloques (`block-A` … `block-I`): un bloque = una rama = una
PR = un tag. Antes de empezar, lee `SESSION.md` (estado actual) y la última entrada de
`CHANGELOG.md`. La "Disciplina de sesión" completa está en `CLAUDE.md`.
