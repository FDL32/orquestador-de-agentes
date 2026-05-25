# MANIFEST_SPEC.md - Especificación Técnica del Sistema de Manifiestos

## Introducción

Esta especificación define el contrato técnico para los manifiestos del sistema multiagente. Los manifiestos aseguran consistencia, detección automática y upgrade seguro entre proyectos y versiones del sistema.

- **Versión mínima del sistema**: 8.0 (soporte inicial de manifiestos).
- **Ubicación**: `.agent/project_manifest.toml` y `.agent/.version_manifest.json`.
- **Autoridad**: `.agent` gobierna todos los aspectos; conflictos se resuelven priorizando el manifest.

## project_manifest.toml

Contrato estable del proyecto. Define configuración canónica, rutas y dependencias. No se modifica con upgrades del sistema.

### Campos y Tipos

| Campo | Tipo | Obligatorio | Descripción | Validaciones |
|-------|------|-------------|-------------|--------------|
| [project] | Sección | Sí | Información básica del proyecto | |
| project.id | String | Sí | Identificador técnico estable | Sin espacios, usado por tooling |
| project.name | String | Sí | Nombre legible humano | Alfanumérico, con espacios permitidos |
| project.version | String | Sí | Versión semántica del proyecto | Formato SemVer (e.g., "1.0.0") |
| project.type | String | No | Tipo de proyecto | e.g., "python_app", "web_app" |
| project.created_from | String | No | Origen de creación | e.g., "orquestador_de_agentes" |
| project.description | String | No | Descripción breve | Máximo 200 caracteres |
| [paths] | Sección | Sí | Rutas canónicas | Todas relativas al root |
| paths.root | String | Sí | Directorio raíz | Siempre "." |
| paths.agent_dir | String | Sí | Directorio del sistema agente | Siempre ".agent" |
| paths.claude_dir | String | No | Directorio de integración Claude | ".claude" por defecto |
| paths.scripts_dir | String | No | Directorio de scripts | "scripts" por defecto |
| paths.tests_dir | String | No | Directorio de tests | "tests" por defecto |
| paths.src_dir | String | No | Directorio fuente | "src" por defecto |
| [dependencies] | Sección | No | Dependencias del proyecto | |
| dependencies.python | String | No | Versión mínima de Python | Formato ">=3.10" |
| dependencies.frameworks | Array<String> | No | Frameworks principales | Lista de nombres |
| [security] | Sección | Sí | Configuración de seguridad | |
| security.allowlist | Array<String> | Sí | Rutas permitidas | Patrones glob (e.g., ["scripts/", "src/"]) |
| security.denylist | Array<String> | Sí | Rutas bloqueadas | Patrones glob (e.g., ["privada/", ".env"]) |
| [metadata] | Sección | No | Metadatos opcionales | |
| metadata.created_at | String | No | Fecha de creación | Formato ISO 8601 |
| metadata.updated_at | String | No | Fecha de última actualización | Formato ISO 8601 |
| [agents] | Sección | No | Agentes externos permitidos | |
| agents.allowed | Array<String> | No | Lista de agentes externos autorizados | Nombres válidos (e.g., ["claude", "codex"]) |
| [quality_gates] | Sección | No | Configuración de quality gates | |
| quality_gates.unit_tests | Boolean | No | Ejecutar unit tests | true/false |
| quality_gates.integration_tests | Boolean | No | Ejecutar integration tests | true/false |
| quality_gates.linting | Boolean | No | Ejecutar linting | true/false |
| [agent_system] | Sección | No | Compatibilidad con sistema multiagente | |
| agent_system.min_version | String | No | Versión mínima requerida | SemVer (e.g., "8.0.0") |
| agent_system.max_version | String | No | Versión máxima soportada | SemVer o patrón (e.g., "9.x") |
| agent_system.upgrade_channel | String | No | Canal de actualización | Valores: "stable", "beta", "nightly" |

### Validaciones Generales

- Todos los paths son relativos al root del proyecto.
- No incluir rutas absolutas ni personales.
- No incluir secretos, tokens o credenciales.
- Array<String> para listas, con elementos no vacíos.
- Strings sin caracteres de control.

### Valores Permitidos

- project.id: Sin espacios, alfanumérico con guiones bajos.
- project.version: SemVer válido.
- project.type: Valores comunes: "python_app", "web_app", etc.
- paths.root: Siempre ".".
- paths.agent_dir: Siempre ".agent".
- security.allowlist/denylist: Patrones válidos para pathlib.glob.
- agents.allowed: Lista de nombres de agentes externos válidos.
- quality_gates.*: true/false.
- agent_system.min_version/max_version: SemVer válido o patrón.
- agent_system.upgrade_channel: "stable", "beta", "nightly".

## .version_manifest.json

Estado técnico del sistema instalado. Registra versiones, status y confidence. Actualizado automáticamente por herramientas.

### Campos y Tipos

| Campo | Tipo | Obligatorio | Descripción | Validaciones |
|-------|------|-------------|-------------|--------------|
| agent_core_version | String | Sí | Versión del núcleo agente | SemVer |
| template_version | String | Sí | Versión de la plantilla | SemVer |
| status | String | Sí | Estado del sistema | Valores: "canonical", "recovered", "unknown" |
| confidence | String | Sí | Nivel de certidumbre | Valores: "high", "medium", "low", "recovered_from_markers" |
| last_updated | String | Sí | Timestamp de última actualización | ISO 8601 con timezone |
| components | Object | Sí | Versiones de componentes | |
| components.agent_controller | String | Sí | Versión del controlador | SemVer |
| components.hooks | String | Sí | Versión de hooks | SemVer |
| components.rules | String | Sí | Versión de reglas | SemVer |
| markers_validated | Boolean | Sí | Si markers legacy fueron validados | true/false |
| drift_detected | Boolean | Sí | Si se detectó drift | true/false |

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "agent_core_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "template_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "status": {
      "type": "string",
      "enum": ["canonical", "recovered", "unknown"]
    },
    "confidence": {
      "type": "string",
      "enum": ["high", "medium", "low", "recovered_from_markers"]
    },
    "last_updated": {
      "type": "string",
      "format": "date-time"
    },
    "components": {
      "type": "object",
      "properties": {
        "agent_controller": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$"
        },
        "hooks": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$"
        },
        "rules": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$"
        }
      },
      "required": ["agent_controller", "hooks", "rules"]
    },
    "markers_validated": {
      "type": "boolean"
    },
    "drift_detected": {
      "type": "boolean"
    }
  },
  "required": [
    "agent_core_version",
    "template_version",
    "status",
    "confidence",
    "last_updated",
    "components",
    "markers_validated",
    "drift_detected"
  ]
}
```

### Validaciones Generales

- Todas las versiones en formato SemVer (e.g., "1.0.0").
- last_updated en formato ISO 8601 con timezone (e.g., "2026-04-28T21:42:57+02:00").
- No incluir rutas absolutas ni secretos.
- Status y confidence separados: status indica estado, confidence indica certidumbre.

### Valores Permitidos

- status: "canonical" (instalación estándar), "recovered" (reparado), "unknown" (no determinado).
- confidence: "high" (alta certidumbre), "medium", "low", "recovered_from_markers" (origen no-canónico).

## Reglas de Autoridad

### Para Rutas

- project_manifest.toml prevalece: Cualquier detección heurística debe coincidir.
- Discrepancias = drift: Reportar como WARNING, sugerir repair.
- Repair con doctor --repair-manifest o upgrade --confirm: Actualiza status a "recovered", confidence a "recovered_from_markers".

### Para Status y Confidence

- Solo herramientas autorizadas (upgrade, doctor --repair-manifest, migrate) pueden modificar.
- Status refleja estado real del sistema.
- Confidence refleja origen y validación de la información.
- Cambios auditados en execution_log.md con timestamp.

### Autoridad General

- .agent es autoridad única para manifests y estado técnico.
- .claude consume pero no modifica.
- Conflicto: Priorizar .agent; regenerar .claude si diverge.

## Compatibilidad Futura

- **Versión mínima**: Sistema 8.0 soporta manifiestos; versiones anteriores usan markers legacy.
- **Backward compatibility**: Manifests antiguos válidos si cumplen schema mínimo.
- **Forward compatibility**: Nuevos campos opcionales; herramientas ignoran desconocidos.
- **Upgrade path**: doctor_agent_system.py detecta versiones, upgrade_agent_system.py migra schema.
- **Deprecation**: Campos obsoletos marcados en changelog; removidos en versiones mayores.

## Ejemplos

### project_manifest.toml Completo

```toml
[project]
id = "mi_proyecto"
name = "Mi Proyecto"
version = "1.0.0"
type = "python_app"
created_from = "orquestador_de_agentes"
description = "Proyecto multiagente de ejemplo"

[paths]
root = "."
agent_dir = ".agent"
claude_dir = ".claude"
scripts_dir = "scripts"
tests_dir = "tests"
src_dir = "src"

[dependencies]
python = ">=3.10"
frameworks = ["fastapi", "pydantic"]

[security]
allowlist = ["scripts/", "src/"]
denylist = ["privada/", ".env"]

[metadata]
created_at = "2026-04-28T21:42:57+02:00"
updated_at = "2026-04-28T21:42:57+02:00"

[agents]
allowed = ["claude", "codex"]

[quality_gates]
unit_tests = true
integration_tests = false
linting = true

[agent_system]
min_version = "8.0.0"
max_version = "9.x"
upgrade_channel = "stable"
```

### .version_manifest.json Completo

```json
{
  "agent_core_version": "8.2.0",
  "template_version": "1.0.0",
  "status": "canonical",
  "confidence": "high",
  "last_updated": "2026-04-28T21:42:57+02:00",
  "components": {
    "agent_controller": "1.0.0",
    "hooks": "1.0.0",
    "rules": "1.0.0"
  },
  "markers_validated": true,
  "drift_detected": false
}
```
