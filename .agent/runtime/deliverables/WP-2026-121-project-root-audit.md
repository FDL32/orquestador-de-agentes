# Auditoria de derivacion de `project_root` (WP-2026-121)

Inventario **exhaustivo** de todos los puntos del motor que derivan o asumen
`project_root` / `AGENT_DIR`, base exacta para la implementacion (WP-2026-122).
Este WP NO modifica codigo: solo describe y decide.

Metodo: `grep "Path(__file__)"` sobre todos los `*.py` del repo (117
ocurrencias revisadas, sin truncar) + lectura de los modulos del bus.

---

## Fase 1: Inventario de derivacion de root (clasificado)

Cada fila se clasifica en una de tres categorias:

- **[A]** En alcance de WP-A: runtime operativo que lee/escribe el estado
  canonico del proyecto destino -> debe aceptar `project_root` inyectado.
- **[B]** Concierne al instalador / distribucion (WP-B): ya opera con un
  concepto de origen/destino; no se toca en WP-A.
- **[E]** Engine-rooted: opera sobre el propio repo del motor; debe seguir
  anclado al motor -> NO cambia.

### Categoria [A] - Runtime operativo (alcance WP-2026-122)

| Archivo | Linea | Derivacion |
|---------|-------|-----------|
| `.agent/agent_controller.py` | 38 | `_AGENT_DIR = Path(__file__).parent.resolve()` |
| `.agent/agent_controller.py` | 88 | `SCRIPT_DIR = Path(__file__).parent` -> `PROJECT_ROOT`, `AGENT_DIR` |
| `.agent/agents_config.py` | 18 | `CONFIG_PATH = Path(__file__).parent / "config" / "agents.json"` |
| `.agent/agents_config.py` | 77 | `project_root = Path(__file__).parent.parent` |
| `.agent/completion_checker.py` | 23 | `COLLAB_DIR = Path(__file__).parent / "collaboration"` |
| `.agent/completion_common.py` | 10 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `.agent/session_tracker.py` | 25 | `COLLAB_DIR = Path(__file__).parent / "collaboration"` |
| `.agent/hooks/stop_hook.py` | 12 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `.agent/runtime/memory/memory_helpers.py` | 9 | `Path(__file__).resolve().parent` |
| `runtime/ui_state_projector.py` | 11 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` (+ usos en 16, 18) |
| `scripts/manager_review_bridge.py` | 18 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` |
| `scripts/local_audit.py` | 10 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `scripts/ticket_supervisor.py` | 11 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` |
| `scripts/ticket_activity_monitor.py` | 13 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` |
| `scripts/run_gates_dispatch.py` | 16 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `scripts/builder_agent.py` | 13 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` |
| `scripts/archive_event_bus.py` | 30 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]` |
| `scripts/check_deliverables_exist.py` | 16 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `scripts/memory_consolidate.py` | 18 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |
| `scripts/update_project_map.py` | 30 | `PROJECT_ROOT = Path(__file__).parent.parent.resolve()` |
| `scripts/validate_authority.py` | 84 | `root = Path(__file__).parent.parent` |
| `scripts/run_pytest_safe.py` | 25 | `PROJECT_ROOT = Path(__file__).resolve().parent.parent` |

Total **[A]: 22 puntos en 22 archivos** (`agent_controller.py` y
`agents_config.py` tienen 2 puntos cada uno).

### Categoria [B] - Instalador / distribucion (WP-B, no se toca en WP-A)

| Archivo | Linea | Derivacion |
|---------|-------|-----------|
| `scripts/install_agent_system.py` | 35 | `REPO_ROOT = Path(__file__).resolve().parent.parent.parent` |
| `scripts/sync_agent_core.py` | 96 | `script_path = Path(__file__).resolve()` |
| `scripts/upgrade.py` | 316 | `source_dir = args.source or Path(__file__).parent.parent` |
| `scripts/upgrade_agent_system.py` | 24-25, 556 | `sys.path` + `source_dir` |
| `scripts/detect_version.py` | 16 | `sys.path.insert(... agent_system)` |
| `scripts/doctor_agent_system.py` | 23-24 | `sys.path.insert(...)` |
| `scripts/migrate_legacy_project.py` | 22-23 | `sys.path.insert(...)` |

### Categoria [E] - Engine-rooted (opera sobre el propio motor, NO cambia)

| Archivo | Linea | Motivo |
|---------|-------|--------|
| `scripts/discover_skills.py` | 81 | `bundle_root`: descubre skills del bundle del motor. |
| `scripts/orquestador.py` | 220, 435 | Localiza scripts hermanos del motor. |
| `scripts/build_llms.py` | 20 | Genera `llms.txt` desde la doc del motor. |
| `scripts/check_ruff_hook_scope.py` | 9 | Verifica el `.pre-commit-config.yaml` del motor. |
| `agent_system/refactor_kit/refactor_manager.py` | 32 | Kit portable zero-dependency. |
| `agent_system/refactor_kit/install_refactor_kit.py` | 21 | Kit portable zero-dependency. |
| `skills/validate_all.py` | 27 | Valida skills del motor. |
| `tools/scripts/memory_manager.py` | 22 | Helper interno del motor. |

---

## Fase 2: Mapa de call-sites de `EventBus` y resolvers

| Call-site / Consumidor | Origen de `runtime_dir` / `project_root` | Estado |
|------------------------|-------------------------------------------|--------|
| `.agent/agent_controller.py:~160` | `AGENT_DIR / "runtime" / "events"` (AGENT_DIR derivado de `__file__`) | [A] Acoplado |
| `runtime/ui_state_projector.py:16,20` | `runtime_dir` param con **fallback** a `PROJECT_ROOT` derivado | [A] Acoplado en el fallback |
| `scripts/manager_review_bridge.py:~330` | `project_root=PROJECT_ROOT` derivado de `__file__` | [A] Acoplado |
| `scripts/ticket_supervisor.py:~64` | `project_root=PROJECT_ROOT` derivado de `__file__` | [A] Acoplado |
| `bus/supervisor.py` | `project_root` inyectado via constructor | Limpio (inyectado) |
| `bus/review_bridge.py` | `project_root` y `event_bus` inyectados | Limpio (inyectado) |
| `bus/event_bus.py` | `runtime_dir` inyectado via `__init__` | Limpio (inyectado) |
| `agent_system/scripts/project_paths.py` | `start_dir` externo (parametro) | Resolver; ver Fase 3 |

Conclusion: los tres modulos de `bus/` **NO necesitan cambios internos**. El
acoplamiento real esta en los call-sites de categoria [A] que construyen el
`runtime_dir` / `project_root` a partir de `__file__`.

---

## Fase 3: Diseno del contrato `project_root` y decision sobre `project_paths.py`

### Contrato de inyeccion

1. **Entry points CLI** (`agent_controller.py`, `ticket_supervisor.py`,
   `manager_review_bridge.py`, demas scripts de categoria [A]): aceptan
   `--project-root <ruta>`. Si no se pasa, fallback al comportamiento actual
   (root derivado de `__file__`) -> cero regresion.
2. **Hooks** (`stop_hook.py` y procesos lanzados por el modelo, sin CLI
   propia): leen la variable de entorno `AGENT_PROJECT_ROOT`, inyectada por el
   launcher. Si la variable no existe, fallback al derivado.
3. **Funcion central de resolucion**: una unica funcion
   `resolve_project_root()` que aplica la precedencia
   `arg CLI > env AGENT_PROJECT_ROOT > derivado de __file__`, reutilizada por
   todos los archivos [A] en lugar de repetir la logica.

### Decision CERRADA sobre `agent_system/scripts/project_paths.py`

**Decision:** `project_paths.py` se mantiene **tal cual, como helper de
instalacion y diagnostico** (lo consumen `doctor_agent_system.py`,
`validate_authority.py` y los scripts de categoria [B]). **NO se enruta el
runtime de WP-A a traves de el.**

**Motivo (cerrado, no abierto):** su `_find_project_root` resuelve el root
*caminando hacia arriba* hasta encontrar un `.agent` con marcadores. En el
modelo motor/destino coexisten dos `.agent` (el del motor y el del destino),
y esa busqueda ascendente es justo la ambiguedad que causo el split-brain de
WP-2026-049. El runtime de WP-A usara **inyeccion explicita** (contrato de
arriba), que es deterministica. `project_paths.py` se queda fuera del alcance
de WP-2026-122.

### Comportamiento por defecto

Sin `--project-root` ni `AGENT_PROJECT_ROOT`, todo el motor se comporta
exactamente como hoy (root = repo del motor). La portabilidad es aditiva.

---

## Fase 4: `Files Likely Touched` para WP-2026-122 (rutas literales)

Separado por **codigo** y **tests**, sin globs, verificable contra el scope
gate literal de `agent_controller.py`.

### Codigo (22 archivos de categoria [A])

- `.agent/agent_controller.py`
- `.agent/agents_config.py`
- `.agent/completion_checker.py`
- `.agent/completion_common.py`
- `.agent/session_tracker.py`
- `.agent/hooks/stop_hook.py`
- `.agent/runtime/memory/memory_helpers.py`
- `runtime/ui_state_projector.py`
- `scripts/manager_review_bridge.py`
- `scripts/local_audit.py`
- `scripts/ticket_supervisor.py`
- `scripts/ticket_activity_monitor.py`
- `scripts/run_gates_dispatch.py`
- `scripts/builder_agent.py`
- `scripts/archive_event_bus.py`
- `scripts/check_deliverables_exist.py`
- `scripts/memory_consolidate.py`
- `scripts/update_project_map.py`
- `scripts/validate_authority.py`
- `scripts/run_pytest_safe.py`

### Launcher / entorno

- `scripts/launch_agent_terminals.ps1`

### Tests (a actualizar / ampliar por modulo parametrizado)

- `tests/test_agent_controller.py`
- `tests/unit/test_agents_config.py`
- `tests/test_completion_checker.py`
- `tests/test_completion_common.py`
- `tests/test_stop_hook.py`
- `tests/integration/test_memory_integration.py`
- `tests/test_ui_state_projector_scoping.py`
- `tests/test_manager_review_bridge.py`
- `tests/unit/test_local_audit.py`
- `tests/test_validate_authority.py`
- `tests/unit/test_run_gates_dispatch.py`
- `tests/unit/test_check_deliverables_exist.py`
- `tests/unit/test_archive_collaboration_artifacts.py`

Nota: la cobertura concreta de tests la confirma WP-2026-122 al ejecutar;
esta lista mapea los tests existentes de los modulos [A]. WP-2026-122 puede
anadir tests nuevos para `resolve_project_root()`.

---

## Riesgos y orden de implementacion sugerido

1. **Primero la funcion central** `resolve_project_root()` + tests propios.
2. **Hooks** (`stop_hook.py`): fallback por `AGENT_PROJECT_ROOT`. Riesgo alto
   si el launcher no inyecta la variable -> validar el launcher en el mismo paso.
3. **Entry points CLI** (`agent_controller.py`, `ticket_supervisor.py`,
   `manager_review_bridge.py`): anadir `--project-root`.
4. **Scripts [A] restantes**: migrar a `resolve_project_root()`.
5. **`launch_agent_terminals.ps1`**: alimentar `--project-root` /
   `AGENT_PROJECT_ROOT` apuntando al workspace destino.
6. **Validacion**: ejecutar la pipeline contra un proyecto destino fixture y
   confirmar que sin parametros el comportamiento por defecto no cambia.

### Aclaracion de scope confirmada

- `bus/event_bus.py`, `bus/supervisor.py`, `bus/review_bridge.py`: **no
  necesitan cambios internos** (ya inyectados).
- Categoria [B] (instalador): se aborda en WP-B, no en WP-2026-122.
- Categoria [E] (engine-rooted): permanece anclada al motor, no cambia.
