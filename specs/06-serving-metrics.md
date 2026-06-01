# Spec 06 · Serving, métricas y observabilidad

**Estado:** aceptada parcialmente (SSE ✓, trazas enriquecidas ✓, 5 métricas computables ✓; tool_use_accuracy y desglose de coste por tool pendientes de block-H)
**Fase:** 4 · Serving + observabilidad (block-G). Instrumentación cruda de Langfuse adelantada a block-C.
**Dependencias:** Spec 03 (loop), Spec 05 (output estructurado), Spec 04 (guardrails)

## Goal

Exponer el agente vía `POST /research` con SSE, instrumentar cada ejecución en Langfuse con una traza por ejecución y un span por turno, y calcular las métricas específicas de un agente con tool use.

## User story

> Como operador del agente, quiero un endpoint que reciba un ticker o nombre de empresa y devuelva el loop en streaming, con cada ejecución trazada turno a turno en Langfuse y las métricas de agente calculadas, para entender qué pasó cuando algo falla y para vigilar coste y latencia.

## Outline de approach

- [ ] Endpoint `POST /research` con body `{"ticker": "SHOP"}` o `{"empresa": "Acme GmbH"}`. Devuelve SSE con eventos del loop y un evento final con el dossier validado.
- [ ] Reaplicar el mismo patrón de serving del chatbot RAG (FastAPI + Render/Fly + Langfuse + GitHub Actions): mismo enfoque, no copia literal de código. El cambio está en las métricas.
- [ ] Instrumentación Langfuse base (ya cableada en block-C): una traza por ejecución; un span por turno con tool calls anidados (name, input, latencia, tokens, coste), tool results y decisión del modelo; totales al cierre (tokens, coste, latencia). En block-G se enriquece con los pasos añadidos después (validación del dossier, reintento de schema, guardrails que cortan, clasificador de output) y los atributos que necesitan las métricas.
- [ ] Métrica **task completion rate**: porcentaje de ejecuciones que terminan con dossier válido (sin error, sin presupuesto agotado, sin tope de turnos sin completar).
- [ ] Métrica **tool use accuracy**: porcentaje de tool calls correctamente elegidas según el contexto, medible contra el set de evaluación anotado.
- [ ] Métrica **tool error rate**: errores totales / tool calls, desglosada por tool.
- [ ] Métrica **latencia por ejecución**: distribución p50/p95/p99 (la unidad es la ejecución completa, no la query).
- [ ] Métrica **coste por ejecución**: distribución, desglose por modelo y por tool.
- [ ] Métrica **turnos por ejecución**: distribución; si el p95 se acerca al tope, subirlo o mejorar el agente.
- [ ] Dashboard mínimo: completion rate, tool use accuracy, coste medio, latencia p95, errores por tool.

## Acceptance criteria

- `POST /research` con un ticker válido devuelve un stream SSE con un evento por turno y un evento final con el dossier.
- Cada ejecución produce una traza en Langfuse con un span por turno y tool calls anidados.
- Las seis métricas de agente (completion rate, tool use accuracy, tool error rate, latencia p50/p95/p99, coste por ejecución, turnos por ejecución) se calculan y se exponen.
- El dashboard refleja las métricas sobre ejecuciones reales de desarrollo.
- Las trazas no almacenan PII ni material con copyright sin redacción.

## Riesgos

- Trazas con outputs completos de tools pueden contener PII (nombres en comunicados, emails en filings) o copyright. Redactar y tratar trazas como datos sensibles.
- Métricas calculadas sobre samples sesgados (solo ejecuciones exitosas) inflan el completion rate. Anotar también los fallos.
- Infraestructura compartida con el chatbot RAG: una falla puede afectar a ambos. Documentar dependencias.

## Preguntas abiertas

- Verbosidad de trazas: verbose en desarrollo vs compactas + sampling en producción. Decidir según coste de almacenamiento.
- Tool use accuracy con anotación humana vs LLM-as-judge para coverage del set. Definir mezcla en la Fase 5 (block-H).
