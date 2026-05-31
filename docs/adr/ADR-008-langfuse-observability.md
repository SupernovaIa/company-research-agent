# ADR-008: Observabilidad del loop con Langfuse

**Estado:** aceptado (firmado en block-B 2026-05-31; instrumentación base en Fase 2, block-C, cuando nace el loop; métricas de agente y comandos en Fase 4, block-G)
**Fecha:** 2026-05-31
**Tags:** observabilidad, metricas, tracing

## Contexto y problema

Un agente con tool use necesita trazas del loop completo para entender qué pasó cuando algo falla, y métricas específicas de agente: task completion rate, tool use accuracy, latencia y coste por ejecución. Cada ejecución tiene varios turnos, y cada turno tiene tool calls con su input, output, latencia, tokens y coste. Hay que elegir la plataforma de observabilidad que instrumente el loop con trazas anidadas por turno.

## Drivers de la decisión

- Continuidad con el chatbot RAG, que ya usa Langfuse.
- Trazas anidadas por turno y por tool call, no solo por request.
- Métricas custom y datasets de evaluación dentro de la misma plataforma.
- Instrumentación simple del loop con un SDK Python.

## Opciones consideradas

- A. Langfuse: rico en features de LLM, trazas anidadas, observabilidad de tool use, mismo patrón del proyecto anterior.
- B. LangSmith: tracing nativo si todo el stack es LangChain.
- C. OpenTelemetry: estándar abierto, vendor-neutral, instrumentación manual de cada paso del loop con un backend de observabilidad aparte.

## Decisión

Opción A. Langfuse, en modo Cloud con el tier gratuito (Hobby) para el repo de referencia: fricción mínima (solo claves, sin operar infraestructura). El self-hosted de Langfuse queda documentado como upgrade de producción cuando haya requisitos de residencia de datos o privacidad, relevantes porque las trazas pueden contener contenido externo con PII o copyright; conviene avisar de que el self-hosted v3 es pesado de operar (ClickHouse, Redis, almacenamiento de objetos y Postgres). El modo se alinea con el del proyecto anterior por continuidad.

Reaplica el patrón del chatbot RAG (mismo enfoque, no copia literal) y soporta trazas anidadas por turno. Cada ejecución guarda el input inicial, un span por turno con sus tool calls (name, input, latencia, tokens, coste), los tool results, los tokens del modelo y la decisión, el output final y su validación, más el total de tokens, coste y latencia. Las tools server-side de Anthropic (`web_search`, `web_fetch`, code execution) se trazan desde la respuesta del modelo (bloques `server_tool_use` y `usage`), con menos granularidad que las client tools (`get_market_data`, `submit_dossier`), que tu wrapper cronometra span a span. Es la contrapartida de apoyarse en server tools (ver ADR-003).

Las métricas del agente se calculan sobre estas trazas: completion rate, tool error rate por tool, latencia y coste por ejecución, y turnos por ejecución. La tool use accuracy es la excepción: no sale de la traza sola, porque la traza dice qué tool se llamó pero no si era la acertada; se calcula contra el set anotado (ver ADR-009 y la spec de evals). Estas métricas actúan como gate de PR en CI.

## Consecuencias

### Positivas

- Sin plataforma nueva: el mismo enfoque de observabilidad del proyecto anterior.
- Trazas anidadas que permiten drill-down por turno y por tool call.
- Datasets de evaluación y métricas custom en la misma herramienta.

### Negativas

- Acoplamiento con Langfuse. Cambiar de plataforma obliga a reinstrumentar.
- Las trazas con outputs completos de tools pueden contener PII o material con copyright. Hay que tratarlas como datos sensibles y aplicar redacción o sampling en producción.

## Alternativas descartadas

- LangSmith: óptimo si todo el stack fuera LangChain, descartado porque el loop se construye sobre el SDK directo y la observabilidad ya está en Langfuse.
- OpenTelemetry: vendor-neutral, descartado para el arranque por el coste de instrumentar manualmente cada paso del loop y montar un backend de observabilidad aparte. Reservado si se necesita backend genérico más adelante.
