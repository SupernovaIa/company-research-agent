# ADR-006: Output estructurado vía tool de submit

**Estado:** propuesto (se firma en Fase 1, block-B; se implementa en Fase 2, block-D)
**Fecha:** <YYYY-MM-DD>
**Tags:** output-estructurado, schema, dossier

## Contexto y problema

El agente devuelve un `CompanyDossier` con schema fijo: `company`, `market_data`, `business_overview`, `key_facts`, `recent_news`, `sources` y metadatos de la ejecución, con cada `Fact` y `NewsItem` citando un `Source` real. El schema es el contrato con quien consume el agente. Hay que decidir cómo se obtiene ese output estructurado del modelo de forma que se valide contra el schema antes de devolverlo al cliente.

## Drivers de la decisión

- Robustez: el output tiene que cumplir el schema de forma fiable, no de forma intermitente.
- Integración limpia con el loop de tool use ya construido.
- Validación nativa del schema en el punto donde el modelo produce el dossier.
- Disponibilidad: que la solución funcione con el modelo elegido hoy, sin depender de features en preview.

## Opciones consideradas

- A. Instrucción en el system prompt más un ejemplo del JSON esperado. El modelo devuelve texto que parseas a JSON.
- B. Una tool dedicada `submit_dossier(...)` con el schema de `CompanyDossier` como `input_schema`. El modelo termina llamando a esta tool y el cliente la intercepta como señal de fin.
- C. Structured output del modelo vía parámetro de la API.

## Decisión

Opción B. Una tool dedicada `submit_dossier(...)` cuyo `input_schema` es el schema del dossier. El modelo cierra la investigación llamando a esta tool, y el cliente la intercepta como señal de fin del loop. El SDK valida el schema en la llamada, y la salida pasa por Pydantic antes de devolverse al cliente. Si la validación falla, se reintenta una vez con el error explícito; si persiste, se devuelve error con el output parcial para debugging. El reintento es una llamada extra al modelo, así que cuenta contra el tope de turnos y el presupuesto por ejecución (ver ADR-007).

Esto convierte el "devuelve un dossier" en "llama a esta tool con el dossier", que es más robusto que pedir texto y parsearlo.

## Consecuencias

### Positivas

- Validación del schema en el punto de la llamada, integrada con el loop existente.
- Señal de fin del loop explícita: el cliente sabe que el agente terminó cuando intercepta `submit_dossier`.
- Funciona con el modelo elegido hoy, sin depender de un modo en preview.

### Negativas

- El comportamiento depende del `description` de `submit_dossier`. Si se cambia el description, el modelo puede dejar de invocarla bien y hay que iterar con el set de evaluación.
- Una tool más en la lista, con su superficie de mantenimiento.

## Alternativas descartadas

- Parseo de texto (opción A): simple, descartado por frágil ante variaciones de formato. En producción produce errores intermitentes difíciles de reproducir.
- Structured output vía parámetro de la API (opción C): genera salida conforme a un JSON schema sin definir ninguna tool, y es GA en la API (sin beta header; `output_config.format`). No se elige como mecanismo de cierre porque `submit_dossier` encaja mejor en el patrón de tool use: una sola tool intercepta el fin del loop y valida el schema en el mismo punto donde el modelo produce el dossier. Queda como alternativa nativa para forzar el schema del texto final si se prefiere no modelar el cierre como tool.
