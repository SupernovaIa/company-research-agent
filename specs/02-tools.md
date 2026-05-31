# Spec 02 · Tools del agente

**Estado:** aceptada (contrato firmado en block-B 2026-05-31: inventario de TOOLS declarado; implementación de la lógica en Fase 2 y Fase 3)
**Fase:** 2 (`get_market_data`, `web_search`, `web_fetch`, code execution, `submit_dossier`); la defensa del contenido de `web_fetch` y el acotado de code execution en Fase 3
**Dependencias:** Spec 01 (schema del Dossier), ADR-003 (web_search server-side), ADR-004 (yfinance), ADR-005 (web_fetch server-side), ADR-011 (code execution)

## Goal

Disponer el conjunto de tools del agente con arquetipos distintos a propósito: una client tool de datos propia (`get_market_data`, con su schema Pydantic, su `description` escrita para el modelo, errores como dato y salida acotada), las server tools de Anthropic que se declaran y resuelve el proveedor (`web_search`, `web_fetch`, code execution) y la client tool de cierre `submit_dossier`. El contraste es deliberado: dato estructurado propio, recuperación y cálculo server-side, y contrato de salida.

## User story

> Como operador del agente, quiero un conjunto de tools de solo lectura con inputs validados y outputs pequeños y citables, para que el modelo elija bien qué llamar y para que un fallo de proveedor devuelva un error recuperable en lugar de romper el loop.

## Outline de approach

- [ ] `get_market_data(ticker)`: datos de mercado vía `yfinance` (sin API key). Devuelve un objeto homogéneo (`price`, `currency`, `change_pct`, `market_cap`, `pe_ratio`, `forward_pe`, `eps`, `dividend_yield`, `week52_high`, `week52_low`, `as_of`, `source`), no el dump completo de `Ticker.info`. Campos sin dato → `null`.
- [ ] `web_search(query)`: búsqueda web con la tool `web_search` **server-side de Anthropic**. No se implementa infra de búsqueda; se declara y se deja que el modelo la use. Recuperación difusa para perfil de negocio y noticias.
- [ ] `web_fetch(url)`: recuperación del contenido de una URL concreta con la tool `web_fetch` **server-side de Anthropic**, para profundizar en una fuente. El contenido externo se trata como no confiable (ver Spec 04, indirect prompt injection); el fetch server-side evita la superficie de SSRF de un fetch propio (ver ADR-005).
- [ ] code execution: cálculo determinista de métricas derivadas con la **code execution tool server-side de Anthropic**. El modelo no computa a mano; ejecuta sobre números que ya tiene en contexto. El acotado de privilegio se trata en Spec 04 (ver ADR-011).
- [ ] `submit_dossier(...)`: tool de cierre con el schema de `CompanyDossier` en `input_schema`; el cliente la intercepta como señal de fin (detalle en Spec 05).
- [ ] Anatomía de una **client tool** (`get_market_data`, `submit_dossier`): `name`, `description` (escrita para el modelo, indica qué hace y cuándo usarla), `input_schema` (JSON Schema con `required` y `description` por campo), implementación Python que recibe inputs validados. Las **server tools** (`web_search`, `web_fetch`, code execution) se declaran por tipo y versión; las resuelve Anthropic, sin implementación propia.
- [ ] Validación de inputs con Pydantic antes de ejecutar: el modelo puede alucinar parámetros mal tipados (p. ej. un ticker inexistente).
- [ ] Errores como dato: ante fallo, devolver `{"error": "...", "recoverable": bool}` en el `tool_result`, nunca lanzar excepción que rompa el loop. Un ticker inválido o un fallo de `yfinance` es un error recuperable.
- [ ] Filtrado de campos relevantes dentro de la tool para no saturar el contexto (el modelo paga cada token del output).
- [ ] Registro de tools al cliente Anthropic en formato del SDK (`tools=[...]`), mezclando las server tools (`web_search`, `web_fetch`, code execution) y las client tools (`get_market_data`, `submit_dossier`).

## Acceptance criteria

- `get_market_data("AAPL")` devuelve un objeto compacto validado contra `MarketData`, con `as_of` y `source` poblados.
- `get_market_data("ZZZZ")` (ticker inexistente) devuelve `{"error": ..., "recoverable": true}`, no una excepción.
- `web_search` con una query genérica deja que el modelo recupere resultados server-side sin que el cliente implemente búsqueda.
- `web_fetch` trae el contenido de una URL resuelto server-side y entra al contexto como contenido no confiable; una URL inaccesible la reporta Anthropic en la respuesta.
- Un input mal tipado pasado a una client tool produce un error recuperable, no una excepción no controlada.
- `get_market_data` tiene test unitario con el proveedor mockeado; `submit_dossier` tiene test de validación de schema.
- El `description` de cada tool está versionado como fichero en `prompts/`.

## Riesgos

- `description` poco clara hace que el modelo elija mal la tool. Mitigar iterando sobre el set de evaluación.
- Output de tool demasiado grande satura el contexto en pocos turnos. Mitigar filtrando y acotando dentro de la tool.
- El contenido de `web_fetch` es superficie de indirect prompt injection al entrar en contexto. Mitigar con las capas de la Fase 3 (Spec 04). La code execution tool, al ejecutar Python arbitrario, no acota "solo cálculo descriptivo" en el límite de la tool: se acota con system prompt y clasificador de output (Spec 04, ADR-011).
- `yfinance` es no oficial: puede romper o limitar. Mitigar con errores como dato y el manejo de fallo del proveedor; documentado en ADR-004.

## Preguntas abiertas

- Granularidad de tools: una por tipo de información vs tools de grano fino. Validar con turnos por ejecución en la Fase 2.
- Uso real de la code execution tool: confirmar con el set de evaluación que el modelo la usa de forma significativa; si casi no se llama, reconsiderarla para no penalizar la tool use accuracy (ver ADR-011).
