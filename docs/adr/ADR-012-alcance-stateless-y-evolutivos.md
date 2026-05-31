# ADR-012: Alcance stateless del agente y evolutivos de producto

**Estado:** aceptado (firmado en block-B 2026-05-31)
**Fecha:** 2026-05-31
**Tags:** arquitectura, alcance, diseño-agente

## Contexto y problema

El agente recibe un ticker o nombre de empresa y devuelve un dossier. Queda por fijar qué responsabilidades entran en el sistema y cuáles quedan fuera. Tres capacidades de producto aparecen como candidatas naturales: una interfaz de usuario para consumir el dossier, un disparador periódico que re-investigue una lista de empresas, y una capa de almacenamiento que guarde dossiers y permita actualizarlos o compararlos en el tiempo. La decisión define la frontera del sistema y su coste de mantenimiento.

## Drivers de la decisión

- La tarea del agente es producir un dossier reproducible y citable a fecha de hoy. Cada dato lleva su marca temporal (`market_data.as_of`, `generated_at`).
- Un dossier es un snapshot temporal: el de hoy y el de la semana pasada describen hechos distintos. Actualizar en sitio borraría información válida.
- Cada ejecución gasta dinero real de API. Un disparador automático sin presupuesto por ejecución es una vía directa de gasto descontrolado.
- El sistema arranca single-user y sin autenticación.
- El output es JSON estructurado con `schema_version`, pensado para que un consumidor downstream (frontend, almacén) lo lea sin parsear prosa.

## Opciones consideradas

- A. Agente stateless con un único punto de entrada (`POST /research`) que devuelve un dossier por ejecución. UI, scheduling y persistencia quedan fuera del loop, documentados como evolutivos.
- B. Agente con estado: persistencia integrada, deduplicación por empresa y actualización del dossier existente dentro del propio sistema.
- C. Agente con UI y scheduler integrados desde el inicio.

## Decisión

Opción A. El agente es stateless por diseño. Produce un snapshot point-in-time y lo devuelve; no guarda histórico, no deduplica, no programa ejecuciones, no renderiza vista. El contrato de salida (`CompanyDossier` con `schema_version`, `generated_at` y fuentes resolubles) está pensado para alimentar una capa de producto externa.

Tres evolutivos quedan documentados como capa de producto por fuera del loop. Cuando se implemente alguno, vive fuera del agente y consume su output, sin modificar el loop, las tools ni los guardrails:

1. **Interfaz de usuario.** Frontend que renderiza el dossier como vista navegable, con cada hecho enlazado a su fuente, y muestra el stream SSE del loop en vivo. El schema estable y el streaming por turno ya están diseñados para soportarla.
2. **Disparador periódico (scheduler).** Programador que re-ejecuta el research sobre una watchlist de empresas en una cadencia fija. Depende del presupuesto por ejecución (ver ADR-007) para acotar el gasto agregado, y de la capa de persistencia para conservar los resultados.
3. **Persistencia y versionado.** Almacén que guarda cada dossier como una versión fechada de su empresa y permite comparar el snapshot actual con el anterior (diff de precio, de PER, de noticias). El `schema_version` y `generated_at` sostienen el versionado. El modelo de actualización versiona snapshots fechados y los compara entre sí; la actualización en sitio destruiría el snapshot anterior.

Los tres encajan entre sí: el scheduler dispara ejecuciones, la persistencia versiona los resultados, la UI los muestra y los compara. El Postgres del proyecto anterior queda disponible si se aborda la persistencia.

## Consecuencias

### Positivas

- El sistema tiene una sola responsabilidad y una sola frontera: input de empresa, output de dossier. El loop, las tools y los guardrails no cargan con lógica de almacenamiento ni de presentación.
- Cada evolutivo se construye y se prueba de forma independiente sobre un contrato de salida estable, sin tocar el núcleo.
- El coste por ejecución queda acotado y medible (ver ADR-007), condición previa para que un scheduler resulte seguro.

### Negativas

- Dos ejecuciones sobre la misma empresa producen dos dossiers sin relación entre sí. La deduplicación y la comparación quedan delegadas a una capa que todavía no existe.
- Sin persistencia, un dossier vive solo en la respuesta de su ejecución. Reusarlo exige que el consumidor lo guarde.

## Alternativas descartadas

- Opción B (estado integrado): junta la lógica de research con la de almacenamiento y versionado en un mismo sistema. Descartada por acoplar dos responsabilidades con ciclos de cambio distintos. Queda como el evolutivo de persistencia, fuera del loop.
- Opción C (UI y scheduler desde el inicio): adelanta capa de producto antes de tener el núcleo medido y estable. Descartada por sobreingeniería en el arranque. Quedan como evolutivos de UI y de scheduler.
