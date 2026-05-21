---
name: code-review
version: 1.0.0
description: Revisar cambios de cÃ³digo contra arquitectura del proyecto
triggers: [/review, code-review, /approve]
author: agent
tags: [core, system]
---

# man-review-implementation

Skill para revisar trabajo del Builder segÃºn el plan aprobado y criterios de calidad.

## Overview

Cuando el Builder marca una tarea como `READY_FOR_REVIEW`, el Manager usa esta skill para:
1. Entender quÃ© se implementÃ³ (execution_log.md)
2. Verificar Quality Gates (ruff + runner seguro de pytest)
3. Revisar cÃ³digo contra criterios de aceptaciÃ³n
4. Verificar seguridad (no secrets, arquitectura respetada)
5. Generar veredicto: APROBADO / CAMBIOS_REQUERIDOS / RECHAZADO

## Workflow

### Paso 0: Verificar Turno
```bash
python .agent/agent_controller.py
```
Debe indicar `ROL ACTIVO: MANAGER`. Si dice BUILDER, informar al usuario.

### Paso 1: Cargar Contexto
Leer en orden:
1. `.agent/rules/manager/` - restricciones del rol
2. `work_plan.md` - plan aprobado con criterios de aceptaciÃ³n
3. `execution_log.md` - quÃ© implementÃ³ el Builder
4. `references/review-checklist.md` - checklist de verificaciÃ³n

### Paso 2: Leer el cÃ³digo directamente

**Regla de oro: no confÃ­es en el log; lee el cÃ³digo.**

Para cada archivo listado en `execution_log.md`, lÃ©elo directamente. No aceptes el resumen del Builder como Ãºnica evidencia.

Re-ejecuta tÃº mismo las validaciones tipo-especÃ­ficas:
```bash
python -m py_compile src/archivo.py
python -c "import yaml; yaml.safe_load(open('data/archivo.yaml', encoding='utf-8')); print('OK')"
```

**SeÃ±ales de alerta que requieren verificaciÃ³n adicional:**
- Builder reporta **"ya existÃ­a"** o **"ya estaba hecho"** â†’ lee el archivo y verifica que el contenido cumple el criterio del plan exacto, no solo que algo con ese nombre existe.
- Builder dice **"sin cambios necesarios"** â†’ verifica que el plan no requerÃ­a algo diferente.
- El plan modificaba **N archivos del mismo tipo** y el log solo menciona uno â†’ verifica los N archivos individualmente.
- El nÃºmero de tests **cambia >5%** â†’ investiga por quÃ©.

Para cada archivo, verifica:

| VerificaciÃ³n | Â¿QuÃ© buscar? |
|--------------|--------------|
| **Cumple plan** | Â¿El cÃ³digo hace exactamente lo que pide el plan, sin funciones extra no solicitadas? |
| **Consistencia de estado** | Â¿Lo que reporta `execution_log.md` coincide con lo que hay realmente en disco? |
| **Type hints** | Â¿Todas las funciones tienen hints en argumentos y retorno? |
| **Docstrings** | Â¿Funciones y clases pÃºblicas tienen docstrings descriptivos? |
| **Pathlib** | Â¿Se usa `pathlib` de forma consistente para toda manipulaciÃ³n de rutas? |
| **Manejo errores** | Â¿Hay `try/except` con logs especÃ­ficos? Prohibido `except: pass`. |
| **Secrets** | Â¿No hay API keys, passwords ni rutas absolutas locales hardcodeadas? |
| **CÃ³digo muerto** | Â¿Se eliminaron variables, imports y archivos `debug_*.py` temporales? |
| **Hub nodes** | Si existe `graphify-out/GRAPH_REPORT.md`, Â¿los archivos de alto grado tocados estÃ¡n mencionados en el log? |

### Paso 3: Ejecutar Quality Gates

```bash
# 1. Sintaxis Python
python -m py_compile src/**/*.py

# 2. Linting (src/ + tests/)
ruff check . --exclude .agent

# 3. Tests
python scripts/run_pytest_safe.py

# Fallback
python scripts/run_pytest_safe.py -- tests/ -v

# 4. Verificar imports circulares
python -c "import src"
```

**Si falla algÃºn gate:**
- Documentar errores en `review_queue.md` como `CHANGES_REQUESTED`
- Notificar al Builder via `notifications.md`
- **NO aprobar hasta que pase todos los gates**

### Paso 4: Verificar Seguridad

**Checklist de Seguridad:**
- [ ] No hay strings de conexiÃ³n/credenciales en cÃ³digo
- [ ] Variables de entorno usadas vÃ­a `settings.py`
- [ ] PatrÃ³n cascada respetado (`privada/` â†’ `publica/`)
- [ ] `.gitignore` protege `privada/`, `.env`, `data/`
- [ ] No hay `print()` con datos sensibles

### Paso 5: Generar Veredicto

#### OpciÃ³n A: APROBADO
Si pasa todos los gates y verificaciones:

1. En `work_plan.md`: cambiar estado a `âœ… COMPLETED`
2. En `review_queue.md`: aÃ±adir entrada `APPROVED`
3. En `notifications.md`: notificar handoff al usuario
4. Limpiar `execution_log.md` para prÃ³xima sesiÃ³n

#### OpciÃ³n B: CAMBIOS_REQUERIDOS
Si hay problemas menores:

```markdown
### ðŸ”„ REV-[ID]: Cambios Solicitados
- **Plan ID:** WP-XXX
- **Tipo:** CHANGES_REQUESTED
- **Prioridad:** [Alta/Media/Baja]
- **Estado:** â³ PENDING

**Problemas encontrados:**
1. [DescripciÃ³n del problema]
2. [DescripciÃ³n del problema]

**Cambios solicitados:**
1. [Cambio especÃ­fico]
2. [Cambio especÃ­fico]

**Referencia:** Ver execution_log.md secciÃ³n [X]
```

#### OpciÃ³n C: RECHAZADO
Si hay problemas graves (seguridad, arquitectura incorrecta):
- Documentar en `review_queue.md` con detalles
- Requerir nueva implementaciÃ³n
- Mantener plan en `APPROVED` para que Builder reintente

## Output Format

### Veredicto en review_queue.md

```markdown
### ðŸ” REV-[ID]: RevisiÃ³n de [Plan ID]
- **Fecha:** [YYYY-MM-DD HH:MM]
- **Revisor:** Manager
- **Veredicto:** [APPROVED | CHANGES_REQUESTED | REJECTED]
- **Estado:** âœ… RESOLVED / â³ PENDING

**Resumen:**
[2-3 lÃ­neas de resumen]

**Quality Gates:**
- [x] Ruff: PASSED
- [x] Pytest: PASSED (X/Y tests)
- [x] Seguridad: VERIFIED

**Archivos revisados:**
- `src/[archivo].py` - [OK | Cambios solicitados]

**Notas:**
[Observaciones adicionales]
```

### NotificaciÃ³n al Builder (notifications.md)

```markdown
## ðŸ“¨ [FECHA] RevisiÃ³n Completa: Manager â†’ Builder
**Plan:** WP-XXX
**Veredicto:** [APPROVED | CHANGES_REQUESTED]
**AcciÃ³n requerida:** [Ver review_queue.md | Continuar con siguiente tarea]
**Estado:** â³ PENDING
```

## References

- `references/review-checklist.md` - Checklist detallado de revisiÃ³n
- `references/verdict-format.md` - Templates de veredictos
- `.agent/rules/manager/` - Restricciones del rol Manager
- `.agent/workflows/manager_workflow.md` - Flujo completo

## Constraints

- **NO** modificar cÃ³digo en `src/` o `tests/`
- **NO** escribir en `execution_log.md` (solo lectura)
- **NO** aprobar sin verificar Quality Gates
- **SIEMPRE** documentar decisiÃ³n en `review_queue.md`
