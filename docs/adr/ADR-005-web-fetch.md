# ADR-005: Extracción de URL con `web_fetch` (server-side)

**Estado:** propuesto (se firma en Fase 1)
**Fecha:** <YYYY-MM-DD>
**Tags:** tools, fetch, web

## Contexto y problema

El agente necesita profundizar en una fuente concreta: un comunicado oficial, un artículo de noticias, una ficha de empresa. El contenido tiene que llegar al modelo limpio y acotado, no como HTML crudo. Ese contenido externo es no confiable: es el vector principal de indirect prompt injection del caso. La elección afecta a la fricción, al coste, a la calidad de extracción y a la superficie de seguridad, entre ella el SSRF.

## Drivers de la decisión

- Fricción mínima: repo de referencia; evitar API keys de pago y operar infra cuando se pueda.
- Contenido limpio y acotado, utilizable por el modelo sin saturar contexto.
- Superficie de seguridad acotada: descargar una URL arbitraria desde tu backend abre SSRF.
- El contenido externo se trata como no confiable desde el diseño.

## Opciones consideradas

- A. `fetch_url` como client tool propia: `httpx` para descargar más `trafilatura` para extraer el contenido principal a texto/markdown. Sin API key y con control total de la sanitización, pero descargar URLs arbitrarias en tu backend es superficie de SSRF que tienes que defender (allowlist, bloqueo de IPs privadas, restricción de esquema, timeouts).
- B. Firecrawl: convierte cualquier URL a Markdown limpio y maneja JavaScript pesado. Plan de pago por créditos.
- C. `web_fetch` server tool de Anthropic (`web_fetch_20260209`): recupera el contenido de una URL en la infraestructura de Anthropic, sin infra propia ni API key extra, con dominios permitidos gestionados y sin exponer tu backend a SSRF.

## Decisión

Opción C. `web_fetch` server-side de Anthropic. Recupera el contenido de la URL elegida sin que escribas una tool de fetch ni gestiones credenciales, y la descarga ocurre fuera de tu backend, así que la superficie de SSRF que tendría un fetch propio no aparece. La versión va anclada al modelo y se documenta (`web_fetch_20260209`). Además, `web_fetch` es gratis cuando se usa junto a `web_search` o la code execution tool, que el agente ya usa.

El contenido devuelto sigue siendo externo no confiable: entra en el contexto y es el vector de indirect prompt injection. La defensa se mantiene en las capas de guardrails (delimitadores de contenido externo, system prompt explícito, clasificador de output; ver Spec 04). Mover el fetch a server-side quita la superficie de SSRF, no la de inyección por contenido.

## Consecuencias

### Positivas

- Sin API key ni infra de fetch: el alumno clona y ejecuta.
- Sin superficie de SSRF en tu backend: Anthropic gestiona la red y los dominios permitidos.
- Gratis junto a `web_search` o code execution; el coste queda integrado en la llamada al modelo.

### Negativas

- Acoplamiento con Anthropic para el fetch y comportamiento server-side opaco: ves el resultado, no la request (mismo patrón que `web_search`, ver ADR-003).
- Menos control sobre la extracción y el acotado que con una tool propia.
- El contenido sigue siendo no confiable: la defensa de inyección no desaparece (ver Spec 04).

## Alternativas descartadas

- `fetch_url` propio con `httpx` más `trafilatura` (opción A): control total de la extracción, descartado porque añade superficie de SSRF que defender y código de fetch propio sin ventaja clara frente a `web_fetch`. Queda documentado como la versión que se construye a mano si se quiere enseñar el manejo de contenido externo a nivel del backend y la defensa de SSRF, o si se necesita control fino de extracción.
- Firecrawl (opción B): Markdown limpio y extracción estructurada, descartado por la fricción de API key de pago y el coste por créditos en un repo de referencia. Queda como upgrade documentado si la calidad de extracción lo justifica en producción.
