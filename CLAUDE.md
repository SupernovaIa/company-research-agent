# CLAUDE.md: contexto del proyecto company-research-agent

> Fichero leído por Claude Code y cualquier agente que abra este repo. Contiene el contexto mínimo del proyecto, las convenciones y cómo trabajar aquí.

## Qué es este proyecto

Agente de research financiero sobre empresas con tool use. Dado el nombre o ticker de una empresa cotizada, orquesta datos de mercado, búsqueda web y profundización en fuentes dentro de un loop controlado, y devuelve un dossier estructurado y citable a fecha de hoy. Caso práctico canónico de un agente con varias tools en producción: loop de tool use, guardrails del loop, output estructurado validado, serving con observabilidad y evaluación en CI con métricas propias de agente.

El agente es **stateless por diseño**: una ejecución produce un dossier y termina. Persistir un dossier vive fuera del loop.

Aviso transversal: **cada ejecución gasta API de pago.** El presupuesto por ejecución es parte del diseño. Una ejecución típica con Sonnet 4.6 y 8-12 turnos cuesta entre 0,20 y 0,40 dólares.

## Stack

- Backend: Python 3.12 + FastAPI + Anthropic Python SDK.
- Modelo del agente: Claude Sonnet 4.6 (tool use, web_search server-side). Se fija el tier; al construir se ancla la versión vigente con fecha.
- Guardrails: Claude Haiku 4.5 como clasificador de output.
- Validación: Pydantic v2 (schemas de tools y del dossier).
- Tools: `get_market_data` (client tool, yfinance, datos de mercado, sin API key); `web_search`, `web_fetch` y code execution server-side de Anthropic (búsqueda, profundización en una fuente, cálculo determinista); `submit_dossier` (cierre). Alternativas de pago y la versión propia de fetch documentadas como ADR.
- Observabilidad: Langfuse (trazas anidadas del loop, métricas custom).
- CI: GitHub Actions con evals como gate.
- Despliegue: Render / Fly.
- Package manager: uv.

## Estructura del repo

```
.
├── backend/
│   ├── app/
│   │   ├── agent/              Loop de tool use, control de turnos, presupuesto
│   │   ├── tools/              get_market_data y submit_dossier (client); web_search, web_fetch, code execution (server-side)
│   │   ├── guardrails/         Timeouts, backoff, rate limiting, clasificador de output
│   │   ├── dossier/            Schema Pydantic del dossier, validación
│   │   ├── serving/            Endpoint FastAPI /research, streaming SSE
│   │   ├── evals/              Dataset runner, métricas de agente
│   │   └── observability/      Instrumentación Langfuse del loop
│   └── tests/                  Pytest con mocking de tools y del modelo
├── prompts/                    System prompt del agente, descriptions de tools (versionados)
├── evals/
│   └── gold.jsonl              Set de evaluación de comportamiento anotado (~12-15)
├── security/
│   └── red-team-checklist.md   Checklist de prompt injection
├── docs/
│   ├── adr/                    Architecture Decision Records (MADR)
│   └── architecture/           C4 model en Mermaid
├── specs/                      Specs de features (SDD ligero)
├── .github/workflows/          CI workflows
├── .claude/
│   ├── commands/               Slash commands del proyecto
│   └── agents/                 Subagentes del proyecto (gold-annotator, redteam-runner)
├── CLAUDE.md                   Este fichero
├── CHANGELOG.md                Historial de cambios por sesión
├── SESSION.md                  Estado dinámico de la sesión actual
└── DECISIONS.md                Índice de ADRs
```

## Convenciones

### Idioma

- **Código en inglés siempre.** Variables, funciones, clases, comentarios, mensajes de log, nombres de ramas, mensajes de commit, paths de código.
- **Documentación en español neutro siempre.** README, ADRs, specs, diagramas C4, comentarios de PR, descripciones de issues. Sin voseo ni regionalismos.
- **Excepción técnica:** los `description` de las tools y el system prompt del agente se escriben para el modelo. Van en el idioma que mejor rinda según la evaluación (habitualmente inglés). Se versionan en `prompts/`.

### Git

- **Conventional Commits** desde el primer commit. `commitlint` aplicado en pre-commit.
- Ramas: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`. Una rama por bloque.
- PRs descritos en español, mensaje de commit en inglés.
- **Sin atribución de IA en los commits.** Nada de `Co-Authored-By: Claude` ni `Generated with`. El commit es del autor humano que lo revisa y lo firma.

### Disciplina de sesión

Aplica a cada bloque de trabajo (block-A … block-I). Esto es transversal: vale para todas las sesiones, no se repite en cada prompt.

- **Un bloque = una rama = una PR = un tag.** El bloque vive en su rama; al cerrar se mergea (squash) a `main` y se taggea `NN-block-X`.
- **Verifica el deliverable en vivo en cuanto exista, no al cerrar.** Status codes, trazas en Langfuse, coste por ejecución, una tool ejecutándose de verdad: evidencia real, no solo tests verdes. Los tests con mock validan lógica, no la integración con el modelo ni con servicios externos.
- **Qué no delega el agente:** alcance y output, schema de tools y del dossier, elección de proveedores, política de guardrails, tope de turnos y presupuesto. Esas decisiones las firma el humano.
- **Causa raíz contrastada, no de memoria.** Ante un bug o hallazgo, el primer diagnóstico puede estar mal con confianza. Verifica contra fuente autoritativa (Context7 o doc oficial) antes de actuar.
- **Vigilancia de coste:** cada ejecución del agente gasta API real; respeta el tope por ejecución también en desarrollo.
- **Cierre de un bloque:** `/close-session` corre los checks del CI en local, actualiza `SESSION.md` y `CHANGELOG.md`, y prepara el commit `chore(session): close block-X`. El agente abre la PR; tras abrirla, corre la skill `code-review` sobre ella, postea el resultado como comentario en la PR y para. El agente no mergea. El merge (squash) y el tag son acción humana.

### SDD ligero

- Antes de implementar una feature no trivial: spec en `specs/`. Estructura: goal, user story, approach, acceptance criteria, dependencies, risks.
- Antes de tomar una decisión arquitectónica: ADR en `docs/adr/`. Formato MADR.

### Testing

- Backend: Pytest. Mockeo de las tools externas y del modelo en tests unitarios. Tests de integración con tools reales bajo presupuesto controlado.
- El loop se testea con respuestas del modelo mockeadas que fuerzan cada `stop_reason`.

### Observabilidad

- Langfuse instrumentado desde el día uno. Cada ejecución es una traza; cada turno del loop, un span anidado con sus tool calls, tokens, coste y latencia.
- PII y material con copyright redactados antes de loguear contenido de tools.

### Guardrails del loop

- Tope de turnos por ejecución.
- Presupuesto máximo por ejecución; corte si se excede.
- Timeout y reintentos con backoff por tool.
- Rate limiting por usuario/IP en el endpoint.
- Defensa en capas frente a indirect prompt injection vía contenido de tools.
- Tools de solo lectura (mínimo privilegio; excessive agency bajo por diseño).

### Subagentes de desarrollo

- Dos subagentes en `.claude/agents/`: `gold-annotator` (anota lotes del set de evaluación), `redteam-runner` (ejecuta red teaming).
- Las decisiones de diseño (schema de tools y del dossier, elección de proveedores, política de guardrails, tope de turnos, presupuesto) no se delegan a subagentes: las firma el agente principal bajo revisión humana.

## Cómo trabajar aquí

1. Lee `SESSION.md` para saber el estado actual.
2. Lee la última entrada de `CHANGELOG.md` para ver qué se hizo en la sesión anterior.
3. Consulta `specs/` y `docs/adr/` según la tarea en curso.
4. Sigue la "Disciplina de sesión" de arriba para ramificar, verificar y cerrar el bloque.
5. Para correr el agente: `/research <ticker>` o el script equivalente.

## Comandos rápidos

```bash
# Instalar dependencias
uv sync

# Ejecutar el agente sobre una empresa
uv run python -m app.agent.run --ticker SHOP

# Correr evals
uv run pytest backend/tests/evals -v

# Levantar el endpoint
uv run uvicorn app.serving.main:app --reload
```

## Referencias

- Arquitectura del sistema: `docs/architecture/` (C4 en Mermaid).
- Decisiones de diseño: `docs/adr/` (índice en `DECISIONS.md`).
- Specs de features: `specs/`.
- Quickstart y operación: `README.md`.
