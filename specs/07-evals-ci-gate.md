# Spec 07 · Evals en CI como gate de PR

**Estado:** aceptada (implementada en block-H, 2026-06-01)
**Fase:** 5 · Evals + CI (block-H)
**Dependencias:** Spec 08 (set de evaluación), Spec 06 (métricas)

## Goal

Tener un workflow de GitHub Actions que corra el set de evaluación contra el agente en cada PR y aplique un gate por métricas: si caen por debajo del umbral, el PR no se mergea.

## User story

> Como operador del agente, quiero que cada PR ejecute el dataset de evaluación y que las métricas actúen como gate, para que ninguna regresión de tool use accuracy, completion rate o coste llegue a producción sin que alguien lo decida explícitamente.

## Outline de approach

- [ ] Workflow de GitHub Actions que corre el set de evaluación (`evals/gold.jsonl`, ~12-15 empresas) contra el agente en cada PR.
- [ ] Cálculo de métricas sobre el set: task completion rate, tool use accuracy, coste medio por ejecución.
- [ ] Gate por umbrales: task completion rate ≥ 0.85, tool use accuracy ≥ 0.80, coste medio ≤ presupuesto.
- [ ] Si alguna métrica cae por debajo del umbral, el job falla y el PR no se mergea.
- [ ] Reporte de métricas comentado en el PR para revisión (cada cambio del agente con sus números).
- [ ] Reaplicar el mismo patrón de CI del chatbot RAG (mismo enfoque, no copia literal); el cambio son las métricas evaluadas.
- [ ] Control de coste del propio job: el set de evaluación gasta tokens reales; con ~12-15 empresas el coste es acotado, y el caching del system prompt + tools lo baja más.
- [ ] Determinismo del gate: las llamadas a las fuentes externas se sirven desde fixtures grabados (datos de mercado de `get_market_data`, y resultados de `web_search`/`web_fetch`), para que un fallo o rate limit de Yahoo Finance o de la web no tumbe el gate y para acotar el coste (ver ADR-004). El modelo sí se llama en vivo (es lo que se mide: qué tool elige); su no determinismo lo absorben los umbrales por métrica. La evaluación de comportamiento end-to-end totalmente en vivo se reserva a un job programado, no al gate de cada PR.

## Acceptance criteria

- Un PR con el agente sano pasa el gate (las tres métricas por encima de su umbral).
- Un PR que degrada tool use accuracy por debajo de 0.80 falla el job y bloquea el merge.
- Un PR que sube el coste medio por encima del presupuesto falla el gate.
- El reporte de métricas aparece como comentario o resumen del PR.
- El workflow corre sobre `evals/gold.jsonl` sin tocar producción.
- El gate usa fixtures de las fuentes externas (datos de mercado y web), de modo que un fallo de yfinance o de la web no lo tumba; el modelo se llama en vivo.

## Riesgos

- El set de evaluación gasta tokens reales en cada PR. Mitigar con su tamaño acotado (~12-15) y el caching del system prompt + tools.
- Umbrales mal calibrados bloquean PRs sanos o dejan pasar regresiones. Calibrar con la distribución observada.
- Cambio del schema del dossier invalida entradas del set. Revisar el set cuando cambie el schema.

## Preguntas abiertas

- Umbral de coste medio: fijar contra el presupuesto por ejecución acordado en la Fase 3 (block-E).
- Frecuencia de ejecución: en cada push vs solo en PR a `main`. Decidir según minutos de Actions disponibles.
