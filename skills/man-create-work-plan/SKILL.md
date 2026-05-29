---
name: create-work-plan
version: 2.0.0
description: Skill para que el Manager cree planes de implementaciÃ³n estructurados con fases, tareas y criterios de aceptaciÃ³n
triggers: [/plan, create-plan, /schedule]
author: agent
role: manager
stage: plan
writes_memory: false
quality_gate: false
tags: [core, system]
---

# man-create-work-plan

Skill para crear planes de trabajo detallados que el Builder pueda ejecutar.

## Overview

Cuando el usuario solicita una nueva funcionalidad, el Manager usa esta skill para:
1. Analizar el requerimiento y contexto actual
2. Identificar archivos privados necesarios (Fase 0)
3. Descomponer en fases con tareas ðŸ¤–/ðŸ‘¤
4. Asignar niveles de riesgo (ðŸŸ¢/ðŸŸ¡/ðŸ”´)
5. Definir criterios de aceptaciÃ³n medibles
6. Documentar trade-offs considerados

## Workflow

### Paso 0: Verificar Turno
```bash
python .agent/agent_controller.py
```
Debe indicar `ROL ACTIVO: MANAGER` y acciÃ³n `CREATE_PLAN`.

### Paso 0b: Cargar lecciones de cierre

Antes de analizar el requerimiento, leer si existe:
- `.agent/runtime/memory/closeout_lessons.md`

Usar ese contexto para:
- evitar repetir errores de tickets previos
- reutilizar learnings aprobados como generalizables
- respetar learnings que siguen siendo locales al proyecto

Si el archivo no existe, continuar sin bloquear.

### Paso 1: Analizar Requerimiento

Entender del usuario:
- Â¿QuÃ© problema resuelve?
- Â¿QuÃ© resultado espera?
- Â¿Hay restricciones de tiempo/tecnologÃ­a?

Explorar cÃ³digo existente:
```bash
tree src/ -L 2
find src/ -name "*.py" | head -20
```

### Paso 2: Identificar Fase 0 (Usuario)

Determinar si se necesitan archivos en `privada/`:
- Â¿Necesita credenciales/API keys?
- Â¿ConfiguraciÃ³n personal del usuario?
- Â¿Datos sensibles de empresa?

Si sÃ­ â†’ Fase 0 con tareas ðŸ‘¤ para el usuario

### Paso 3: Crear work_plan.md

Usar `references/plan-template.md` como base.

Estructura obligatoria:
```markdown
# Plan de Trabajo: [TÃ­tulo]

## Metadata
- **ID:** WP-[YYYY]-[NNN]
- **Estado:** ðŸŸ¡ IN_PLANNING
- **deliverable_type:** code | documentation | research | analysis | mixed
- **Creado:** [FECHA]
- **Prioridad:** HIGH/MEDIUM/LOW
- **Asignado a:** Builder

## ðŸŽ¯ Objetivo
[DescripciÃ³n clara en 2-3 lÃ­neas]

## ðŸ“‹ Contexto
[SituaciÃ³n actual, problema a resolver]

## ðŸ” ConfiguraciÃ³n Privada Requerida
[Lista de archivos necesarios en privada/]

## ðŸ—ï¸ Plan de ImplementaciÃ³n

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| ðŸ¤– | TAREA AGENTE | Builder |
| ðŸ‘¤ | TAREA USUARIO | Usuario |

### Fase 0: [Nombre] (ðŸ‘¤/ðŸ¤–)
#### 0.1: ðŸ¤–/ðŸ‘¤ [Nombre tarea]
- **Tipo:** ðŸ¤–/ðŸ‘¤ TAREA [AGENTE/USUARIO]
- **Archivo:** `ruta/archivo.py`
- **AcciÃ³n:** Crear/Modificar
- **DescripciÃ³n:** [QuÃ© hacer]
- **Riesgo:** ðŸŸ¢/ðŸŸ¡/ðŸ”´ [Bajo/Medio/Alto]
- **Criterio de AceptaciÃ³n:** [Medible y verificable]
- **Si falla:** [AcciÃ³n a tomar]

### Fase 1: [Nombre]
...

## âš–ï¸ Trade-offs Considerados
| OpciÃ³n | Pros | Contras | DecisiÃ³n |
|--------|------|---------|----------|
| A | [+] | [-] | [âœ…/âŒ] |

## ðŸš¨ GuÃ­a de Riesgos
| Nivel | Significado | AcciÃ³n del Builder |
|-------|-------------|-------------------|
| ðŸŸ¢ Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| ðŸŸ¡ Medio | Requiere atenciÃ³n | Intentar 2 veces, escalar si dudas |
| ðŸ”´ Alto | CrÃ­tica | Escalar al primer fallo |

## ðŸ§ª Criterios de AceptaciÃ³n Global
- [ ] [Criterio medible 1]
- [ ] [Criterio medible 2]
```

### Paso 4: Asignar Riesgos

Para cada tarea, usar guÃ­a en `references/risk-guide.md`:

**ðŸŸ¢ Bajo:**
- Crear archivos nuevos
- Modificar templates
- Tests simples

**ðŸŸ¡ Medio:**
- Modificar lÃ³gica existente
- Cambios en configuraciÃ³n
- Integraciones

**ðŸ”´ Alto:**
- Cambios arquitectÃ³nicos
- Migraciones de datos
- Cambios en seguridad

### Paso 5: Definir Criterios de AceptaciÃ³n

Cada tarea necesita criterios **SMART**:
- **S**pecific: QuÃ© exactamente
- **M**easurable: CÃ³mo se verifica
- **A**chievable: Realista
- **R**elevant: Al plan
- **T**ime-bound: CuÃ¡ndo listo

Ejemplo bueno:
> "Crear `validate_all.py` que detecte 9 directorios de skills y valide frontmatter YAML con campos: name, version, description, author, tags"

Ejemplo malo:
> "Crear script de validaciÃ³n"

### Paso 6: Documentar Trade-offs

Si hay decisiones arquitectÃ³nicas:

```markdown
## âš–ï¸ Trade-offs Considerados

| OpciÃ³n | Pros | Contras | DecisiÃ³n |
|--------|------|---------|----------|
| SQLite local | Simple, sin servidor | No escalable | âœ… Elegida |
| PostgreSQL | Escalable | Requiere setup | âŒ Descartada |

**RazÃ³n:** Para MVP, SQLite es suficiente.
```

Crear ADR en `.agent/decisions/` si es decisiÃ³n importante.

### Paso 7: Aprobar Plan

Checklist antes de aprobar:
- [ ] ID Ãºnico y descriptivo
- [ ] Fase 0 incluida si hay archivos privados
- [ ] Todas las tareas tienen riesgo asignado
- [ ] Criterios de aceptaciÃ³n son medibles
- [ ] Trade-offs documentados (si aplica)
- [ ] Ninguna fase tiene campos duplicados (p.ej. dos lineas `Descripcion:` en la misma fase); si se actualizo un campo, borrar la version anterior antes de aprobar
- [ ] No hay contradiccion entre `Descripcion` y `Criterios de Aceptacion` de la misma fase; si difieren, reconciliarlos explicitamente antes de aprobar — nunca asumir que uno manda sobre el otro sin corregir el texto
- [ ] Todo criterio verificable de una fase tiene su comando o accion correspondiente en la seccion `Calidad`; si un criterio de aceptacion no aparece ahi, el Manager puede aprobarlo sin haberlo verificado
- [ ] Si un comando se usa en dos modos distintos (p.ej. `--dry-run` vs ejecucion real, `--force` vs sin flag), la Descripcion especifica explicitamente cual es la accion de la fase y cual es la comprobacion previa, en ese orden; si el plan usa `--dry-run`, la fase real debe existir como paso separado — dry-run nunca sustituye la ejecucion real ni cuenta como validacion de cierre
- [ ] Si `work_plan.md` y `PLAN_WP-*.md` coexisten, el resumen corto no puede contradecir al largo en ningun punto operativo (comandos, flags, orden de pasos); si difieren, el largo (work_plan.md) manda y el corto debe regenerarse antes de aprobar
- [ ] Si una fase depende de actualizar `PROJECT.md` o `CHANGELOG.md` manualmente, la Descripcion especifica quien lo actualiza (Builder/Manager) y con que criterio o contenido minimo; la ambiguedad aqui produce fases declaradas completas sin que los archivos se hayan tocado

Cambiar estado: `ðŸŸ¡ IN_PLANNING` â†’ `ðŸŸ¢ APPROVED`

AÃ±adir notificaciÃ³n:
```markdown
## ðŸ“¨ [FECHA] Handoff: Manager â†’ Builder
**Plan:** WP-XXX
**AcciÃ³n requerida:** Implementar segÃºn work_plan.md
**Estado:** â³ PENDING
```

## Handoff canonico al Builder (OBLIGATORIO)

Preparar la documentacion para el Builder NO es solo aprobar el work_plan.
Son SIETE artefactos. Omitir uno deja el ciclo incompleto. Error recurrente:
olvidar `PLAN_WP-*.md` y `AUDIT_WP-*.md`.

Checklist obligatorio, en orden:

0. `TP Check` en `AUDIT_WP` — verificar contra `../../_shared/ticket-anti-patterns.md` antes de aprobar el `work_plan`.
1. `work_plan.md` — contenido completo + `Estado: APPROVED`.
2. `PLAN_WP-XXXX.md` — estrategia tecnica del ticket (en `.agent/collaboration/`).
3. `AUDIT_WP-XXXX.md` — criterios que el Manager verificara en el review.
4. `execution_log.md` — `Estado: IN_PROGRESS`, bitacora inicializada.
5. `TURN.md` — regenerar a `ROL=BUILDER`:
   `python .agent/agent_controller.py --reset-turn --force`
   Sin `--reset-turn` el controller NO sobrescribe un TURN.md existente.
6. `STATE.md` — lo regenera el mismo comando del paso 5.
7. Bus — emitir `STATE_CHANGED -> IN_PROGRESS`:
   `python .agent/agent_controller.py --bootstrap-ticket --json`
   Idempotente (`already_bootstrapped` si ya existe).

Verificacion final OBLIGATORIA:
`python .agent/agent_controller.py --validate --json --force` -> 0 errores.

Solo con los 7 artefactos + validate en verde el turno es del Builder y el
launcher abrira su ventana del Builder.

## Output Format

El handoff al Builder genera/actualiza, sin omitir ninguno:
1. `work_plan.md` (APPROVED)
2. `PLAN_WP-XXXX.md` (estrategia tecnica)
3. `AUDIT_WP-XXXX.md` (criterios de auditoria)
4. `execution_log.md` (IN_PROGRESS)
5. `TURN.md` + `STATE.md` (regenerados con `--reset-turn`)
6. Bus: evento `STATE_CHANGED -> IN_PROGRESS`
7. `--validate` en verde
8. `notifications.md` con handoff al Builder (opcional)
9. ADR en `.agent/decisions/` (opcional, si trade-off significativo)

## References

- `references/plan-template.md` - Template base del plan
- `references/risk-guide.md` - GuÃ­a de asignaciÃ³n de riesgos
- `.agent/templates/work_plan_template.md` - Template completo del sistema
- `.agent/rules/manager/` - Restricciones del rol

- `references/plan-quality-checklist.md` - Checklist de calidad para planes y audits
- `../../_shared/ticket-anti-patterns.md` - Catalogo TP compartido para prompts de Manager y Builder
- `../man-session-closeout/SKILL.md` - Cierre de sesion y puente de learnings

## TP Check obligatorio

Antes de aprobar cualquier `work_plan.md`, el Manager debe rellenar en `AUDIT_WP-XXXX.md` una seccion `## TP Check` usando:

1. `../../_shared/ticket-anti-patterns.md` como catalogo de referencia.
2. `references/plan-quality-checklist.md` como checklist de aprobacion.
3. Evidencia literal para cada check: seccion, linea, test, comando o diff.

Regla de aprobacion:
- Si un TP aplica y no puede cerrarse con una linea concreta, el plan sigue en borrador.
- Si el plan y el audit no coinciden en secuencia, archivos o criterios, el ticket no pasa a `APPROVED`.
- Si el texto usa semantica blanda sin definir el mecanismo, se corrige antes del handoff.
- Si el ticket introduce una nueva gate de calidad, aplica ese gate manualmente sobre el propio `AUDIT_WP` antes de confiar en automatizacion futura.
- Si existe `.agent/runtime/memory/closeout_lessons.md`, usalo como contexto antes de redactar un nuevo plan.

## Constraints

- **NO** asignar tareas del usuario (ðŸ‘¤) al Builder
- **NO** omitir Fase 0 si hay archivos privados
- **SIEMPRE** incluir criterios de aceptaciÃ³n medibles
- **SIEMPRE** asignar nivel de riesgo a cada tarea
