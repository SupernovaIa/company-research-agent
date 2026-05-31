# ADR-013: Defensa en capas frente a indirect prompt injection y red team

**Estado:** aceptado (implementado en block-F 2026-05-31)
**Fecha:** 2026-05-31
**Tags:** seguridad, prompt-injection, guardrails, owasp-llm, red-team

## Contexto y problema

El agente lee contenido externo no confiable (`web_fetch`, `web_search`, datos de mercado) que entra en su contexto. Ese contenido es el vector principal de indirect prompt injection (ADR-005, Spec 04, Spec 09): puede intentar que el agente cambie de tarea, filtre su system prompt, emita un veredicto de compra/venta o ejecute una acción fuera de su alcance. Ninguna defensa única es suficiente; la Spec 04 y la Spec 09 piden defensa en capas y una checklist de red team con un umbral de bloqueo antes del tag.

La pregunta concreta de block-F: qué capas implementar, cómo cablearlas en el loop ya existente (clasificador Haiku 4.5 ya declarado como `GUARDRAIL_MODEL`, tools de solo lectura, loop con `submit_dossier`) y cómo gatear el red team de forma fiable y barata.

## Drivers de la decisión

- Defensa en profundidad: varias capas independientes, ninguna de confianza total.
- Coste y reproducibilidad del gate: el red team debe poder correr en CI sin gastar API ni depender de la red.
- No sesgo de auto-aprobación en el clasificador (Spec 04): modelo distinto al del agente.
- Mínimo privilegio: que el peor resultado de un secuestro sea un dossier incorrecto, nunca una acción destructiva.
- Mapeo a OWASP LLM Top 10 (Spec 09).

## Decisión

Cuatro capas, cada una con una responsabilidad y un payload de red team que la ejercita:

- **L1 · Delimitadores** (`guardrails/injection.py`): el contenido de tools se envuelve en `<<UNTRUSTED_TOOL_CONTENT>> … <<END_UNTRUSTED_TOOL_CONTENT>>` antes de entrar al contexto, sanitizando cualquier intento de falsificar la frontera o un turno (`System:`/`User:`). Cableado en `agent/loop.py` al construir los `tool_result`.
- **L2 · System prompt** (`prompts/system_prompt_v1.md`): sección explícita que marca el contenido de tools como datos, no instrucciones, y prohíbe obedecer órdenes embebidas, revelar el prompt, cambiar de tarea, emitir veredictos o actuar fuera del research.
- **L3 · Clasificador de output** (`guardrails/classifier.py`): pre-filtro determinista (`heuristic_scan`, regex sin coste) + backstop semántico con **Haiku 4.5**, cliente dedicado con su propio timeout. El loop descarta el dossier (`terminated_by="guardrail_blocked"`) si no pasa. Degrada con elegancia: sin API key corre en modo solo-heurístico; ante error del clasificador no bloquea el agente si la heurística ya pasó.
- **L4 · Mínimo privilegio**: las tools son de solo lectura; ninguna capacidad con efectos secundarios (ADR-006, ADR-009, ADR-011). Un payload que exige `send_email`/`delete`/`http_post` no tiene tool que abusar.

**Gate del red team determinista y offline como canónico.** El runner (`app.redteam.run`) ejercita cada capa sin llamar al modelo: es gratis, reproducible y gateable en CI (`--ci`, exit 1 si bloqueo < umbral). El umbral es **PASS ≥ 90%** (`runner.THRESHOLD`). El backstop semántico de Haiku (L3b) se valida aparte en **modo live** contra el agente desplegado, con evidencia en las trazas de Langfuse (span `output_guardrail`).

## Consecuencias

### Positivas

- Cuatro capas independientes; un bypass de una no compromete las demás.
- Gate de seguridad barato y reproducible en CI; el red team no gasta API.
- Clasificador con modelo distinto (Haiku): sin sesgo de auto-aprobación.
- Checklist como código (`payloads.py`) sincronizada con el documento humano por test.

### Negativas

- El gate determinista no prueba el comportamiento real del modelo ante L2/L3b; eso requiere el modo live (más caro, no en cada CI).
- La heurística L3 es de patrones: cubre lo obvio, no lo semántico; depende del backstop Haiku para el resto.
- El clasificador añade una llamada Haiku por dossier exitoso (coste y latencia pequeños).

## Alternativas descartadas

- **Una sola capa** (solo system prompt, o solo clasificador): descartada por frágil; cualquier bypass único deja pasar el ataque.
- **Red team solo en modo live**: descartado como gate canónico por coste y falta de reproducibilidad en CI; se mantiene como verificación complementaria.
- **Clasificador con el mismo modelo del agente** (Sonnet): descartado por sesgo de auto-aprobación (Spec 04).

## Mapeo OWASP LLM Top 10

- LLM01 Prompt Injection → L1, L2.
- LLM02 Sensitive Information Disclosure (fuga de prompt / exfiltración) → L2, L3.
- LLM05 Improper Output Handling (veredicto fuera de schema) → L3.
- LLM06 Excessive Agency → L4.
- LLM09 Misinformation (relleno fabricado) → L3.
