# ADR-003: Búsqueda web server-side vs client-side

**Estado:** propuesto (se firma en Fase 1, block-B; se implementa en Fase 2, block-C)
**Fecha:** <YYYY-MM-DD>
**Tags:** tools, proveedores, busqueda-web

## Contexto y problema

El agente necesita buscar en la web para construir el perfil de la empresa y encontrar noticias recientes. El SDK de Anthropic distingue entre tools que ejecuta Anthropic en su infraestructura (entre ellas `web_search`) y tools que ejecutas en tu backend. La búsqueda web puede resolverse de las dos formas, y la elección afecta al código de orquestación, al control sobre las fuentes y al acoplamiento con el proveedor.

## Drivers de la decisión

- Time-to-MVP: cuanto menos código de orquestación, antes funciona el agente.
- Citas: el dossier exige cada hecho con su fuente.
- Control de fuentes: posibilidad de filtrar por dominio o aplicar ranking propio más adelante.
- Acoplamiento: dependencia del proveedor frente a intercambiabilidad.

## Opciones consideradas

- A. `web_search` server-side de Anthropic (`web_search_20260209`). Cero código de tool, citas automáticas, coste incluido por uso.
- B. Tavily como client tool: control de fuentes, filtros por dominio, intercambiable entre proveedores.
- C. Una API de búsqueda dedicada (Brave Search, SerpAPI) como client tool, con extracción de página aparte.

## Decisión

Opción A para el arranque. Se empieza con `web_search` server-side de Anthropic por su time-to-MVP: cero infraestructura, citas automáticas y sin gestión de claves extra. La versión de la tool va anclada al modelo y se documenta (`web_search_20260209`).

Migración a Tavily client-side (opción B) cuando aparezca una de estas necesidades: filtrado por dominio dinámico, ranking propio o cambio de proveedor de búsqueda. La migración se decide con datos del set de evaluación, no de forma anticipada.

## Consecuencias

### Positivas

- Arranque rápido: el agente busca sin que escribas una sola línea de tool de búsqueda.
- Citas automáticas que alimentan el campo de fuentes del dossier. En el cierre del dossier, cada cita de `web_search` (los bloques `web_search_tool_result` con url y título) se transforma a un `Source(id, url, title, accessed_at)` del schema; ahí se juega la trazabilidad de cada hecho.
- Una credencial menos que rotar durante el desarrollo.
- Coste acotado con `max_uses` en la definición de la tool: como `web_search` server-side se factura por uso, el tope de usos por ejecución entra en el control de coste (ver ADR-007).

### Negativas

- Acoplamiento con Anthropic para la búsqueda web. El control de fuentes es limitado.
- El comportamiento server-side es opaco: no ves la request a la API de búsqueda; las trazas las da Anthropic. El debugging fino requiere migrar a client tool.

## Alternativas descartadas

- Tavily client-side desde el primer día: descartado para el arranque porque añade código y una dependencia antes de que haya un requisito de control que lo justifique. Reservado como migración.
- API de búsqueda dedicada (Brave, SerpAPI) como buscador: descartada por coste y complejidad superiores para el flujo de búsqueda en un repo de referencia. La extracción de una URL concreta la cubre `web_fetch` (ver ADR-005).
