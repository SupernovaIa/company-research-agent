# Spec 04 · Guardrails del loop

**Estado:** aceptada parcialmente (guardrails operativos implementados en block-E; indirect prompt injection y clasificador de output quedan para block-F)
**Fase:** 3 · Guardrails + red team (block-E guardrails operativos, block-F inyección y red team)
**Dependencias:** Spec 03 (loop), Spec 02 (tools), Spec 01 (schema del Dossier)

## Goal

Blindar el loop con timeouts por tool, reintentos con backoff, presupuesto por ejecución con corte, rate limiting, validación de outputs de tools, defensa en capas contra indirect prompt injection, validación del dossier final con reintento y auditoría de cada ejecución.

## User story

> Como operador del agente con un endpoint público, quiero que ninguna ejecución gaste de más, que un proveedor caído no rompa el loop, que el contenido recuperado no inyecte instrucciones y que el dossier final cumpla el schema antes de devolverse, todo registrado para forensics.

## Outline de approach

- [ ] Timeout duro por tool (5-15s). Al expirar, `tool_result` con error y `recoverable: true`.
- [ ] Timeout del cliente del modelo: se fija en el constructor del cliente Anthropic (o por request con `with_options(timeout=...)`), no en parámetros sueltos de la llamada. El agente (Sonnet, ejecución larga) y el clasificador de output (Haiku, llamada corta) usan **clientes dedicados con su propio timeout**, porque sus perfiles de latencia difieren.
- [ ] Reintentos con backoff exponencial (Tenacity): 3 intentos (1s/2s/4s) para errores transitorios (5xx, conexión, 429); 0 reintentos para 4xx (input mal formado, autenticación).
- [ ] Presupuesto por ejecución: contador de tokens (input + output) convertido a USD con el rate card del modelo. Al superar el tope (0,30-0,80 USD), cortar y forzar respuesta o devolver error.
- [ ] Rate limiting por usuario/IP en el endpoint (Upstash Redis o middleware) y respeto a los rate limits de los proveedores externos con backoff ante 429. Control de concurrencia del backend.
- [ ] Validación de outputs de tools contra su schema Pydantic antes de inyectar al contexto; sanitizar blobs de texto (input no confiable).
- [ ] Indirect prompt injection en capas (vector principal: el contenido de `web_fetch`, y los resultados de `web_search`, contenido externo no confiable): system prompt que marca el contenido entre delimitadores como datos del mundo; envoltura de outputs de tools en bloques delimitados; clasificador de output con Haiku 4.5; descarte si el agente "cambia de tarea" a mitad del loop.
- [ ] Excessive agency: las client tools son de solo lectura (sin escritura en BBDD ni envío de email). La code execution tool ejecuta Python arbitrario en una sandbox, así que la restricción "solo cálculo descriptivo, no especular ni recomendar" no se impone en el límite de la tool: pasa al system prompt y al clasificador de output, más los límites de la sandbox (sin red si no hace falta, timeouts, tamaño de salida). Ver ADR-011.
- [ ] Validación del dossier final con Pydantic; ante fallo, un reintento con el error explícito; si persiste, error al usuario con el output parcial.
- [ ] Auditoría: cada ejecución guarda la traza completa (tool calls, inputs, outputs, latencias, tokens, coste).

## Acceptance criteria

- Una tool que excede su timeout produce error recuperable y el loop continúa.
- Un timeout del cliente del modelo dispara el comportamiento de fallback esperado (test que ata "timeout excedido → fallback", para que el timeout no quede muerto sin que nadie se entere).
- Un proveedor que devuelve 503 reintenta con backoff y, si todo falla, devuelve error al modelo sin romper el loop.
- Una ejecución que supera el presupuesto se corta y no sigue consumiendo tokens.
- El endpoint limita peticiones por IP (configurable) y rechaza el exceso.
- Un output de tool con instrucciones inyectadas no altera la tarea del agente: el system prompt lo trata como dato y el clasificador descarta respuestas fuera del schema.
- Un dossier que no valida dispara un reintento; tras el segundo fallo devuelve error con el parcial.
- Ninguna tool tiene efectos secundarios sobre tus sistemas o datos (escritura en BBDD, envío); los efectos de la code execution tool quedan confinados a su sandbox efímera.
- Un intento de que el agente use la code execution tool para especular, valorar o recomendar lo bloquean el system prompt y el clasificador de output.

## Riesgos

- Reintentos sin backoff ante un proveedor con rate limit amplifican el problema. Backoff exponencial obligatorio.
- Clasificador de output con el mismo modelo del agente: sesgo de auto-aprobación. Usar Haiku 4.5 o un proveedor distinto.
- Logs con outputs de tools sin redacción pueden contener PII o material con copyright. Tratar logs como datos sensibles.

## Preguntas abiertas

- Umbral de presupuesto por ejecución: calibrar con la distribución de coste real (p95 + margen) en la Fase 4 (block-G).
- Backend de rate limiting (Upstash Redis vs middleware simple): decidir según volumen esperado.
