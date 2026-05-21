---
name: implement-feature
version: 1.0.0
description: Implementar nueva funcionalidad basado en especificaciÃ³n
triggers: [/implement, implement, /code]
author: agent
tags: [core, system]
---

# bui-implement-from-plan

Skill para implementar cÃ³digo segÃºn un plan de trabajo aprobado.

## Overview

Cuando el Manager marca un plan como `ðŸŸ¢ APPROVED`, el Builder usa esta skill para:
1. Leer y entender el plan completo
2. Implementar tareas en orden (sin saltar fases)
3. Aplicar reglas de cÃ³digo (pathlib, type hints, etc.)
4. Usar la Regla de 2 Acciones para documentar hallazgos
5. Registrar progreso y escalarse si es necesario

## Workflow

### Paso 0: Verificar Turno
```bash
python .agent/agent_controller.py
```
Debe indicar `ROL ACTIVO: BUILDER` y acciÃ³n `IMPLEMENT`.

### Paso 1: Cargar Contexto

Leer en orden:
1. `.agent/rules/builder/` - restricciones del rol
2. `work_plan.md` - plan aprobado completo
3. `execution_log.md` - progreso previo
4. `references/code-rules.md` - reglas de cÃ³digo

### Paso 2: Identificar Tarea Actual

En `work_plan.md`, buscar:
- Primera fase con tareas pendientes `[ ]`
- Primera tarea no completada en esa fase

**NO saltar fases** - Implementar en orden.

### Paso 3: Verificar Pre-condiciones

Antes de implementar:
- [ ] Plan estÃ¡ `ðŸŸ¢ APPROVED` (no `DRAFT` o `IN_PLANNING`)
- [ ] No hay tareas `ðŸ‘¤ USUARIO` pendientes en esta fase
- [ ] Entiendo quÃ© debo hacer (criterio de aceptaciÃ³n claro)

### Paso 4: Implementar con Reglas de CÃ³digo

Ver `references/code-rules.md` para detalles completos.

**Reglas esenciales:**

| Regla | Ejemplo | âŒ Incorrecto | âœ… Correcto |
|-------|---------|---------------|-------------|
| **Pathlib** | Rutas | `os.path.join()` | `Path() / "file"` |
| **Type hints** | Funciones | `def load():` | `def load() -> dict:` |
| **Docstrings** | PÃºblicas | Sin docstring | `"""Carga config."""` |
| **Logging** | Errores | `print(e)` | `logger.error(e)` |
| **Try/except** | Excepciones | `except:` | `except ValueError:` |

### Paso 5: Aplicar Regla de 2 Acciones

DespuÃ©s de **2 operaciones de lectura consecutivas** (leer archivos, buscar cÃ³digo, listar directorios), documenta hallazgos relevantes antes de continuar.

**Documentar en `findings.md`:**

```markdown
### [FECHA HORA] - [CategorÃ­a]
**Archivo:** `src/[archivo].py`
**Hallazgo:** [PatrÃ³n detectado / DecisiÃ³n importante]
**Impacto:** [CÃ³mo afecta al cÃ³digo]
```

Si no hay nada relevante que documentar, continÃºa sin escribir.

### Paso 6: Probar el CÃ³digo

```bash
# Ejecutar tests relacionados
python scripts/run_pytest_safe.py -- tests/test_[modulo].py -v

# Fallback
python scripts/run_pytest_safe.py -- tests/test_[modulo].py -v

# Verificar linting
ruff check src/[archivo].py
```

**Si falla:** Corregir antes de continuar.

### Paso 6.5: Ejecutar bui-self-audit (OBLIGATORIO)

Antes de documentar la tarea como completada, ejecuta el skill `bui-self-audit`.

`bui-self-audit` cubre:
1. VerificaciÃ³n tipo-especÃ­fica (py_compile, yaml.safe_load, json.load)
2. Protocolo "ya existÃ­a" con cita de lÃ­nea
3. Completitud multi-archivo
4. Checklist anti-regresiÃ³n para ISS/code smell
5. Gate completo ruff + pytest

**Solo si `bui-self-audit` pasa completamente, continÃºa al Paso 7.**

### Paso 7: Documentar en execution_log.md

```markdown
### âœ… [FECHA] - [Nombre Tarea]
- **Archivo:** `src/[archivo].py`
- **Cambios:** [DescripciÃ³n breve]

**CÃ³digo aÃ±adido:**
```python
# Ejemplo de funciÃ³n creada
def nueva_funcion() -> None:
    pass
```

**Tests:**
```bash
$ python scripts/run_pytest_safe.py
[archivo].py::test_nueva PASSED
```

**Hallazgos:** [Si aplica, referencia a findings.md]
```

### Paso 8: Marcar Tarea Completada

En `work_plan.md`:
- Cambiar `- [ ]` a `- [x]` para la tarea completada

### Paso 9: Verificar si Fase Completa

Si todas las tareas de la fase estÃ¡n `[x]`:
1. Ejecutar **Quality Gates completos**
2. Si pasan â†’ Continuar con siguiente fase
3. Si fallan â†’ Corregir antes de continuar

## EscalaciÃ³n

**Escalar al Manager si:**

| Riesgo | CondiciÃ³n | AcciÃ³n |
|--------|-----------|--------|
| ðŸŸ¢ Bajo | 3+ intentos fallidos | Escalar |
| ðŸŸ¡ Medio | 2+ intentos fallidos | Escalar |
| ðŸ”´ Alto | 1 intento fallido | Escalar inmediatamente |
| Cualquiera | 30+ min bloqueado | Escalar |

**CÃ³mo escalar:**
1. Documentar en `execution_log.md` intentos realizados
2. AÃ±adir a `review_queue.md` con formato de escalaciÃ³n
3. Cambiar estado a `ðŸŸ  BLOCKED`
4. Informar al usuario

## Output Format

### Al Completar Tarea
- Tarea marcada `[x]` en `work_plan.md`
- Entrada en `execution_log.md` con cambios y tests
- `findings.md` actualizado (si aplicÃ³ 2-Action Rule)

### Al Completar Fase
- Todas las tareas de la fase en `[x]`
- Quality Gates pasados
- Resumen de la fase en `execution_log.md`

### Al Completar Plan
- Todas las fases completadas
- Estado cambiado a `ðŸŸ£ READY_FOR_REVIEW`
- Resumen final en `execution_log.md`
- NotificaciÃ³n en `notifications.md`

## References

- `references/code-rules.md` - Reglas completas de cÃ³digo Python
- `references/log-format.md` - Formato de execution_log.md
- `.agent/rules/builder/` - Restricciones del rol
- `.agent/workflows/builder_workflow.md` - Flujo completo

## Constraints

- **NO** modificar `work_plan.md` (excepto marcar tareas `[x]`)
- **NO** saltar fases del plan
- **NO** omitir type hints o docstrings
- **NO** usar `os.path` (usar `pathlib`)
- **SIEMPRE** documentar hallazgos (2-Action Rule)
- **SIEMPRE** escalar si se superan intentos segÃºn riesgo
