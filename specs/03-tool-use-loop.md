# Spec 03 · Loop de tool use

**Estado:** pre-construida (se implementa en Fase 2, block-C)
**Fase:** 2 · Loop + datos + output (block-C)
**Dependencias:** Spec 02 (tools), Spec 01 (schema del Dossier)

## Goal

Construir el loop agéntico sobre el Anthropic Python SDK: `messages.create` con tools, ejecución de `tool_result` por turno, tope de turnos, caching del contexto estable y streaming SSE al cliente.

## User story

> Como operador del agente, quiero un loop disciplinado que llame a las tools que el modelo decide, alimente los resultados de vuelta y termine de forma controlada, con un tope de turnos que evite la divergencia y caching que reduzca el coste en producción.

## Outline de approach

- [ ] Request inicial: `messages.create()` con `tools=[...]` y `messages=[{"role": "user", "content": ...}]`.
- [ ] Bucle por `stop_reason`: si `tool_use`, ejecutar cada bloque (`id`, `name`, `input`) y devolver `tool_result` con `tool_use_id`; si `end_turn`, el texto es la respuesta candidata.
- [ ] Parsing de la respuesta como **lista de bloques**: `response.content` es una lista de bloques con `type` (`text`, `tool_use` y, si se activa extended thinking, `thinking`). Centralizar la extracción en un helper que itere por `block.type`; no asumir `content[0]` ni tratar el contenido como string. Un parsing ingenuo rompe en silencio cuando aparece un bloque `thinking` o varios bloques de texto.
- [ ] Server tools de Anthropic (`web_search`, `web_fetch`, code execution) llegan ya resueltas en la respuesta; client tools (`get_market_data`, `submit_dossier`) requieren ejecución y envío de `tool_result`. Ambos tipos conviven en la misma sesión.
- [ ] Paralelismo: cuando el modelo devuelve varios bloques `tool_use`, ejecutarlos en paralelo y devolver todos los `tool_result` juntos.
- [ ] Tope de turnos (típico 8-12; tope blando ~15, tope duro 20-25, ver ADR-007): contador en el cliente. Al tope, forzar respuesta final con mensaje al modelo ("ya no puedes llamar más tools, redacta el dossier con lo que tienes").
- [ ] Caching: marcar system prompt y definiciones de tools como bloques cacheables; mantener estables los bloques iniciales para no invalidar el cache.
- [ ] `tool_choice`: `auto` por defecto; opción de forzar una tool concreta en el primer turno si conviene arrancar con `get_market_data`.
- [ ] Estado del loop: lista de mensajes que crece por turno; vigilar el crecimiento del contexto (input acumulado por turno).
- [ ] Streaming SSE: emitir un evento por turno (tool invocada, resultado parcial, respuesta final) al frontend.
- [ ] Contador de tokens y coste acumulado por ejecución, expuesto al cierre. Con streaming, capturar el `usage` de los eventos del stream (`message_start` para input, `message_delta`/`message_stop` para output), no de un atributo de una respuesta streameada. El presupuesto se evalúa entre turnos acumulando el `usage` de cada `messages.create`.

## Acceptance criteria

- Una ejecución sobre un ticker cotizado termina en `end_turn` con un dossier candidato en menos del tope de turnos.
- El loop ejecuta tool calls en paralelo cuando el modelo las emite en un mismo turno.
- Al alcanzar el tope de turnos, el loop fuerza respuesta final y no continúa.
- El cache de system prompt + tools produce hit en ejecuciones consecutivas (verificable en los `usage` de la respuesta).
- El stream SSE emite un evento por turno y un evento final con el dossier.
- Tests del loop con SDK mockeado cubren los caminos `tool_use`, `end_turn` y tope alcanzado.
- El helper de extracción procesa correctamente una respuesta con bloque `thinking` además de `text`/`tool_use` (test con respuesta multi-bloque mockeada).

## Riesgos

- Sin tope ni presupuesto, una ejecución mal arrancada gasta tokens sin control. Mitigar con tope de turnos aquí y presupuesto en la Fase 3 (block-E).
- Cambios dinámicos en bloques cacheables invalidan el cache. Mitigar estructurando el system prompt y las tools como bloques estables iniciales.
- Server tools son opacas en debugging. Mitigar documentando su uso y apoyándose en las trazas de Anthropic.

## Preguntas abiertas

- Tope de turnos final: arrancar con valores provisionales y recalibrar tras medir la distribución de turnos por tarea (p95 + margen) cuando exista el set de evaluación (block-H e iteración, ver ADR-007).
- Tamaño de tool result que dispara el coste por turno: medir y acotar en block-C.
