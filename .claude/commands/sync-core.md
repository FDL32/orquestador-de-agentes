# Sync Agent Core — Sincronización Portable del Núcleo Multi-Agente

## Descripción
Sincroniza el directorio `.agent/` desde la plantilla canónica `orquestacion_agentes/` hacia la instancia local. **Por política de "sin drift", `--strict-sync` es el comportamiento por defecto:** elimina automáticamente archivos residuales que no existen en la plantilla.

Preserva la sesión activa (`collaboration/`, `runtime/`) y valida integridad del sistema.

## Cuándo usarlo
- Antes de iniciar un nuevo ciclo de trabajo
- Después de actualizar la plantilla `orquestacion_agentes/`
- Para validar y asegurar coherencia del sistema multi-agente
- En proyectos recién clonados sin `.agent/` configurado

## Uso
```bash
# ✅ Por defecto: sync + strict (elimina residuos automáticamente)
python orquestacion_agentes/scripts/install_agent_system.py --sync

# 📋 Vista previa (dry-run, no modifica nada)
python orquestacion_agentes/scripts/install_agent_system.py --sync --dry-run

# 🤔 Interactivo: pregunta cuáles residuos eliminar
python orquestacion_agentes/scripts/install_agent_system.py --sync --prune

# 🔨 Instalación inicial (solo si .agent/ no existe)
python orquestacion_agentes/scripts/install_agent_system.py --install
```

## Qué hace
1. **Detecta plantilla** — Busca `orquestacion_agentes` automáticamente (descendientes, hermanos, rutas comunes)
2. **Sincroniza** — Copia `.agent/` desde plantilla, preservando LOCAL_DIRS (`collaboration/`, `runtime/`)
3. **Limpia automáticamente** — Por defecto (`--strict-sync`), elimina residuos de `.agent/` que no están en la plantilla
4. **Valida** — Verifica integridad post-sync (archivos críticos, estructura)
5. **Reporta** — Muestra resumen detallado

## Comportamiento de Sync

### ✅ Por Defecto (`--strict-sync` implícito)
```
Template .agent/ → Project .agent/ (copiar)
                → Detectar residuos (archivos locales que NO están en template)
                → Eliminar todos los residuos automáticamente
                → Validar resultado
```

**Resultado:** `.agent/` es exactamente copia de template (excepto LOCAL_DIRS preservados).

### 📋 Con `--dry-run`
Solo simula cambios sin modificar nada. Útil para ver qué se modificaría.

### 🤔 Con `--prune` (sin `--strict-sync`)
Muestra cada residuo encontrado y pregunta interactivamente cuáles eliminar.

## Directorios Protegidos (Nunca Sincronizados)
- `.agent/collaboration/` — Sesión activa, cambios locales, work_plan.md, execution_log.md
- `.agent/runtime/` — Estado local de runtime, memoria persistente

## Archivos Críticos (Validados Post-Sync)
- `agent_controller.py` (orquestador del sistema)
- `hooks/*.py` (5 hooks de integración Claude Code)
- `rules/` (45 reglas modulares)
- `config/hooks_config.json` (integridad semántica: campos requeridos, tipos correctos)

## Política de "Sin Drift" — Por Qué Strict es Default

El proyecto mantiene una **política explícita de coherencia**: la instancia local de `.agent/` debe ser reflejo exacto de la plantilla canónica (excepto LOCAL_DIRS).

**Razones para `--strict-sync` por defecto:**
- ✅ Previene archivos huérfanos que pueden causar conflictos
- ✅ Asegura que todos usan las mismas reglas, hooks y configuración
- ✅ Reduce surface de ataque (sin residuos legados)
- ✅ Simplifica troubleshooting (estado conocido después de sync)

Si necesitas **preservar cambios locales**, usa `--prune` e indica cuáles residuos mantener.

## Salida Esperada

**Con `--sync` (default/strict):**
```
[SYNC] Agent System from orquestacion_agentes/
[INFO] Template detected: C:\...\orquestacion_agentes
[INFO] Destination:      C:\...\Crear_Texto_LLM
[INFO] Mode:            LIVE
[INFO] Template version: 9.2.1
[INFO] Current project version: 9.2.1
[OK] No destination residues detected.
[OK] Hooks config integrity verified.

[SUCCESS] Agent System synced. Local dirs preserved: collaboration, runtime
```

**Con `--sync --prune` (interactivo):**
```
[WARN] Residues detected: 3
  - legacy/deprecated_rule.md
  - test_logs/old_run.log
  - config/custom_setting.json

[PRUNE] Residues detected:
  1. legacy/deprecated_rule.md
  2. test_logs/old_run.log
  3. config/custom_setting.json

Clean which residues? [all/comma-list/none]: 1,3

[PRUNED] legacy/deprecated_rule.md
[PRUNED] config/custom_setting.json
[SUCCESS] ...
```

## Integración con Claude Code
- Slash command: `/sync-core` → `--sync` (strict por defecto)
- Flags adicionales disponibles: `--dry-run`, `--prune`
- Ejecuta desde raíz del proyecto
- Recomendado antes de iniciar trabajo importante

## Comportamiento Destructivo (Importante)

⚠️ **El comando `--sync` POR DEFECTO ELIMINA ARCHIVOS** en `.agent/` que no existen en la plantilla. Esto es intencional (política "sin drift").

**Qué se elimina:**
- Archivos residuales en `.agent/` (ej: `legacy/deprecated_rule.md`)
- Directorios generados como `__pycache__`, `.tmp`

**Qué se PRESERVA (nunca se toca):**
- `.agent/collaboration/` — sesión activa, work_plan, execution_log
- `.agent/runtime/` — estado local persistente
- Archivos del template (solo se actualiza si hay cambios)

**Cómo prevenir eliminación accidental:**
- Usa `--dry-run` primero para ver qué se eliminaría
- Usa `--prune` para revisar interactivamente cada residuo antes de eliminar
- Mantén backups si tienes datos críticos en `.agent/`

## Troubleshooting
| Problema | Causa | Solución |
|----------|-------|----------|
| "No .agent/ found" | Proyecto sin inicializar | Ejecutar `--install` primero |
| Residuos no se eliminaron | Usaste `--sync` sin `--prune` | Ejecutar con `--prune` si necesitas interactivo |
| "collaboration/ se modificó" | Conflicto de contenido local | Script NO toca `collaboration/`. Revisar permisos o merge manual |
| Validación falla post-sync | Archivos críticos missing en template | Revisar `orquestacion_agentes/.agent/` integridad |

## Comandos Relacionados
- **`--install`** — Instalación inicial (solo si `.agent/` no existe)
- **`--sync --dry-run`** — Vista previa sin modificaciones
- **`--sync --prune`** — Eliminación interactiva de residuos
- **`--sync`** — Sincronización estricta (por defecto)

## Regla Arquitectónica

**Desde v9.4.1+**, el script `install_agent_system.py` reemplaza el viejo `sync_agent_core.py`.

- **Nuevo:** `orquestacion_agentes/scripts/install_agent_system.py` (mantenido, portable)
- **Legacy:** `orquestacion_agentes/scripts/sync_agent_core.py` (deprecado, mantiene compatibilidad)

---

*Sistema multi-agente v9.4.1+ | Política: Sin Drift | WP-2026-040-041*
