---

name: bui-implement-from-plan

version: 2.0.0

description: Implementar nueva funcionalidad basado en especificación

triggers: [/implement, implement, /code]

author: agent

role: builder

stage: implement

writes_memory: false

quality_gate: false

tags: [core, system]

---



# bui-implement-from-plan



Skill para implementar código según un plan de trabajo aprobado.



## Overview



Cuando el Manager marca un plan como `APPROVED`, el Builder usa esta skill para:

1. Leer y entender el plan completo

2. Implementar tareas en orden (sin saltar fases)

3. Aplicar reglas de código (pathlib, type hints, etc.)

4. Usar la Regla de 2 Acciones para documentar hallazgos

5. Registrar progreso y escalarse si es necesario



## Workflow



### Paso 0: Verificar Turno

```bash

python .agent/agent_controller.py

```

Debe indicar `ROL ACTIVO: BUILDER` y acción `IMPLEMENT`.



### Paso 1: Cargar Contexto



Leer en orden:

1. `.agent/rules/builder/` - restricciones del rol

2. `work_plan.md` - plan aprobado completo

3. `execution_log.md` - progreso previo

4. `references/code-rules.md` - reglas de código



### Paso 2: Identificar Tarea Actual



En `work_plan.md`, buscar:

- Primera fase con tareas pendientes `[ ]`

- Primera tarea no completada en esa fase



**NO saltar fases** - Implementar en orden.



### Paso 3: Verificar Pre-condiciones



Antes de implementar:

- [ ] Plan est? `APPROVED` (no `DRAFT` o `IN_PLANNING`)

- [ ] No hay tareas `USUARIO` pendientes en esta fase

- [ ] Entiendo qué debo hacer (criterio de aceptación claro)



### Paso 4: Implementar con Reglas de Código



Ver `references/code-rules.md` para detalles completos.



**Reglas esenciales:**



| Regla | Ejemplo | Incorrecto | Correcto |

|-------|---------|---------------|-------------|

| **Pathlib** | Rutas | `os.path.join()` | `Path() / "file"` |

| **Type hints** | Funciones | `def load():` | `def load() -> dict:` |

| **Docstrings** | Públicas | Sin docstring | `"""Carga config."""` |

| **Logging** | Errores | `print(e)` | `logger.error(e)` |

| **Try/except** | Excepciones | `except:` | `except ValueError:` |



### Paso 5: Aplicar Regla de 2 Acciones



Después de **2 operaciones de lectura consecutivas** (leer archivos, buscar código, listar directorios), documenta hallazgos relevantes antes de continuar.



**Documentar en `findings.md`:**



```markdown

### [FECHA HORA] - [Categoría]

**Archivo:** `src/[archivo].py`

**Hallazgo:** [Patrón detectado / Decisión importante]

**Impacto:** [Cómo afecta al código]

```



Si no hay nada relevante que documentar, continúa sin escribir.



### Paso 6: Probar el Código



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

1. Verificación tipo-específica (py_compile, yaml.safe_load, json.load)

2. Protocolo "ya existía" con cita de línea

3. Completitud multi-archivo

4. Checklist anti-regresión para ISS/code smell

5. Gate completo ruff + pytest



**Solo si `bui-self-audit` pasa completamente, continúa al Paso 7.**



### Paso 7: Documentar en execution_log.md



```markdown

### [OK] [FECHA] - [Nombre Tarea]

- **Archivo:** `src/[archivo].py`

- **Cambios:** [Descripción breve]



**Código añadido:**

```python

# Ejemplo de función creada

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



Si todas las tareas de la fase están `[x]`:

1. Ejecutar **Quality Gates completos**

2. Si pasan → Continuar con siguiente fase

3. Si fallan → Corregir antes de continuar



### Paso 10: Cierre Canonico (solo al completar el plan entero)



Cuando TODAS las fases están completadas y los quality gates pasan:

```bash

python .agent/agent_controller.py --pre-handoff --project-root <workspace> --json --force

python .agent/agent_controller.py --mark-ready --project-root <workspace> --json --force

```

**Este paso es obligatorio.** Sin el `--mark-ready`, el bus no recibe `BUILDER_EXIT` y el Manager nunca revisa.

Si `--mark-ready` falla porque `checkpoint/review-<ticket>` esta obsoleto (`stale`, `expected HEAD`), no uses `--scope-override`: ejecuta `python .agent/agent_controller.py --pre-handoff --project-root <workspace> --json --force` otra vez para recrear M3 sobre el HEAD actual de `repo_motor` y despues reintenta `--mark-ready`.



## Escalación



**Escalar al Manager si:**



| Riesgo | Condición | Acción |

|--------|-----------|--------|

| Bajo | 3+ intentos fallidos | Escalar |

| Medio | 2+ intentos fallidos | Escalar |

| Alto | 1 intento fallido | Escalar inmediatamente |

| Cualquiera | 30+ min bloqueado | Escalar |



**Cómo escalar:**

1. Documentar en `execution_log.md` intentos realizados

2. Añadir a `review_queue.md` con formato de escalación

3. Cambiar estado a `BLOCKED`

4. Informar al usuario



## Output Format



### Al Completar Tarea

- Tarea marcada `[x]` en `work_plan.md`

- Entrada en `execution_log.md` con cambios y tests

- `findings.md` actualizado (si aplicó 2-Action Rule)



### Al Completar Fase

- Todas las tareas de la fase en `[x]`

- Quality Gates pasados

- Resumen de la fase en `execution_log.md`



### Al Completar Plan

- Todas las fases completadas

- Resumen final en `execution_log.md`

- Ejecutar cierre canonico (OBLIGATORIO, en este orden):

```bash

python .agent/agent_controller.py --pre-handoff --project-root <workspace> --json --force

python .agent/agent_controller.py --mark-ready --project-root <workspace> --json --force

```

- Estado cambiado a `READY_FOR_REVIEW` por el controller (no manualmente)



## References



- `references/code-rules.md` - Reglas completas de código Python

- `references/log-format.md` - Formato de execution_log.md

- `.agent/rules/builder/` - Restricciones del rol

- `.agent/workflows/builder_workflow.md` - Flujo completo



## Constraints



- **NO** modificar `work_plan.md` (excepto marcar tareas `[x]`)

- **NO** saltar fases del plan

- **NO** omitir type hints o docstrings

- **NO** usar `os.path` (usar `pathlib`)

- **SIEMPRE** documentar hallazgos (2-Action Rule)

- **SIEMPRE** escalar si se superan intentos según riesgo
