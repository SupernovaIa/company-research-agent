# ADR-011: Cálculo con la code execution tool (built-in)

**Estado:** propuesto (se firma en Fase 1, block-B)
**Fecha:** <YYYY-MM-DD>
**Tags:** tools, calculo, code-execution, guardrails

## Contexto y problema

El dossier incluye métricas derivadas de los datos de mercado: variación frente al rango de 52 semanas, crecimiento, ratios de comprobación. El modelo no es fiable haciendo aritmética en la cabeza, así que el cálculo se delega a una herramienta determinista. La pregunta es si construir una tool de cálculo propia y acotada (`compute_metrics`) o usar la code execution tool de Anthropic.

## Drivers de la decisión

- Determinismo: los números derivados no se alucinan.
- Fricción mínima: no reinventar una capacidad que ya existe.
- Mínimo privilegio: dar al agente solo la capacidad de cálculo que necesita, no más.
- El agente es de solo lectura y no debe especular ni recomendar.

## Opciones consideradas

- A. `compute_metrics` como client tool propia: un conjunto cerrado de cálculos con nombre (`pct_change`, `distance_from_high`, `cagr`…), input validado con Pydantic, output con la fórmula usada. Acota qué puede computar el agente en el límite de la tool.
- B. Code execution tool de Anthropic (`code_execution_20260120`): sandbox de Python/bash server-side, GA, soportada en Sonnet 4.5+/Opus 4.5+, gratis cuando se usa junto a `web_search` o `web_fetch`.

## Decisión

Opción B. La code execution tool de Anthropic. Es GA, no requiere infra propia y es gratis junto a las server tools que el agente ya usa (`web_search`, `web_fetch`). No se reinventa una capacidad de cálculo que ya está resuelta y probada.

El contraste con las otras tools del sistema cierra el criterio de selección por privilegio:

- En la extracción de URL, el built-in (`web_fetch`) era preferible porque reduce superficie (ver ADR-005).
- En el cálculo, el built-in es **más potente** que una tool acotada: la sandbox ejecuta Python arbitrario. Eso quita la garantía que daría `compute_metrics` de acotar "solo cálculo descriptivo" en el límite de la tool.

Consecuencia que se asume: con Python arbitrario, la restricción de "no especular ni recomendar, no valorar" no se puede imponer en el límite de la tool. Pasa a las capas de guardrails: system prompt explícito y clasificador de output (ver Spec 04 y la checklist de red team, Spec 09), más los límites de la propia sandbox (sin red si no hace falta, timeouts, tamaño de salida). El red team incluye payloads que intenten usar code execution para especular, valorar o recomendar.

Uso concreto: la code execution tool computa métricas descriptivas sobre números que el agente ya tiene en contexto (campos de `MarketData`, datos recuperados con `web_fetch`). No es una tool de adorno; si el set de evaluación muestra que casi no se usa, se reconsidera para no penalizar la tool use accuracy.

## Consecuencias

### Positivas

- Cero infra y sin tool de cálculo que mantener; capacidad probada y GA.
- Gratis junto a `web_search` y `web_fetch`.
- Números derivados deterministas, no alucinados.

### Negativas

- La restricción "solo descriptivo, no especular" no es imponible en el límite de la tool: depende de system prompt y clasificador de output. Más superficie que defender.
- Acoplamiento con Anthropic para el cálculo y comportamiento server-side opaco.

## Alternativas descartadas

- `compute_metrics` propia (opción A): acota el cálculo en el límite de la tool y enseña validación de input, descartada porque reinventa un subconjunto de una capacidad built-in ya disponible. Queda como la versión que se construye a mano si se necesita acotar el cálculo de forma estricta por mínimo privilegio.
