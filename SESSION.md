# SESSION.md — Estado de la sesión actual

> Fichero dinámico. Se actualiza al inicio y al final de cada sesión de construcción. Cualquier agente que abra el repo lee este fichero para saber dónde se quedó el trabajo.

## Sesión actual

**Sesión:** <block-A | block-B | block-C | block-D | block-E | block-F | block-G | block-H | block-I>
**Estado:** <not_started | in_progress | gate_pending | completed | blocked>
**Fecha apertura:** <YYYY-MM-DD HH:MM>
**Última actualización:** <YYYY-MM-DD HH:MM>

## Objetivo de la sesión

<1-2 frases describiendo qué se está construyendo en esta sesión>

## Próxima acción concreta

<Una frase con la siguiente cosa que hay que hacer al retomar>

## Pendientes en esta sesión

- [ ] <tarea pendiente 1>
- [ ] <tarea pendiente 2>
- [ ] <tarea pendiente 3>

## Completado en esta sesión

- [x] <cosa hecha 1>
- [x] <cosa hecha 2>

## Subagentes usados en esta sesión

- <Subagente, qué se le delegó, qué devolvió. Si no se usó ninguno, escribir "Ninguno".>

## Blockers

- <Blocker explícito si lo hay, con qué hace falta para desbloquear. Si no hay blockers, escribir "Ninguno".>

## Decisiones tomadas en esta sesión

- <Decisión 1, con referencia al ADR si aplica>
- <Decisión 2>

## Coste de la sesión

- <Coste aproximado de API gastado en pruebas del agente durante la sesión, si aplica.>

## Notas de handoff

<Contexto que el próximo agente o tú al retomar necesitáis para no perder hilo. Cualquier rareza, atajo aplicado, hipótesis a validar, etc.>

## Comandos útiles ahora

```bash
# <comando que dejé corriendo o que hay que correr al volver>
```

## Gate de revisión

- **Criterio:** <criterio de la sesión del session-prompt>
- **Resultado:** <pendiente | pasa | falla>
- **Comentarios:** <si falla, qué falta>
