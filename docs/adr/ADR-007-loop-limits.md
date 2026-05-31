# ADR-007: Límites del loop, tope de turnos y presupuesto

**Estado:** aceptado (firmado en block-B 2026-05-31; topes provisionales implementados en block-C; recalibración definitiva en block-E)
**Fecha:** 2026-05-31
**Tags:** loop, guardrails, coste, presupuesto

## Contexto y problema

El loop de tool use puede divergir. Sin un tope de turnos y sin un presupuesto por ejecución, una ejecución mal arrancada gasta dinero antes de que te enteres. El coste de un agente se mide por ejecución completa, con 5 a 20 turnos y contexto creciente, no por query. Hay que fijar dos límites duros en el cliente y un criterio para calibrarlos.

## Drivers de la decisión

- Cortar la divergencia del loop antes de que gaste de más.
- Cubrir las tareas legítimas que necesitan varios turnos sin recortarlas.
- Calibrar con datos reales, no a ojo.
- Coste por ejecución como métrica de producto desde el primer día.

## Opciones consideradas

- A. Tope de turnos alto (25-30) y presupuesto alto (cerca de 1 dólar): cubre tareas complejas, con riesgo de divergencia y de ejecuciones caras.
- B. Tope de turnos bajo (8-12) y presupuesto bajo (cerca de 0,20 dólares): respuestas rápidas y predecibles, con riesgo de cortar tareas válidas.
- C. Tope y presupuesto calibrados con la distribución real de turnos y de coste del set de evaluación.

## Decisión

Opción C. Turnos típicos esperados de 8 a 12; tope blando (soft limit) en torno a 15 y tope duro (hard limit) entre 20 y 25; presupuesto por ejecución de 0,30 a 0,80 dólares como rango de arranque con Claude Sonnet 4.6. Estos números son provisionales: se fijan al construir el loop (block-E) con valores de arranque y se recalibran contra la distribución real del set de evaluación cuando exista (block-H e iteración). El tope de turnos se sitúa un poco por encima del p95 de turnos por tarea, y el presupuesto sobre el p95 de coste por ejecución más un margen.

**Nota block-C (2026-05-31):** los topes provisionales (HARD=20, SOFT=15) se implementan ya en block-C para cumplir el criterio de aceptación de Spec 03 y poder hacer una corrida real controlada. Se leen de `AGENT_MAX_TURNS` en el `.env` para poder ajustarlos sin tocar el código. La recalibración definitiva basada en datos del set de evaluación queda pendiente para block-E, donde los valores de arranque se sustituyen por el p95 + margen observado. Spec 03 y este ADR no coincidían en la fase de implementación de los topes: Spec 03 los incluye como criterio de block-C, este ADR los situaba en block-E. Resolución: block-C añade los topes provisionales y configura el mecanismo; block-E recalibra los números.

Mecánica del corte: un contador en el cliente cuenta turnos y suma tokens convertidos a dólares con el rate card del modelo. Al llegar a cualquiera de los dos límites, se fuerza la respuesta final con un mensaje al modelo (ya no puedes llamar más tools, redacta el dossier con lo que tienes) o se devuelve error al usuario.

Modelo: Sonnet 4.6 mantiene el coste por ejecución en un rango bajo (orientativo 0,20 a 0,40 dólares con 8 a 12 turnos; confirmar con el rate card vigente al construir). Opus 4.8 sube el coste por su rate card más alto. El cambio a Opus se trata como decisión de modelo aparte, justificada con números (ver ADR-010 para la capa de loop y el bucle de iteración para el cambio de modelo).

## Consecuencias

### Positivas

- Divergencia del loop acotada: ninguna ejecución gasta sin límite.
- Límites basados en datos reales, no en intuición.
- Coste por ejecución medible desde el arranque, como métrica de producto.

### Negativas

- El corte por límite puede recortar una tarea compleja legítima que necesitaba más turnos o más presupuesto.
- Calibrar requiere un set de evaluación con distribución representativa antes de fijar los números.

## Alternativas descartadas

- Tope y presupuesto altos fijos (opción A): descartados por exponer el sistema a ejecuciones caras descontroladas sin un criterio que los respalde.
- Tope y presupuesto bajos fijos (opción B): descartados por cortar tareas válidas sin medir antes la distribución real.
