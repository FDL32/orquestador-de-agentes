---

name: code-review

version: 2.0.0

description: Revisar cambios de código contra arquitectura del proyecto

triggers: [/review, code-review, /approve]

author: agent

role: manager

stage: review

writes_memory: false

quality_gate: false

tags: [core, system]

---



# man-review-implementation



Skill para revisar trabajo del Builder según el plan aprobado y criterios de calidad.



## Overview



Cuando el Builder marca una tarea como `READY_FOR_REVIEW`, el Manager usa esta skill para:

1. Entender qué se implementó (execution_log.md)

2. Verificar Quality Gates (ruff + runner seguro de pytest)

3. Revisar código contra criterios de aceptación

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

2. `work_plan.md` - plan aprobado con criterios de aceptación

3. `execution_log.md` - qué implementó el Builder

4. `references/review-checklist.md` - checklist de verificación



### Paso 2: Leer el código directamente



**Regla de oro: no confíes en el log; lee el código.**



Para cada archivo listado en `execution_log.md`, léelo directamente. No aceptes el resumen del Builder como única evidencia.



Re-ejecuta tú mismo las validaciones tipo-específicas:

```bash

python -m py_compile src/archivo.py

python -c "import yaml; yaml.safe_load(open('data/archivo.yaml', encoding='utf-8')); print('OK')"

```



**Señales de alerta que requieren verificación adicional:**

- Builder reporta **"ya existía"** o **"ya estaba hecho"** -> lee el archivo y verifica que el contenido cumple el criterio del plan exacto, no solo que algo con ese nombre existe.

- Builder dice **"sin cambios necesarios"** -> verifica que el plan no requería algo diferente.

- El plan modificaba **N archivos del mismo tipo** y el log solo menciona uno -> verifica los N archivos individualmente.

- El número de tests **cambia >5%** -> investiga por qué.



Para cada archivo, verifica:



| Verificación | ¿Qué buscar? |

|--------------|--------------|

| **Cumple plan** | ¿El código hace exactamente lo que pide el plan, sin funciones extra no solicitadas? |

| **Consistencia de estado** | ¿Lo que reporta `execution_log.md` coincide con lo que hay realmente en disco? |

| **Type hints** | ¿Todas las funciones tienen hints en argumentos y retorno? |

| **Docstrings** | ¿Funciones y clases públicas tienen docstrings descriptivos? |

| **Pathlib** | ¿Se usa `pathlib` de forma consistente para toda manipulación de rutas? |

| **Manejo errores** | ¿Hay `try/except` con logs específicos? Prohibido `except: pass`. |

| **Secrets** | ¿No hay API keys, passwords ni rutas absolutas locales hardcodeadas? |

| **Código muerto** | ¿Se eliminaron variables, imports y archivos `debug_*.py` temporales? |

| **Hub nodes** | Si existe `graphify-out/GRAPH_REPORT.md`, ¿los archivos de alto grado tocados están mencionados en el log? |



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



**Si falla algún gate:**

- Documentar errores en `review_queue.md` como `CHANGES_REQUESTED`

- Notificar al Builder via `notifications.md`

- **NO aprobar hasta que pase todos los gates**



### Paso 4: Verificar Seguridad



**Checklist de Seguridad:**

- [ ] No hay strings de conexión/credenciales en código

- [ ] Variables de entorno usadas vía `settings.py`

- [ ] Patrón cascada respetado (`privada/` -> `publica/`)

- [ ] `.gitignore` protege `privada/`, `.env`, `data/`

- [ ] No hay `print()` con datos sensibles



### Paso 5: Generar Veredicto



#### Opción A: APROBADO

Si pasa todos los gates y verificaciones:



1. En `work_plan.md`: cambiar estado a `COMPLETED`

2. En `review_queue.md`: añadir entrada `APPROVED`

3. En `notifications.md`: notificar handoff al usuario

4. Limpiar `execution_log.md` para próxima sesión



#### Opción B: CAMBIOS_REQUERIDOS

Si hay problemas menores:



```markdown

### REV-[ID]: Cambios Solicitados

- **Plan ID:** WP-XXX

- **Tipo:** CHANGES_REQUESTED

- **Prioridad:** [Alta/Media/Baja]

- **Estado:** Ï³ PENDING



**Problemas encontrados:**

1. [Descripción del problema]

2. [Descripción del problema]



**Cambios solicitados:**

1. [Cambio específico]

2. [Cambio específico]



**Referencia:** Ver execution_log.md sección [X]

```



#### Opción C: RECHAZADO

Si hay problemas graves (seguridad, arquitectura incorrecta):

- Documentar en `review_queue.md` con detalles

- Requerir nueva implementación

- Mantener plan en `APPROVED` para que Builder reintente



## Output Format



### Veredicto en review_queue.md



```markdown

### REV-[ID]: Revisión de [Plan ID]

- **Fecha:** [YYYY-MM-DD HH:MM]

- **Revisor:** Manager

- **Veredicto:** [APPROVED | CHANGES_REQUESTED | REJECTED]

- **Estado:** RESOLVED / PENDING



**Resumen:**

[2-3 líneas de resumen]



**Quality Gates:**

- [x] Ruff: PASSED

- [x] Pytest: PASSED (X/Y tests)

- [x] Seguridad: VERIFIED



**Archivos revisados:**

- `src/[archivo].py` - [OK | Cambios solicitados]



**Notas:**

[Observaciones adicionales]

```



### Notificación al Builder (notifications.md)



```markdown

## [FECHA] Revisión Completa: Manager -> Builder

**Plan:** WP-XXX

**Veredicto:** [APPROVED | CHANGES_REQUESTED]

**Acción requerida:** [Ver review_queue.md | Continuar con siguiente tarea]

**Estado:** Ï³ PENDING

```



## References



- `references/review-checklist.md` - Checklist detallado de revisión

- `references/verdict-format.md` - Templates de veredictos

- `.agent/rules/manager/` - Restricciones del rol Manager

- `.agent/workflows/manager_workflow.md` - Flujo completo



## Constraints



- **NO** modificar código en `src/` o `tests/`

- **NO** escribir en `execution_log.md` (solo lectura)

- **NO** aprobar sin verificar Quality Gates

- **SIEMPRE** documentar decisión en `review_queue.md`
