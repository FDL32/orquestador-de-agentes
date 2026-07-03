# Work Plan - WOT-2026-016p

## Metadata
- **ID:** WOT-2026-016p
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Proyecciones regenerables del motor con rutas absolutas en destinos: auto-gitignore en install/sync + generadores PII-safe (N7 + B-PROJ)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

El motor escribe en los destinos PROYECCIONES REGENERABLES con rutas ABSOLUTAS
(`C:\Users\<user>\...`): `project-map.json` (campo `project_root`, project_scanner.py:717),
`destination_map.md` (lineas Destination root / Motor root, destination_context.py:377/382).
Si el destino las versiona, cada corrida del motor las re-contamina.

MORDIO EN PRODUCCION (2026-07-03, tanda backup): tras filter-repo, el gate classify hizo que
el motor REGENERARA project-map/link con rutas reales; un `git add -A` posterior las barrio a
un commit post-redaccion y se pusheo PII (cazado por Manager review). Interim aplicado a mano:
untrack+ignore en los 13 destinos. Este ticket lo hace estructural (sugerencia Manager:
"el motor deberia marcar las proyecciones regenerables como gitignored automaticamente").

## Decision Arquitectonica

- Doble barrera:
  (a) PREVENTIVA-ESTRUCTURAL: `install_agent_system.py` (install Y sync) asegura de forma
      IDEMPOTENTE un bloque gestionado en el `.gitignore` del destino con las proyecciones
      regenerables: `.agent/context/project-map.json`, `.agent/context/destination_map.md`,
      `.agent/config/motor_destination_link.json`, `.agent/.last_upgrade_result.json`,
      `.agent/runtime/`.
  (b) GENERADORES PII-SAFE: los generadores dejan de emitir rutas absolutas:
      project_scanner emite `project_root` = NOMBRE de la carpeta (no ruta completa);
      destination_context emite `Destination root` = nombre y `Motor root` = nombre.
- Consumidores VERIFICADOS en Fase 0: `_build_scanner_context_block` (agent_controller:2304)
  lee summary/frameworks/importMap, NO project_root; scope_gate solo excluye el path del
  archivo; nadie parsea las lineas de ruta del destination_map (batch_destination_controller
  ESCRIBE su propio manifiesto, no lee este). Cambio de semantica seguro.
- El CONTENIDO del link NO se toca: es machine-specific por diseno (debe llevar ruta real
  para resolver el motor); su proteccion es (a).

## Fases

### Fase 0 - Diagnostico (COMPLETADO)
- Escritores localizados: project_scanner.py:624,717; destination_context.py:377,382.
- install_agent_system.py NO gestiona .gitignore del destino (grep 0) -> funcionalidad nueva.
- Hooks de enganche: install_agent_system() L1121 y sync_agent_system() L1215.
- Consumidores verificados (arriba): sin dependencia de los campos de ruta.

### Fase 1 - Implementacion
- `scripts/install_agent_system.py`: nueva `ensure_destination_projections_ignored(project_root,
  dry_run)` -> bloque gestionado idempotente (marcador de comentario; no duplica si existe;
  respeta dry_run); llamada desde install y sync.
- `scripts/project_scanner.py`: L717 `str(project_root)` -> `project_root.name`; actualizar
  schema doc L624.
- `scripts/destination_context.py`: L377 `project_root.resolve()` -> `.name`;
  L382 motor_root -> `Path(motor_root).name` con fallback 'unknown'.

### Fase 2 - Tests (barrera FAIL-sin/PASS-con)
- `tests/test_projections_pii_safe.py` (nuevo):
  - ensure_gitignore: sobre destino tmp SIN entradas -> las anade; re-run -> sin duplicados
    (idempotente); dry_run -> no escribe.
  - project_scanner: el JSON emitido para un tmp project NO contiene patron de ruta absoluta
    (`[A-Za-z]:\\` ni `/home/`) y `project_root` == nombre de carpeta.
  - destination_context: el map generado NO contiene rutas absolutas.
  - BARRERA: los asserts de ausencia fallan contra el comportamiento antiguo (revertir el
    cambio del generador -> test rojo).

## Criterios de aceptacion

1. Destino tmp recien instalado (install) -> `.gitignore` contiene las 5 entradas de
   proyecciones; `git add -n .` NO stagea ninguna proyeccion.
2. Re-ejecutar install/sync -> cero duplicados en .gitignore (idempotencia).
3. project-map.json y destination_map.md generados SIN rutas absolutas (regex negativa).
4. BARRERA verificada: sin el fix de generador, los tests de ausencia FALLAN.
5. `ruff check` + `ruff format --check` verdes sobre los .py tocados.
6. Suite canonica `run_pytest_safe.py --level all` exit 0 (tested_commit_sha == HEAD).
7. `validate --json` = 0 errors / 0 warnings; `check_encoding_guard.py` exit 0.

## Files Likely Touched

### repo_motor
- `scripts/install_agent_system.py`
- `scripts/project_scanner.py`
- `scripts/destination_context.py`
- `tests/test_projections_pii_safe.py` (nuevo)

## Read/inspect only
- `.agent/agent_controller.py` (_build_scanner_context_block, consumidor verificado).
- `runtime/motor_link.py` (lector del link; no se toca).

## Non-goals
- NO tocar el CONTENIDO de motor_destination_link.json (machine-specific por diseno).
- NO retro-limpiar destinos ya publicados (hecho a mano en la tanda; este ticket es estructural).
- NO tocar classify_publication (eso es 016o) ni el gate de publicacion (016m).
- NO mezclar con .last_upgrade_result (lo escribe el agent_system legacy, no el motor actual;
  entra solo como entrada de gitignore).
