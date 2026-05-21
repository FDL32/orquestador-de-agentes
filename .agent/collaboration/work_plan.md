# Plan de Trabajo: WP-2026-123 - Workspace minimo del destino

## Metadata
- **ID:** WP-2026-123
- **Estado:** APPROVED
- **deliverable_type:** code
- **Creado:** 2026-05-21
- **Prioridad:** HIGH
- **Asignado a:** Builder
- **Backend:** OpenCode
- **Tipo:** IMPLEMENTATION

---

## Objetivo

Hacer que el instalador mantenga en el proyecto destino solo el `.agent/`
minimo, sin copiar el motor, y que ademas escriba un archivo de enlace
motor-destino para dejar trazabilidad portable del workspace instalado.

## Contexto

WP-2026-122 ya dejo resuelto el desacople de `project_root` en el motor.
Tambien ya existe en `install_agent_system.py` la logica de copia allowlist-
driven del destino y la proteccion contra copiar codigo del motor operativo.
WP-2026-123 no reescribe eso: publica el contrato faltante del enlace y ajusta
el allowlist para conservarlo en el destino.

La base existente ya aporta:

- `MANIFEST.workspace` con la lista de superficies que deben quedar en el
  destino.
- `scripts/install_agent_system.py` con copia allowlist-driven y flip de
  `active_profile` a `host-project`.
- `README.md` y `PROJECT.md` con la arquitectura de motor central + destino.

La pieza que falta definir es el contrato de enlace motor-destino. El WP-B lo
introduce como un artefacto generado por el instalador dentro del destino:

- `.agent/config/motor_destination_link.json`

Schema propuesto del enlace:

- `motor_root`: ruta al motor externo, absoluta o derivada de entorno.
- `destination_root`: ruta raiz del destino instalado.
- `motor_version`: version tecnica del motor que esta consumiendo el destino.
- `destination_id`: identificador estable del destino o workspace.
- `created_at`: timestamp ISO-8601 UTC de la instalacion o sync.
- `manifest_version`: version del contrato `MANIFEST.workspace` aplicado.

## Files Likely Touched

### Codigo

- `scripts/install_agent_system.py`
- `MANIFEST.workspace`

### Documentacion

- `README.md`
- `PROJECT.md`

### Tests

- `tests/unit/test_install_agent_system.py`
- `tests/unit/test_workspace_manifest.py`

## Plan

### Fase 1: Contrato del workspace minimo

- Definir el schema del archivo `.agent/config/motor_destination_link.json`.
- Alinear `MANIFEST.workspace` para conservar el link generado y las
  superficies minimas que deben existir tras `--install` / `--sync`.
- Mantener `agents.json` como configuracion del destino y `active_profile`
  como `host-project`.

### Fase 2: Instalador

- Hacer que `scripts/install_agent_system.py` cree el arbol minimo de `.agent/`
  en el destino.
- Escribir el archivo de enlace motor-destino en `.agent/config/`.
- Evitar la copia del motor operativo en cualquier modo canonical.

### Fase 3: Documentacion y tests

- Actualizar `README.md` y `PROJECT.md` con el contrato del workspace minimo.
- Anadir o ajustar tests del instalador y del allowlist de `MANIFEST.workspace`.
- Verificar que el sync/install sigue siendo idempotente.

### Fase 4: Validacion

- `ruff check .`
- `pytest` en el slice afectado
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de Aceptacion

- [ ] El destino crea solo el `.agent/` minimo necesario.
- [ ] Se escribe un archivo de enlace motor-destino en `.agent/config/`.
- [ ] El motor operativo no se copia al destino.
- [ ] `MANIFEST.workspace` sigue siendo la fuente de allowlist del destino.
- [ ] `MANIFEST.workspace` conserva el link generado para que sobreviva a
      `--sync --prune`.
- [ ] `active_profile` del destino sigue en `host-project`.
- [ ] Los tests afectados pasan.
- [ ] `ruff check .` pasa limpio.
- [ ] `agent_controller.py --validate` pasa limpio.

## Riesgos

- El cambio puede afectar a la semantica de `--install` y `--sync`.
- Hay que evitar duplicar en el destino metadatos del motor que ya existen en
  el repo central.
- El archivo de enlace debe ser estable y no depender de rutas locales
  temporales.
