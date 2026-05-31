# Spec 05 · Output estructurado

**Estado:** pre-construida (se implementa en Fase 2, block-D)
**Fase:** 2 · Loop + datos + output (block-D)
**Dependencias:** Spec 01 (schema del Dossier), Spec 03 (loop), ADR-006 (submit-dossier-tool)

## Goal

Cerrar el loop con la tool `submit_dossier` como señal de fin, validar el dossier con Pydantic antes de devolverlo, garantizar citas verificables con `source_id` y versionar el schema de forma semántica.

## User story

> Como consumidor del agente, quiero que el agente termine llamando a una tool de submit cuyo input es el dossier completo, que el cliente valide ese dossier antes de devolverlo y que cada hecho cite una fuente que realmente vino de una tool ejecutada.

## Outline de approach

- [ ] `submit_dossier(...)` con el schema de `CompanyDossier` en `input_schema`. El cliente intercepta la llamada como señal de fin del loop.
- [ ] Validación con Pydantic del input de `submit_dossier` antes de devolver al cliente.
- [ ] Citas verificables: cada `Fact` y `NewsItem` referencia un `source_id` que resuelve a un `Source` real de la lista `sources`; el frontend resuelve `source_id` a la URL. `market_data` no lleva `source_id`: lleva `source` ("Yahoo Finance") y `as_of`.
- [ ] Validación cruzada: cada `source_id` citado corresponde a una fuente que vino de una tool ejecutada en esta ejecución (evita URLs alucinadas). Un `Fact` derivado (`basis: "computed"`) no cita URL: su procedencia resuelve a datos ya presentes en el dossier (p. ej. `market_data`), de modo que el valor sea reproducible.
- [ ] Reintento ante fallo de schema: un reintento con instrucción explícita del error; si persiste, error al usuario con el output parcial.
- [ ] Versión semántica del schema (`schema_version`): cambios versionados como una API pública, con deprecation policy.
- [ ] Documentar la elección de submit tool frente a parseo de texto y structured output nativo (GA) como decisión: se elige `submit_dossier` por ajuste al patrón de tool use y señal de fin del loop (ver ADR-006).

## Acceptance criteria

- El loop termina cuando el modelo llama a `submit_dossier`; el texto plano no se acepta como output final.
- El input de `submit_dossier` se valida con Pydantic antes de devolverse al cliente.
- Un dossier con un `source_id` que no corresponde a ninguna tool ejecutada falla la validación.
- Un dossier que no cumple el schema dispara un reintento con el error específico.
- El dossier devuelto incluye `schema_version`.
- Tests cubren el camino feliz, el fallo de schema con reintento y la cita huérfana.

## Riesgos

- Cambiar el `description` de `submit_dossier` hace que el modelo deje de invocarla bien. Iterar con el set de evaluación.
- Citas sin validación de URL permiten que el modelo alucine fuentes. Mitigar con la validación cruzada `source_id` contra tools ejecutadas.
- Cambiar el schema sin coordinar con consumidores produce rotura silenciosa. Mitigar con versión semántica.

## Preguntas abiertas

- Structured output nativo del SDK es GA; queda como alternativa para forzar el schema del texto final si se prefiere no modelar el cierre como tool (ver ADR-006).
- Política de campos obligatorios vs opcionales en el schema final. Cerrar junto a Spec 01.
