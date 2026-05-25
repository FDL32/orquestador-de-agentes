# Agent System Upgrade + Cleanup Guide

Guía completa para actualizar un proyecto existente con la nueva versión del sistema multi-agente Manager+Builder, incluyendo limpieza automática de archivos legacy.

## Flujo de 4 Pasos

### 1. Detectar Versión Actual

```powershell
cd C:\tu\proyecto
python scripts/detect_version.py .
```

### 2. Validar con Dry-Run

```powershell
python scripts/upgrade.py . --dry-run
```

### 3. Ejecutar Upgrade

```powershell
python scripts/upgrade.py . --confirm
```

### 4. Limpiar Archivos Legacy (NUEVO)

```powershell
python scripts/cleanup_legacy.py . --list-only
python scripts/cleanup_legacy.py . --dry-run
python scripts/cleanup_legacy.py . --confirm
```

## Flujo Completo Recomendado

```powershell
# Validar cambios actuales en Git
git status

# Detectar versión
python scripts/detect_version.py .

# Simular upgrade
python scripts/upgrade.py . --dry-run

# Ejecutar upgrade
python scripts/upgrade.py . --confirm

# Simular cleanup
python scripts/cleanup_legacy.py . --dry-run

# Ejecutar cleanup
python scripts/cleanup_legacy.py . --confirm

# Validar sistema nuevo
python .agent/agent_controller.py --validate --json --force

# Tests
python scripts/run_pytest_safe.py tests/unit -q
```

## Archivos que Limpia cleanup_legacy.py

### SAFE_REMOVE (sin riesgo):
- scripts/detect_agent_system_version.py
- scripts/test_goose_realworld.py
- debug_output.txt, output.txt, temp_output.txt
- .ruff_cache/, __pycache__/

### REVIEW_BEFORE_REMOVE (revisar primero):
- .agent/legacy/
- .agent/backups/ (se elimina por completo; copia lo que quieras conservar antes de ejecutar --confirm)

### ARCHIVE (guardar copia):
- UPGRADE_GUIDE.md -> `.session/archive/UPGRADE_GUIDE.md`

### Notas operativas

- `cleanup_legacy.py --confirm` elimina `SAFE_REMOVE`, archiva `UPGRADE_GUIDE.md` dentro de `.session/archive/` y escribe `.session/cleanup_log.md`.
- `cleanup_legacy.py --confirm` también elimina `.agent/legacy/`, `.agent/backups/`, `test_logs/` y `graphify-out/cache/` si existen.
- La limpieza excluye `.venv/`, `node_modules/`, `.git/` y `tests/sandbox/` para no tocar dependencias ni temporales de prueba.
- `cleanup_legacy.py --dry-run` y `--list-only` no modifican el árbol.
- Si quieres conservar algún backup para rollback, sáltate `--confirm` hasta copiarlo fuera del árbol del proyecto.

## Rollback de Emergencia

Si algo falla:

```powershell
python scripts/rollback.py --backup backup_20260427_093000
```

## Troubleshooting

| Problema | Solución |
|----------|----------|
| "Permission denied" en Windows | Cierra IDE/editor y reintenta |
| Upgrade muy lento | Espera 2-3 min (venv es grande) |
| Quiero ver qué cambió | Lee .session/upgrade_log.md |
| Quiero ver qué limpió | Lee .session/cleanup_log.md |

## Resumen de auditoría

### Objetivo de la limpieza

Preparar `orquestador_de_agentes/` para clonarlo en un nuevo proyecto sin arrastrar estado operativo, logs de ejecución ni residuos temporales del entorno anterior.

### Elementos limpiados

- Estado operativo: `TURN.md`, `work_plan.md`, `execution_log.md`, `notifications.md`, `STATE.md`
- Runtime: `events.jsonl`, `supervisor_state.json`, `ui_state.json`, `manager_bridge_state.json`, `status_bar.json`, `codex_review_*.md`
- Cachés y residuos: `__pycache__`, `.ruff_cache`, `.agent/legacy`, `.agent/backups`, `graphify-out/cache`
- Documentación obsoleta: `UPGRADE_GUIDE.md` archivado en `.session/archive/UPGRADE_GUIDE.md`

### Cambios en el sistema

- `scripts/cleanup_legacy.py` ahora realiza limpieza real en `--confirm`, archiva documentación y escribe `.session/cleanup_log.md`.
- `tests/conftest.py` fuerza `tmp_path` y `tmp_path_factory` a usar runtime propio del proyecto.
- `tests/README.md` documenta `python scripts/run_pytest_safe.py` como runner oficial en Windows.

### Validación

- `python scripts/cleanup_legacy.py . --dry-run`
- `python scripts/run_pytest_safe.py tests/unit/test_cleanup_legacy.py tests/unit/test_windows_safe_temp_runtime.py -q`
- `python .agent/agent_controller.py --validate --json --force`

### Resultado

- La plantilla queda copy-ready.
- El siguiente proyecto debe iniciar con un ciclo de planificación nuevo.
- El runner seguro debe usarse para pruebas normales en Windows.
- Las pruebas de respaldo existen y pasan: `tests/unit/test_cleanup_legacy.py` y `tests/unit/test_windows_safe_temp_runtime.py`.
