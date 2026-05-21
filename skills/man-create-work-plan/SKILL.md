---
name: create-work-plan
version: 1.0.0
description: Skill para que el Manager cree planes de implementaciÃ³n estructurados con fases, tareas y criterios de aceptaciÃ³n
triggers: [/plan, create-plan, /schedule]
author: agent
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

Cambiar estado: `ðŸŸ¡ IN_PLANNING` â†’ `ðŸŸ¢ APPROVED`

AÃ±adir notificaciÃ³n:
```markdown
## ðŸ“¨ [FECHA] Handoff: Manager â†’ Builder
**Plan:** WP-XXX
**AcciÃ³n requerida:** Implementar segÃºn work_plan.md
**Estado:** â³ PENDING
```

## Output Format

El plan debe generar:
1. `work_plan.md` completo y aprobado
2. `notifications.md` con handoff al Builder
3. ADR opcional en `.agent/decisions/` (si trade-off significativo)

## References

- `references/plan-template.md` - Template base del plan
- `references/risk-guide.md` - GuÃ­a de asignaciÃ³n de riesgos
- `.agent/templates/work_plan_template.md` - Template completo del sistema
- `.agent/rules/manager/` - Restricciones del rol

## Constraints

- **NO** asignar tareas del usuario (ðŸ‘¤) al Builder
- **NO** omitir Fase 0 si hay archivos privados
- **SIEMPRE** incluir criterios de aceptaciÃ³n medibles
- **SIEMPRE** asignar nivel de riesgo a cada tarea
