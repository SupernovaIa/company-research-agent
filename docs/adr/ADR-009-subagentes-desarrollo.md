# ADR-009: Subagentes de Claude Code como herramienta de desarrollo

**Estado:** aceptado (firmado en block-B 2026-05-31; los subagentes aparecen en block-F y block-H)
**Fecha:** 2026-05-31
**Tags:** subagentes, desarrollo, claude-code, paralelismo

## Contexto y problema

Durante la construcción del agente de research aparecen tareas repetibles, acotadas y paralelizables. La pregunta es si delegarlas a subagentes de Claude Code como herramienta de desarrollo, o si el agente principal de Claude Code las hace de forma secuencial. Esto trata de cómo se construye el proyecto, no de qué hace el producto: los subagentes son del entorno de desarrollo, el agente de research desplegado sigue siendo un agente único con tools (ver ADR-002).

El proyecto anterior, el chatbot RAG, descartó deliberadamente los subagentes de desarrollo porque no había una tarea que cumpliera los criterios para delegar: el trabajo era mayormente secuencial y sin paralelismo verdadero. Aquí la situación cambia.

## Drivers de la decisión

Los criterios que justifican delegar en un subagente:

- Volumen de contexto irrelevante para el agente principal.
- Paralelismo verdadero entre las unidades de trabajo.
- Especialización repetible.
- Coste de coordinación tolerable.

En este proyecto, esos criterios se cumplen con claridad en dos puntos: la anotación del set de evaluación y el red teaming. La construcción de las tools no entra: con el inventario actual solo hay una client tool de datos custom (`get_market_data`), porque la búsqueda, el fetch y el cálculo son server tools de Anthropic (ver ADR-003, ADR-005, ADR-011). Sin varias tools que construir en paralelo, no hay nada que delegar ahí.

## Opciones consideradas

- A. El agente principal de Claude Code hace todo el trabajo de forma secuencial.
- B. Se definen subagentes de desarrollo para las tareas que cumplen los criterios, y el agente principal hace el resto directo.

## Decisión

Opción B. Se definen dos subagentes de desarrollo, cada uno en la sesión donde aparece su tarea:

- **`gold-annotator`** (block-H): anotar ~12-15 empresas del set de evaluación (por cada una, las tool calls esperadas y las propiedades del dossier objetivo) es trabajo repetitivo y paralelizable por lotes. Cada lote es contexto que el agente principal no necesita cargar; concatena los bloques JSONL al final.
- **`redteam-runner`** (block-F): ejecuta la checklist de prompt injection contra el agente y produce un reporte PASS/FAIL con remediaciones. Tarea acotada, repetible y con output estructurado que aísla la superficie de seguridad del resto de la sesión.

Coordinación: worktrees para escritura paralela, sin memoria compartida entre subagentes (cada uno recibe su spec y devuelve su resultado por mensaje), techo de tres instancias en paralelo (los lotes de anotación), y gate humano sobre cada output antes de integrarse a la rama de la sesión.

## Consecuencias

### Positivas

- La anotación del set de evaluación avanza por lotes sin saturar el contexto del agente principal.
- El red teaming queda aislado, con output estructurado y repetible.

### Negativas

- Coste de coordinación: el agente principal integra los resultados y resuelve colisiones de worktrees.
- Techo de tres subagentes en paralelo. Más allá, el coste de coordinación y de tokens supera el ahorro.
- Cada output de subagente pasa por el mismo gate humano que cualquier código antes de integrarse, lo que añade un paso de revisión.

## Alternativas descartadas

- El agente principal hace todo (opción A): válido y más simple, descartado porque obliga a cargar en un solo contexto el trabajo repetitivo de anotación y red teaming, que sí cumplen los criterios para delegar. Es la opción que tomó el chatbot RAG porque allí no había tarea que cumpliera los criterios; aquí sí en anotación y red teaming.

**Lo que no se delega a ningún subagente:** el diseño del schema de tools y del dossier, la elección de proveedores externos, la política de guardrails, el tope de turnos y el presupuesto. Esas decisiones las firma el agente principal bajo tu revisión.
