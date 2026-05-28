# Work Plan - WP-2026-158

## Metadata
- **ID:** WP-2026-158
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Review packet completeness and diff filtering
- **Asignado a:** Builder

## Objetivo
Hacer que el review packet del Manager represente el alcance real del ticket, incluyendo entregables nuevos no rastreados, y anadir un metadato minimo de filtrado/severidad inspirado en reviewdog.

## Contexto
- `AP-12` ya formaliza el riesgo: un review packet construido solo desde `git diff` oculta entregables nuevos no rastreados.
- `bus/review_bridge.py` ya construye el packet de review y hoy prioriza `git diff` y provenance, pero no expone una seccion explicita para archivos `??`.
- `agent_controller.get_changed_files()` ya sabe leer staged, unstaged y untracked desde `git status --porcelain -z`, asi que el contrato de untracked ya existe en el sistema.
- `reviewdog` aporta un patron util: packet estructurado, filtro por contexto y niveles de severidad. Aqui se quiere una version minima, no una clonacion completa.
- El flujo `APPROVE / CHANGES / INSPECT` debe permanecer intacto.

## Decision Arquitectonica
- El review packet seguira usando `git diff` como evidencia principal, pero anadira una seccion explicita `Untracked Deliverables` o equivalente con los archivos detectados por `git status`.
- El packet publicara un `filter_mode` minimo con valores acotados, por ejemplo `diff_context`, `added` y `nofilter`.
- El packet publicara una severidad minima (`info`, `warn`, `blocker`) solo como metadata legible, sin cambiar el contrato de decision.
- El bus no debe depender de `agent_controller`; si necesita untracked, lo obtendra con un helper local o una lectura local de `git status`.
- No se introduce ninguna dependencia nueva ni un sistema completo de anotaciones tipo reviewdog.

## Non-goals
- No reemplazar `git diff` por completo.
- No copiar reviewdog 1:1.
- No cambiar el contrato de decision `APPROVE / CHANGES / INSPECT`.
- No tocar el workflow de Builder/Manager mas alla de lo necesario para el packet.

## Fases
### Fase 1: untracked deliverables visibles en el packet
- **Tipo:** TAREA AGENTE
- **Archivos:** `bus/review_bridge.py`, `tests/test_manager_review_bridge.py`
- **Accion:** Crear
- **Descripcion:** Anadir una seccion explicita en el review packet para entregables nuevos no rastreados. El helper debe detectar `??` desde `git status --porcelain -z` en el root del proyecto y renderizar esa informacion junto al diff existente. El packet debe seguir incluyendo provenance y diff, pero ya no puede ocultar archivos nuevos que no aparezcan en `git diff`.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Un repo temporal con un archivo `??` y sin diff rastreado lo sigue mostrando en el review packet bajo una seccion explicita de untracked deliverables.
- **Si falla:** Reducir a una sola seccion `Untracked Deliverables` sin metadata adicional, pero nunca volver a ocultar los archivos nuevos.

### Fase 2: metadata minima de filter mode y severidad
- **Tipo:** TAREA AGENTE
- **Archivos:** `bus/review_bridge.py`, `tests/test_review_bridge.py`, `tests/test_manager_review_bridge.py`
- **Accion:** Anadir metadata y tests
- **Descripcion:** Anadir al packet una metadata legible de `filter_mode` y `severity`. El modo por defecto debe ser `diff_context`; cuando haya entregables no rastreados visibles, el packet puede marcarse como `added`. La severidad debe reflejar el tipo de evidencia sin alterar el contrato de decision.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** Los tests cubren al menos un caso con solo diff rastreado y otro con entregable no rastreado, y en ambos el contrato `APPROVE / CHANGES / INSPECT` sigue intacto.
- **Si falla:** Conservar solo `filter_mode` sin severidad, pero mantener la seccion explicita de untracked deliverables.

## Files Likely Touched
- `bus/review_bridge.py`
- `tests/test_manager_review_bridge.py`
- `tests/test_review_bridge.py`

## Calidad
- `python -m pytest tests/test_manager_review_bridge.py tests/test_review_bridge.py -q`
- `python scripts/run_pytest_safe.py`
- `python .agent/agent_controller.py --validate --json --force`
- `ruff check bus scripts tests`

## Criterios de aceptacion
- El review packet ya no oculta entregables nuevos no rastreados.
- El packet publica una metadata minima de `filter_mode` y `severity` sin cambiar la decision.
- Los tests demuestran que un repo temporal con archivos `??` aparece en el packet.
- La suite safe principal sigue pasando.
- La validacion canonica pasa sin errores.
