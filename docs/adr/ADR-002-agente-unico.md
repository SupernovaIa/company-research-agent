# ADR-002: Agente único con varias tools

**Estado:** propuesto (se firma en Fase 1, block-B)
**Fecha:** <YYYY-MM-DD>
**Tags:** arquitectura, diseño-agente

## Contexto y problema

El agente investiga una empresa orquestando datos de mercado, búsqueda web y profundización en una fuente concreta. Hay dos formas de organizar esa orquestación: un solo agente que decide qué tool llamar en cada turno, o varios agentes especializados (research, financiero, noticiero, redactor) que se coordinan. La elección define la complejidad del sistema y el coste de mantenerlo.

## Drivers de la decisión

- La tarea es una sola: producir un dossier de una empresa.
- Contexto coherente: cada hecho del dossier se apoya en información que el modelo va recopilando dentro de la misma conversación.
- Coste de orquestación bajo deseable para el arranque.
- Capacidad de subdividir más adelante si la tarea crece.

## Opciones consideradas

- A. Agente único con tools especializadas (`get_market_data`, `web_search`, `web_fetch`, code execution). El modelo decide qué tool usar en cada turno.
- B. Varios agentes especializados con handoff: un agente de research, uno financiero, uno de noticias y un redactor final.

## Decisión

Opción A. Un agente único con tools especializadas. El modelo mantiene el contexto completo de la investigación y decide qué tool invocar a partir del `description` de cada una. La separación de responsabilidades se logra por tools, no por agentes.

Si la tarea creciera a research más valoración más comparables, se reconsidera y se justifica subdividir en varios agentes con handoff.

El agente desplegado es uno solo. Los subagentes que aparecen en la construcción del repo (anotación del set, red teaming) son herramienta de desarrollo, no nodos del sistema en runtime (ver ADR-009).

## Consecuencias

### Positivas

- Sistema simple: un loop, un contexto, un punto de control de coste y turnos.
- El contexto es coherente: el modelo razona sobre todo lo recopilado sin reconstruir estado entre agentes.
- Sin complejidad de orquestación ni de handoff entre agentes.

### Negativas

- El contexto crece de forma lineal con los turnos: en una tarea heterogénea, una sola conversación puede saturarse antes que varios contextos limpios. Se controla con la salida acotada de las tools (ver ADR-005) y el tope de turnos (ver ADR-007).
- La separación de responsabilidades depende de la calidad de las descriptions de las tools, no de límites duros entre agentes.

## Alternativas descartadas

- Varios agentes especializados con handoff: válido para una tarea muy heterogénea, descartado aquí por sobreingeniería. Añade orquestación y coordinación que la tarea actual no necesita. Queda como evolución si el alcance crece.
