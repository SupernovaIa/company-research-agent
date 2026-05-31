# Spec 01 · Schema del Dossier

**Estado:** aceptada (firmada en block-B 2026-05-31)
**Fase:** 1 · Infra + diseño
**Dependencias:** ADR del agente (alcance, tools elegidas, proveedor de datos de mercado)

## Goal

Tener el contrato del output del agente fijado como modelo Pydantic v2 antes de escribir cualquier tool: el `CompanyDossier` con sus sub-schemas, citas obligatorias por hecho, datos de mercado estructurados y metadatos operativos de la ejecución.

## User story

> Como consumidor del agente (analista o sistema downstream), quiero recibir siempre un dossier con la misma estructura, con datos de mercado precisos a fecha conocida, cada hecho cualitativo citado a una fuente verificable, y los metadatos de coste y turnos de la ejecución, para poder validar el resultado sin parsear prosa.

## Outline de approach

- [ ] `CompanyDossier` (Pydantic v2) con campos: `schema_version`, `company`, `market_data`, `business_overview`, `key_facts`, `recent_news`, `sources`, `generated_at`, `run`.
- [ ] `Company(name, ticker, exchange, sector?, website?)`.
- [ ] `MarketData(price, currency, change_pct, market_cap, pe_ratio, forward_pe, eps, dividend_yield?, week52_high?, week52_low?, as_of, source)`. `source` es la cadena del proveedor ("Yahoo Finance"); `as_of` el timestamp del dato. Campos sin dato disponible van `null`, no se inventan.
- [ ] `business_overview: str` cualitativo, sintetizado de la web.
- [ ] `Fact(text, source_id?, basis?)` para `key_facts`; `NewsItem(headline, date, summary, source_id)` para `recent_news`. Un `Fact` recuperado de la web cita un `source_id`; un `Fact` derivado de un cálculo (code execution) lleva `basis` (p. ej. `"computed"`) y referencia el dato del que se deriva, normalmente `market_data`, en lugar de un `source_id` a una URL. `recent_news` siempre cita `source_id`.
- [ ] `Source(id, url, title, accessed_at)`: cada `source_id` referenciado debe existir en `sources`.
- [ ] `run(model, cost_usd, turns)`: metadatos operativos de la ejecución.
- [ ] Validador cruzado: todo `source_id` citado en un `Fact` o `NewsItem` resuelve a un `Source` presente en la lista. Un `Fact` lleva exactamente uno de los dos: `source_id` (recuperado de la web) o `basis` (derivado de un cálculo). Un `Fact` con `basis: "computed"` no necesita `source_id`, pero su procedencia debe resolver a datos presentes en el dossier (p. ej. los campos de `market_data` usados), de modo que el valor sea reproducible y no inventado.
- [ ] Contraste de disciplinas, tres tipos de verdad: `market_data` viene de una fuente estructurada (no lleva `source_id`, lleva `source` + `as_of`); `key_facts` y `recent_news` recuperados de la web son prosa citada (llevan `source_id`); los hechos derivados de un cálculo llevan `basis` y se reproducen desde datos ya presentes en el dossier.
- [ ] `schema_version` con versión semántica como campo del dossier.
- [ ] Serialización JSON estable para el frontend y para el set de evaluación.

## Acceptance criteria

- `CompanyDossier.model_validate(payload)` acepta un dossier completo de empresa cotizada USA (AAPL) y de empresa cotizada europea.
- Un dossier con un `source_id` huérfano (citado en un `Fact`/`NewsItem` pero no listado en `sources`) falla la validación.
- Un `Fact` derivado (`basis: "computed"`) sin `source_id` valida si su procedencia resuelve a datos presentes en el dossier; si referencia datos ausentes, falla.
- Un dossier con `market_data` parcial (p. ej. `forward_pe` y `dividend_yield` en `null`) pasa: los campos opcionales aceptan ausencia de dato.
- `market_data.as_of` y `market_data.source` están presentes en toda salida con datos de mercado.
- Los metadatos operativos (`run.model`, `run.cost_usd`, `run.turns`, `generated_at`) están presentes en toda salida.
- Tests unitarios del schema pasan con ejemplos válidos e inválidos.

## Riesgos

- Schema demasiado rígido rechaza empresas con datos parciales legítimos. Mitigar con campos opcionales en `market_data` y en los bloques cualitativos.
- Cambiar el schema rompe consumidores y el set de evaluación. Mitigar con `schema_version` y deprecation policy.

## Preguntas abiertas

- Si se persisten dossiers, qué subconjunto de metadatos se indexa. Documentar en ADR si llega el caso.
