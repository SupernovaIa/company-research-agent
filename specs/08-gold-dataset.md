# Spec 08 · Set de evaluación del agente

**Estado:** pre-construida (se implementa en Fase 5, block-H)
**Fase:** 5 · Evals + CI (block-H)
**Dependencias:** Spec 01 (schema del Dossier), Spec 02 (tools)

## Goal

Construir el set de evaluación del agente en `evals/gold.jsonl`: un set de comportamiento de ~12-15 empresas con sus propiedades y trayectoria esperadas, anotaciones de tool calls esperadas y cobertura de los casos relevantes. No es un dataset de respuestas textuales exactas, es un set de comportamiento.

## User story

> Como operador del agente, quiero un set de comportamiento con empresas variadas, cada una con las propiedades esperadas de su dossier y sus tool calls esperadas, para medir tool use accuracy y task completion rate de forma reproducible en CI.

## Outline de approach

- [ ] Formato `evals/gold.jsonl`: una línea por empresa con entrada, propiedades esperadas del dossier (por estructura y comportamiento, no por contenido textual exacto) y tool calls esperadas.
- [ ] Entradas: tickers y nombres de empresa.
- [ ] Propiedades esperadas por estructura: campos que el dossier debe poblar y reglas que debe cumplir (cada `Fact`/`NewsItem` cita un `Source` real, `market_data` con `as_of` y `source`, lo desconocido en `null`), no el texto exacto (que cambia con el tiempo).
- [ ] Anotaciones de tool calls esperadas: por cada empresa, qué tools debería llamar el modelo (ej: `get_market_data` y `web_search`; `web_fetch` solo para profundizar en una fuente concreta; code execution para métricas derivadas cuando aporten).
- [ ] Cobertura: empresas cotizadas USA, empresas europeas, empresas con datos de mercado parciales (algún campo en `null`), tickers inexistentes (caso de error esperado).
- [ ] Tamaño objetivo: ~12-15 empresas. Es un set de comportamiento, no un dataset masivo de respuestas.
- [ ] La anotación de las ~12-15 empresas se reparte en lotes con el subagente `gold-annotator`; el agente principal concatena los bloques JSONL. La **firma humana es el entregable**: tú verificas que las tool calls esperadas y las propiedades de cada empresa son correctas, igual que firmas el schema del dossier. El `gold-annotator` produce el borrador; lo que vale es tu verificación, no que el agente lo revisó.
- [ ] Changelog del set: cada incidente real que no estaba cubierto se añade tras resolverlo (el set crece con los modos de fallo conocidos).

## Acceptance criteria

- `evals/gold.jsonl` contiene ~12-15 empresas válidas, una por línea.
- Cada entrada tiene la empresa, las propiedades esperadas del dossier por estructura y las tool calls esperadas.
- La cobertura incluye las cuatro categorías: cotizadas USA, europeas, con datos parciales, tickers inexistentes.
- El set es consumible por el workflow de evals en CI sin transformación adicional.
- Los lotes anotados por `gold-annotator` pasan tu firma humana antes de integrarse; no se da por bueno un lote solo porque el agente lo concatenó.

## Riesgos

- Propiedades por contenido textual exacto se rompen al cambiar los datos reales. Definir por estructura y comportamiento.
- Anotación sesgada (solo empresas que salen bien) infla las métricas. Incluir tickers inexistentes y casos de datos parciales.
- Cambio del schema del dossier invalida entradas. Versionar el set contra la versión del schema.

## Preguntas abiertas

- Reparto entre anotación humana y LLM-as-judge. Definir junto a Spec 06.
- Tamaño de lote por invocación de `gold-annotator`. Validar en block-H.
