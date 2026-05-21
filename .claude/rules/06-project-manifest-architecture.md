# 06 - Project Manifest Architecture



## Propósito del Contrato de Proyecto Multiagente



El contrato de proyecto multiagente define las reglas estables para identificar, versionar y operar proyectos que usan el sistema `.agent`. Este contrato asegura consistencia entre proyectos, agentes y herramientas, permitiendo detección automática, migración legacy y upgrade sin ambigüedades.



- **`.agent` es la autoridad del sistema**: Contiene manifests, estado técnico, runtime, hooks y reglas del sistema multiagente.

- **`.claude` es la capa de integración**: Consume el contrato desde `.agent`, expone settings, commands y agentes nativos para Claude Code.



Los agentes deben leer el contrato primero cuando exista, priorizando rutas canónicas sobre detección heurística.



## Diferencia entre Manifests



- **`project_manifest.toml`**: Contrato estable del proyecto. Define rutas canónicas, dependencias y configuración. No cambia con upgrades del sistema. Es fuente de verdad para rutas y estructura.

- **`.version_manifest.json`**: Estado técnico del sistema instalado. Registra versiones, status y confidence. Se actualiza automáticamente por herramientas de upgrade/detect. No contiene rutas absolutas ni secretos.



## Tabla de Responsabilidades



| Responsabilidad | `.agent` (Autoridad) | `.claude` (Integración) | No en ninguna capa |

|-----------------|----------------------|-------------------------|-------------------|

| Manifests del proyecto | ✅ `project_manifest.toml` | âŒ | âŒ |

| Estado técnico del sistema | ✅ `.version_manifest.json` | âŒ | âŒ |

| Runtime y hooks | ✅ `agent_controller.py`, hooks/ | âŒ | âŒ |

| Reglas del sistema | ✅ `rules/` | âŒ | âŒ |

| Estado de colaboración | ✅ `collaboration/` | âŒ | âŒ |

| Settings Claude Code | âŒ | ✅ `config.json` | âŒ |

| Commands slash | âŒ | ✅ `commands/` | âŒ |

| Agentes nativos | âŒ | ✅ `agents/` | âŒ |

| Reglas de consumo | âŒ | ✅ `rules/` | âŒ |

| Secretos | âŒ | âŒ | ✅ |

| Rutas absolutas personales | âŒ | âŒ | ✅ |

| Estado canónico del proyecto | ✅ | âŒ | âŒ |

| Versionado técnico | ✅ | âŒ | âŒ |



## Regla de Autoridad



- **`.agent` gobierna**: Manifests, estado técnico, colaboración y reglas del sistema. Si hay conflicto entre capas, la autoridad del proyecto vive en `.agent`.

- **`.claude` consume**: Lee el contrato desde `.agent` para exponer integración con Claude Code. No almacena estado canónico ni versionado técnico.

- **Conflicto resolución**: Priorizar `.agent`. Si `.claude` contiene estado divergente, regenerar desde `.agent`.



## Orden de Autoridad para Detección



Cuando un agente o herramienta necesita identificar el proyecto:



1. Leer `.agent/project_manifest.toml` (contrato estable, prevalece sobre todo).

2. Leer `.agent/.version_manifest.json` (estado técnico actual).

3. Detección por markers legacy (fallback para proyectos sin manifest).

4. Proyecto no inicializado (requiere setup manual).



No saltar pasos; usar el primer manifest disponible para determinar rutas canónicas.



## Comportamiento Esperado por Herramienta



### `doctor_agent_system.py`

- Tolerante: Diagnóstica legacy, recomienda migración.

- Lee manifests existentes, valida status y confidence.

- Genera reportes sin modificar estado (modo diagnóstico).

- Si faltan manifests, sugiere creación.

- Modo `--repair-manifest`: Crea manifests básicos desde markers legacy, actualizando status a "recovered" y confidence a "recovered_from_markers".



### `upgrade_agent_system.py --dry-run`

- Simula cambios sin modificar archivos.

- Valida manifests contra versiones disponibles.

- Reporta drift, conflictos y acciones necesarias.

- No requiere manifests para dry-run.



### `upgrade_agent_system.py --confirm`

- Estricto: Bloquea si faltan manifests, hay rutas ambiguas o existe drift crítico.

- Actualiza `.version_manifest.json` con nuevo status/confidence.

- Crea backups antes de cambios destructivos.

- Falla si markers legacy no coinciden con manifest.



### `orquestador.py`

- Lee `project_manifest.toml` para rutas canónicas.

- Valida estado desde `.version_manifest.json`.

- Construye contexto usando allowlist/denylist desde manifest.

- Registra ejecución en `execution_log.md`.



## Política de Rutas



- El manifest prevalece: Rutas detectadas heurísticamente deben coincidir con `project_manifest.toml`.

- Discrepancias son drift: Herramientas deben reportar como WARNING y sugerir repair.

- Repair automático: Solo con `--confirm`, actualizando status a "recovered" y confidence a "recovered_from_markers".



## Política de Repair



- **Status**: "recovered" para proyectos reparados desde markers legacy.

- **Confidence**: "recovered_from_markers" para indicar origen no-canónico.

- **Acciones**: Solo herramientas autorizadas (upgrade, migrate) pueden cambiar status/confidence.

- **Auditoría**: Cambios se registran en `execution_log.md` con timestamp y herramienta.

- **--auto no destructivo**: Modos `--auto` (como en migrate_legacy_project.py) solo diagnostican y generan reportes; cambios destructivos requieren `--confirm`.



## Advertencia de Seguridad



- No incluir secretos, tokens, contraseñas ni rutas absolutas personales en manifests.

- `.version_manifest.json` debe ser commiteado y sanitizado.

- Hooks de seguridad bloquean writes en rutas sensibles; eventos se registran en `.agent/logs/security.log`.



## Regla Explícita para Claude Code



`.claude` no almacena estado canónico del proyecto ni versionado técnico. Todo estado debe residir en `.agent`. Claude Code lee desde `.agent` para integración, pero no gobierna el sistema multiagente.



## Ejemplo TOML: `project_manifest.toml`



```toml

[project]

name = "mi_proyecto"

version = "1.0.0"

description = "Descripción del proyecto"



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

created_at = "2026-04-28"

updated_at = "2026-04-28"

```



## Ejemplo JSON: `.version_manifest.json`



```json

{

  "agent_core_version": "8.2",

  "template_version": "1.0",

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
