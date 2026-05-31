# ADR-001: Stack del proyecto

**Estado:** propuesto (se firma en Fase 1, block-B)
**Fecha:** <YYYY-MM-DD>
**Tags:** stack, foundational

## Contexto y problema

El proyecto es un agente de research financiero con tool use. Dado el nombre o el ticker de una empresa cotizada, orquesta datos de mercado (`get_market_data`), búsqueda web (`web_search`), profundización en una fuente (`web_fetch`) y cálculo determinista (code execution), y devuelve un dossier estructurado y citable. Hay que fijar un stack que reaplique el mismo patrón del proyecto anterior (el chatbot RAG) en lo que sea común, y que exponga la mecánica del loop agéntico en lo que es nuevo.

## Drivers de la decisión

- Reaplicar el patrón de serving, observabilidad y evals del chatbot RAG (FastAPI, Langfuse, GitHub Actions, Render/Fly): mismo enfoque, no copia literal de código.
- Ver la mecánica del loop de tool use sin abstracciones: construir el loop sobre el SDK directo del proveedor.
- Una sola fuente de complejidad LLM (un proveedor) para reducir variables durante el desarrollo.
- Stack alineado con el de producción gestionada para que el aprendizaje transfiera.

## Opciones consideradas

- A. Python + Anthropic Python SDK + Claude Sonnet 4.6 + FastAPI + Pydantic v2, con loop construido sobre el SDK directo.
- B. Python + LangChain v1 / LangGraph como capa de orquestación del loop desde el primer día.
- C. Stack TypeScript con el SDK de Anthropic para JS.

## Decisión

Opción A. El stack del proyecto queda:

- **Lenguaje y runtime:** Python 3.12.
- **Package manager:** uv (ya en uso desde el proyecto anterior).
- **Modelo del agente:** Claude Sonnet 4.6 vía Anthropic Python SDK, con `web_search` server-side y Haiku 4.5 como clasificador de guardrails.
- **Validación y schemas:** Pydantic v2 para inputs y outputs de tools y para el schema del dossier.
- **Serving:** FastAPI con `StreamingResponse` (SSE) para emitir los eventos del loop.
- **Observabilidad:** Langfuse, reaplicando el patrón del chatbot RAG.
- **CI/CD:** GitHub Actions con evals como gate de PR.
- **Hosting:** Render o Fly, el mismo PaaS del proyecto anterior.

El loop de tool use se construye sobre el SDK directo de Anthropic. La abstracción con LangChain queda como decisión separada y opcional (ver ADR-010).

## Consecuencias

### Positivas

- Se reaplica el mismo patrón de FastAPI, Langfuse, GitHub Actions y el PaaS sin reaprenderlo.
- El loop sobre el SDK directo deja ver cada componente: request con `tools`, `stop_reason`, ejecución de tool calls, envío de `tool_result`.
- Una sola API key de pago (`ANTHROPIC_API_KEY`): `get_market_data` (yfinance) no requiere credencial, y `web_search`, `web_fetch` y code execution corren server-side dentro de la llamada a Anthropic.

### Negativas

- Acoplamiento al SDK de Anthropic en el núcleo del loop. Cambiar de proveedor obliga a reescribir esa capa.
- El loop manual sube el boilerplate frente a una abstracción tipo `create_agent`.

## Alternativas descartadas

- LangChain v1 / LangGraph desde el primer día: descartado para el desarrollo inicial porque oculta la mecánica que el alumno tiene que ver. Reservado como abstracción opcional al final (ADR-010).
- Stack TypeScript: descartado por continuidad con el chatbot RAG, que ya está en Python.
