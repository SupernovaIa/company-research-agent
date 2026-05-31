# ADR-010: Loop sobre el SDK directo vs LangChain/LangGraph

**Estado:** aceptado (firmado en block-B 2026-05-31; se implementa en Fase 2, block-C)
**Fecha:** 2026-05-31
**Tags:** loop, sdk, abstraccion, langchain

## Contexto y problema

El loop de tool use (request con `tools`, lectura de `stop_reason`, ejecución de tool calls, envío de `tool_result`, control de turnos y de coste) se puede construir sobre el SDK directo de Anthropic o sobre una capa de abstracción como LangChain v1 con `create_agent` y LangGraph. La elección afecta a cuánto ves de la mecánica, a la transparencia del debugging y al boilerplate.

Este proyecto es didáctico: uno de sus objetivos es que el alumno entienda qué hace cada componente del loop.

## Drivers de la decisión

- Ver la mecánica del loop sin abstracciones, al menos en el desarrollo inicial.
- Debugging transparente del loop.
- Boilerplate aceptable para un agente único.
- Posibilidad de subir de abstracción si el sistema crece.

## Opciones consideradas

- A. SDK directo de Anthropic para construir el loop a mano.
- B. LangChain v1 con `create_agent`: el loop viene resuelto de fábrica.
- C. LangGraph con `StateGraph`: el loop se modela como un grafo de estados que tú escribes.

LangChain y LangGraph no son lo mismo. `create_agent` de LangChain te da el loop hecho y oculta la mecánica. LangGraph es más bajo nivel: una librería de máquinas de estado donde defines nodos y transiciones de forma explícita; expone más que LangChain, pero sigue siendo más estructura de la que pide un loop lineal de un solo agente.

## Decisión

Opción A para el desarrollo inicial. El loop se construye sobre el SDK directo de Anthropic, para que cada componente quede a la vista: request con `tools`, `stop_reason == "tool_use"`, ejecución de los bloques `tool_use`, envío de `tool_result`, contador de turnos y de coste, y corte por límite. El debugging es transparente porque no hay capa intermedia que oculte el flujo.

La abstracción con LangChain v1 o LangGraph (opciones B y C) queda como decisión opcional al final, si el sistema crece hacia varios agentes o el boilerplate del loop manual estorba. Si en algún momento se adopta LangChain con server tools de Anthropic, hay que decidir si todo pasa a client tools o se mantiene el SDK directo, porque el wrapper puede ocultar lo que ocurre server-side; esa elección se documenta.

## Consecuencias

### Positivas

- Control total del loop y debugging transparente, sin magia intermedia.
- El alumno ve qué hace cada componente del loop de tool use.
- Sin curva de aprendizaje de un framework de orquestación para un agente único.

### Negativas

- Más boilerplate que con `create_agent`: el loop, el control de turnos y el de coste se escriben a mano.
- Si el sistema crece a varios agentes, la capa manual obliga a reescribir o a adoptar la abstracción más tarde.

## Alternativas descartadas

- LangChain v1 con `create_agent` (opción B): reduce boilerplate e integra tracing, descartado para el arranque porque oculta la mecánica que el alumno tiene que ver y opaca el debugging del loop.
- LangGraph con `StateGraph` (opción C): aporta cuando el sistema es un grafo de verdad (varios agentes, ramificación, checkpointing, human-in-the-loop). Descartado aquí porque el agente es único y el loop es lineal (ver ADR-002): modelar un `while` de un solo ciclo como un grafo añade el vocabulario de LangGraph sin pagar por su valor. Reservado para cuando el sistema crezca a varios agentes; entonces se justifica con la topología, no antes.
