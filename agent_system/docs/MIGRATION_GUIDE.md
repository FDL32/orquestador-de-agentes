# MIGRATION_GUIDE.md - GuÃ­a de MigraciÃ³n a Modelo con Manifests

## PropÃ³sito y Alcance

Esta guÃ­a proporciona instrucciones operativas para migrar proyectos legacy al modelo de manifests multiagente. El modelo introduce `project_manifest.toml` como contrato estable y `.version_manifest.json` como estado tÃ©cnico, reemplazando la detecciÃ³n por markers legacy.

**Alcance:**
- Proyectos existentes sin manifests.
- Proyectos con manifests parciales.
- No cubre instalaciÃ³n inicial ni proyectos ya canÃ³nicos.

**Consistencia:**
- Alineada con `.claude/rules/06-project-manifest-architecture.md`.
- Compatible con `agent_system/docs/MANIFEST_SPEC.md`.

## DefiniciÃ³n de Proyecto Legacy

Un proyecto legacy es aquel que no usa manifests como autoridad primaria:

- **Sin `project_manifest.toml`**: Proyecto sin contrato establecido. Relies en detecciÃ³n heurÃ­stica de rutas y configuraciÃ³n.
- **Con solo `.version_manifest.json`**: Tiene estado tÃ©cnico pero falta contrato. Puede estar en drift si rutas cambiaron.
- **Con solo markers legacy**: Archivos indicadores (e.g., `.agent/agent_controller.py`, hooks/) sin manifests. Requiere migraciÃ³n completa.

Proyectos legacy operan con markers legacy como fallback, pero no son compatibles con el modelo completo de autoridad.

## Flujo Operativo de MigraciÃ³n

Sigue un proceso de 4 pasos para migrar de forma segura:

1. **Detect**: Identificar estado actual del proyecto usando herramientas de diagnÃ³stico.
2. **Assess**: Evaluar compatibilidad, drift y acciones necesarias.
3. **Repair**: Aplicar cambios para establecer manifests y corregir inconsistencias.
4. **Validate**: Verificar que la migraciÃ³n sea exitosa y el proyecto opere correctamente.

El flujo es iterativo; regresa a detect si surgen problemas.

## Comportamiento de Herramientas

### `doctor_agent_system.py`
- **PropÃ³sito**: DiagnÃ³stico no invasivo del estado del sistema.
- **Acciones**: Lee estado actual, valida consistencia, reporta problemas sin modificar archivos.
- **Salida**: Reporte con recomendaciones para migraciÃ³n.
- **Uso**: Primer paso en detect/assess.

### `doctor_agent_system.py --repair-manifest`
- **PropÃ³sito**: Crear manifests bÃ¡sicos desde markers legacy.
- **Acciones**: Genera `project_manifest.toml` y `.version_manifest.json` basados en estructura detectada. Actualiza status a "recovered", confidence a "recovered_from_markers".
- **Limitaciones**: No mueve archivos ni cambia estructura. No destructivo.
- **Uso**: Paso repair para proyectos sin manifests.

### `upgrade_agent_system.py --dry-run`
- **PropÃ³sito**: Simular upgrade sin cambios.
- **Acciones**: Valida manifests existentes contra versiones disponibles, reporta drift y conflictos.
- **Salida**: Reporte detallado de cambios necesarios.
- **Uso**: Paso assess para evaluar riesgos.

### `upgrade_agent_system.py --confirm`
- **PropÃ³sito**: Aplicar upgrade con cambios estructurales.
- **Acciones**: Actualiza `.version_manifest.json`, corrige drift reparable, migra schema si necesario. Bloquea y falla en drift crÃ­tico o ambigÃ¼edades que requieran intervenciÃ³n manual.
- **Requisitos**: Manifests presentes; falla si faltan o hay ambigÃ¼edades crÃ­ticas.
- **Uso**: Paso repair para upgrades reales; no aplica a todos los casos de drift.

### `migrate_legacy_project.py --auto`
- **PropÃ³sito**: MigraciÃ³n automÃ¡tica no destructiva.
- **Acciones**: DiagnÃ³stica, reporta, genera manifests base si faltan. No mueve archivos, no consolida carpetas, no cambia estructura.
- **Limitaciones**: Solo acciones seguras; requiere --confirm para cambios estructurales.
- **Uso**: AutomatizaciÃ³n de detect/assess/repair bÃ¡sica.

### `migrate_legacy_project.py --confirm`
- **PropÃ³sito**: MigraciÃ³n completa con cambios estructurales.
- **Acciones**: Ejecuta consolidaciÃ³n de `.agent/`, movimiento de archivos, correcciÃ³n de rutas en drift, upgrade de schema.
- **Requisitos**: Usuario confirma acciones destructivas.
- **Uso**: Paso final para migraciones completas.

## Regla ExplÃ­cita: --auto vs --confirm

- **`--auto`**: Modo diagnÃ³stico y repair bÃ¡sico. Solo diagnostica, reporta problemas, genera manifests base no destructivos. No realiza cambios estructurales, movimientos de archivos o consolidaciones. Seguro para ejecutar automÃ¡ticamente.
- **`--confirm`**: Modo de cambios reales. Obligatorio para acciones destructivas como mover carpetas, cambiar rutas, consolidar `.agent/`, o upgrades que modifiquen estructura. Requiere confirmaciÃ³n explÃ­cita del usuario.

## Casos de Error y ResoluciÃ³n

### MÃºltiples `.agent/`
- **SÃ­ntoma**: MÃ¡s de una carpeta `.agent/` en el proyecto.
- **Causa**: Migraciones parciales o conflictos de versiones.
- **ResoluciÃ³n**: `migrate_legacy_project.py --auto` reporta conflicto. Requiere `--confirm` para consolidar en una sola carpeta canÃ³nica.

### Rutas en Drift
- **SÃ­ntoma**: Rutas detectadas no coinciden con manifests existentes.
- **Causa**: Cambios manuales post-manifest.
- **ResoluciÃ³n**: `upgrade_agent_system.py --dry-run` identifica drift. `--confirm` corrige rutas y actualiza manifests.

### `project_manifest.toml` Presente pero `.version_manifest.json` Ausente
- **SÃ­ntoma**: Contrato existe pero falta estado tÃ©cnico.
- **Causa**: Proyecto parcialmente inicializado.
- **ResoluciÃ³n**: `doctor_agent_system.py --repair-manifest` genera `.version_manifest.json` con status "recovered", confidence "recovered_from_markers".

### `.version_manifest.json` Presente pero Contrato Ausente
- **SÃ­ntoma**: Estado tÃ©cnico existe pero falta contrato.
- **Causa**: Upgrade incompleto o migraciÃ³n parcial.
- **ResoluciÃ³n**: `migrate_legacy_project.py --auto` genera `project_manifest.toml` desde estado existente y markers.

## Significado de Estados

### Status (en .version_manifest.json)
- **canonical**: InstalaciÃ³n estÃ¡ndar, sin modificaciones manuales. Alta confianza.
- **recovered**: Proyecto reparado desde markers legacy. Requiere verificaciÃ³n.
- **unknown**: Estado no determinado. Requiere diagnÃ³stico.

### Confidence (en .version_manifest.json)
- **high**: InformaciÃ³n validada, origen confiable.
- **medium**: InformaciÃ³n parcialmente validada.
- **low**: InformaciÃ³n limitada, posible inconsistencia.
- **recovered_from_markers**: Origen no-canÃ³nico, generado desde estructura detectada.

## Ejemplos de MigraciÃ³n Paso a Paso

### Ejemplo 1: Proyecto Legacy Sin Manifests

1. **Detect**: `doctor_agent_system.py` reporta "Proyecto legacy: sin manifests, markers detectados".
2. **Assess**: `migrate_legacy_project.py --auto` confirma estructura vÃ¡lida, recomienda generar manifests.
3. **Repair**: `doctor_agent_system.py --repair-manifest` crea `project_manifest.toml` y `.version_manifest.json` con status "recovered", confidence "recovered_from_markers".
4. **Validate**: `doctor_agent_system.py` confirma manifests presentes, sin drift.

### Ejemplo 2: Proyecto con Drift de Rutas

1. **Detect**: `upgrade_agent_system.py --dry-run` reporta "Drift detectado: scripts_dir no coincide".
2. **Assess**: Evaluar si drift es intencional o error.
3. **Repair**: `upgrade_agent_system.py --confirm` corrige rutas en manifests y actualiza `.version_manifest.json`.
4. **Validate**: Verificar que rutas coincidan y herramientas operen correctamente.

### Ejemplo 3: MÃºltiples `.agent/`

1. **Detect**: `migrate_legacy_project.py --auto` reporta "MÃºltiples .agent/ detectadas".
2. **Assess**: Usuario decide cuÃ¡l es canÃ³nica.
3. **Repair**: `migrate_legacy_project.py --confirm` consolida en una carpeta, actualiza manifests.
4. **Validate**: Confirmar una sola `.agent/`, manifests actualizados.

## Checklist Final de ValidaciÃ³n Post-MigraciÃ³n

- [ ] `project_manifest.toml` presente y vÃ¡lido segÃºn `MANIFEST_SPEC.md`.
- [ ] `.version_manifest.json` presente con status apropiado (canonical o recovered).
- [ ] Rutas en manifests coinciden con estructura real del proyecto.
- [ ] No mÃºltiples `.agent/` ni carpetas legacy.
- [ ] `doctor_agent_system.py` reporta estado vÃ¡lido sin errores crÃ­ticos (acepta "Proyecto canÃ³nico" o "Proyecto recovered" segÃºn caso).
- [ ] `upgrade_agent_system.py --dry-run` no reporta drift crÃ­tico.
- [ ] Herramientas operan correctamente (orquestador, agent_controller).
- [ ] Logs de seguridad limpios (sin WRITE_BLOCKED o BASH_BLOCKED).
- [ ] Tests pasan si aplicable (`run_pytest_safe.py`).

Si el checklist falla, regresar a detect y repetir flujo.
