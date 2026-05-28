# Work Plan - WP-2026-161

## Metadata
- **ID:** WP-2026-161
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Ticket Quality & Improvement Loop - fase documental
- **Asignado a:** Builder

## Objetivo
Definir el contrato humano que hara que los tickets futuros sean mas claros, verificables y consistentes antes de activar al Builder. Esta fase establece el catalogo de defectos de ticket, la checklist de calidad y la regla de TP Check en el audit.

## Contexto
- El sistema ya aprende de los defectos de codigo y de review, pero no de los defectos de redaccion de tickets.
- En la sesion anterior aparecieron ambiguedades reales: secuencia contradictoria, criterios no verificables, paridad PLAN/AUDIT y lenguaje blando.
- Las guias de prompting que revisamos refuerzan que las instrucciones deben ser directas, con razon explicita y ejemplos claros.
- Esta fase es documental a proposito: primero se fija el contrato, luego se automatiza si hace falta en un ticket posterior.

## Decision Arquitectonica
- Opcion elegida: formalizar primero la Fase A documental sin codigo nuevo.
- El catalogo TP sera la fuente compartida para Manager y Builder.
- La checklist de calidad del plan sera verificable y apta para prompts.
- El `AUDIT_WP` ganara una seccion obligatoria `## TP Check` para que el Manager decida sin inferir.
- Las observaciones iniciales se derivaran de WP-2026-160 para anclar el sistema en evidencia real.

## Non-goals
- No crear `validate_ticket_prose.py` en este ticket.
- No añadir metricas ni F1-score.
- No tocar `agent_controller.py`.
- No crear una skill separada de validacion automatica.
- No inyectar lecciones de observaciones en prompts de forma programatica.

## Fases

### Fase 1: catalogo de anti-patrones de ticket
- **Tipo:** TAREA AGENTE
- **Archivos:** `skills/_shared/ticket-anti-patterns.md`
- **Accion:** Crear
- **Descripcion:** Definir al menos cinco TP reales y accionables para tickets: contradiccion secuencial, criterio no verificable, deriva de ambito implicita, semantica blanda y paridad PLAN/AUDIT rota. Cada entrada debe incluir descripcion, por que rompe al Builder/Manager, senal de deteccion y ejemplo malo/bueno.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El archivo existe, contiene los cinco TP y cada TP incluye `WHY`, senal de deteccion y ejemplo `NO/SI` apto para prompt injection.
- **Si falla:** Reducir el catalogo a los TPs con evidencia mas clara y completar los restantes en un ticket siguiente.

### Fase 2: checklist de calidad y TP Check en la skill del Manager
- **Tipo:** TAREA AGENTE
- **Archivos:** `skills/man-create-work-plan/references/plan-quality-checklist.md`, `skills/man-create-work-plan/SKILL.md`
- **Accion:** Modificar
- **Descripcion:** Crear una checklist de plan con preguntas verificables y actualizar la skill del Manager para exigir una seccion `## TP Check` en el `AUDIT_WP-XXXX.md`. La skill debe referenciar el catalogo TP compartido y dejar claro que la aprobacion requiere evidencia literal por check.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** `SKILL.md` referencia la checklist y el catalogo TP, y especifica que el `AUDIT_WP` debe incluir `## TP Check` con evidencia verificable.
- **Si falla:** Mantener la checklist en un fichero separado y reducir el texto del skill a una referencia minimalista.

### Fase 3: observaciones de calidad de ticket ancladas en WP-2026-160
- **Tipo:** TAREA AGENTE
- **Archivos:** `.agent/runtime/memory/observations.jsonl`
- **Accion:** Anadir
- **Descripcion:** Registrar tres observaciones manuales derivadas de WP-2026-160 para los defectos de ticket detectados en la sesion: contradiccion secuencial, criterio no verificable y paridad PLAN/AUDIT rota. Las observaciones deben tener `topic`, `signal`, `source`, `applies_to`, `confidence` y `domain` coherentes con el esquema canonico.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El archivo de observaciones incorpora tres entradas nuevas y `scripts/validate_observations.py` las acepta sin romper el contrato.
- **Si falla:** Guardar las observaciones en memoria persistente y mover la normalizacion de campos a un ajuste posterior.

## Files Likely Touched
- `skills/_shared/ticket-anti-patterns.md`
- `skills/man-create-work-plan/references/plan-quality-checklist.md`
- `skills/man-create-work-plan/SKILL.md`
- `.agent/runtime/memory/observations.jsonl`

## Calidad
- `python scripts/validate_observations.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- El catalogo TP existe y tiene entradas con `WHY`, senal y ejemplo `NO/SI`.
- La checklist del plan contiene preguntas verificables y aptas para prompts.
- La skill del Manager exige `## TP Check` en cada `AUDIT_WP`.
- Las tres observaciones manuales de WP-2026-160 quedan registradas en memoria estructurada.
- La validacion canonica sigue pasando.
