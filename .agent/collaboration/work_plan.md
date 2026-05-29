# Work Plan - WP-2026-173

## Metadata
- **ID:** WP-2026-173
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Add pre-handoff helper to stage commit and checkpoint before mark-ready
- **Asignado a:** Builder

## Objetivo
Convertir el cierre manual de 3 pasos en un unico comando atomico antes de `--mark-ready`: preparar los cambios del ticket, crear el commit, refrescar el checkpoint M3 y dejar el arbol limpio o fallar con un mensaje claro.

## Contexto
- Hoy el guard detecta cuando el Builder llega a `--mark-ready` sin commit ni checkpoint, pero eso sigue siendo una deteccion reactiva.
- El flujo repetido de 171 y 172 muestra que el proceso necesita una herramienta proactiva que obligue el orden correcto antes de la entrega.
- No se va a depender de `scripts/create_checkpoint.py`; el helper debe crear o refrescar el tag M3 inline usando el mismo patron de `git rev-parse checkpoint/review-<ticket>^{}` + `git tag -d` + `git tag -a` que ya usa `scripts/pre_handoff_guard.py`.
- El helper debe stagear los archivos a partir de `Files Likely Touched` declarados en `work_plan.md`, leyendo ese bloque directamente con logica inline equivalente al parser del guard, sin importar `parse_files_likely_touched()` desde `scripts/pre_handoff_guard.py`.
- La nueva accion debe quedarse en `agent_controller.py` para aprovechar el contrato ya existente de flags y proyecciones.

## Decision Arquitectonica
- `agent_controller.py` añade un flag `--pre-handoff` que ejecuta una secuencia atomica previa a `--mark-ready`.
- La secuencia separa dos pasos independientes:
  - Paso commit: si hay cambios de entrega, stagearlos segun `Files Likely Touched` y crear el commit con mensaje estandar `chore(<ticket>): pre-handoff checkpoint`.
  - Paso tag: crear o refrescar siempre `checkpoint/review-<ticket>` inline con `git rev-parse checkpoint/review-<ticket>^{}` + `git tag -d` + `git tag -a`, exista o no exista un commit nuevo.
- Si no hay cambios de entrega y el checkpoint ya esta alineado con HEAD, el comando debe salir idempotente con exito y sin hacer nada.
- Si no hay cambios de entrega pero el checkpoint falta o apunta a otro commit, el comando debe saltar el commit y solo crear/refrescar el tag.
- Si el checkpoint M3 no existe, el helper debe crearlo inline con `git tag -a checkpoint/review-<ticket> -m "Checkpoint M3 for <ticket>"`.
- Si `git commit` falla por hooks de pre-commit, el helper debe propagar el exit code y stderr del proceso git tal cual al usuario, sin envolver o ocultar el error.
- El comando no debe tocar `scripts/pre_handoff_guard.py` ni el contrato de `--mark-ready`; solo prepara el estado correcto para que el guard pase.

## Non-goals
- No cambiar la logica del pre-handoff guard.
- No tocar `bus/supervisor.py`.
- No ampliar el scope de `--mark-ready`.
- No introducir nuevas dependencias.

## Fases

### Fase 1: comando pre-handoff
- **Tipo:** TAREA AGENTE
- **Archivos:** `.agent/agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** Añadir `--pre-handoff` como comando previo a `--mark-ready`. Debe localizar cambios de entrega, leer `Files Likely Touched` desde `work_plan.md` con logica inline equivalente al parser del guard, hacer `git add` de esos archivos, crear un commit con mensaje estandar `chore(<ticket>): pre-handoff checkpoint`, crear o refrescar `checkpoint/review-<ticket>` inline usando `git rev-parse checkpoint/review-<ticket>^{}` y `git tag -d / git tag -a`, y verificar que `git status --porcelain` queda limpio excluyendo las mismas superficies vivas que usa el guard antes de devolver exito.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** `--pre-handoff` deja el arbol listo para `--mark-ready`, devuelve exito idempotente cuando ya no hay cambios y el tag esta alineado, o falla con un error claro si el tag no puede crearse o si los hooks del commit fallan.
- **Si falla:** Mantener el flujo manual actual y limitar el comando a un helper de diagnostico.

### Fase 2: cobertura mecanica
- **Tipo:** TAREA AGENTE
- **Archivos:** `tests/test_agent_controller.py`
- **Accion:** Modificar
- **Descripcion:** Cubrir al menos cinco casos: camino feliz con commit + tag + arbol limpio, ausencia total de cambios con tag ya alineado e idempotencia, ausencia de cambios con tag faltante o desalineado donde solo se refresca el tag, fallo de hook/pre-commit propagando stderr, y fallo de verificacion final con arbol sucio despues de filtrar superficies vivas equivalentes a las del guard.
- **Riesgo:** Medio
- **Criterio de Aceptacion:** Los tests verifican la secuencia atomica del helper y los mensajes de error clave.
- **Si falla:** Conservar el helper basico y limitar la cobertura a la secuencia feliz y un caso de error.

## Files Likely Touched
- `.agent/agent_controller.py`
- `tests/test_agent_controller.py`

## Calidad
- `python scripts/run_pytest_safe.py tests/test_agent_controller.py`
- `uv run ruff check .agent/agent_controller.py tests/test_agent_controller.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `--pre-handoff` deja el Builder listo para `--mark-ready` con commit y checkpoint M3 alineados.
- El comando usa `Files Likely Touched` como fuente de verdad para stagear.
- El comando considera superficies vivas al verificar el arbol limpio al final.
- El comando devuelve exito idempotente si no hay cambios de entrega y el checkpoint ya esta alineado.
- El comando propaga el stderr real de fallos de `git commit` causados por hooks.
- Los tests cubren el camino feliz, la idempotencia sin cambios y los fallos de preflight/cierre.
