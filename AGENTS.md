# AGENTS.md - Instrucciones transversales

## Agentes disponibles

- Claude Code: agente principal y supervisor.
- Codex / GitHub Copilot: agentes soportados si leen este archivo dentro del arbol.
- Goose / Claw: motores orquestados por `scripts/orquestador.py`.

## Resumen del entorno

- Runtime: Python 3.10+, `pathlib`, `typing`.
- Package manager: `uv` (`uv add <lib>`, nunca `pip` directo).
- Testing y calidad: `pytest`, `ruff`.
- Seguridad: `gitleaks`, `pip-audit`.

## Rutas importantes

- `agent_system/`: codigo base de apoyo incluido con la plantilla.
- `scripts/`: utilidades de instalacion, upgrade, rollback y validacion.
- `skills/`: micro-habilidades reutilizables.
- `.agent/collaboration/`: estado operacional canonico — vive en el WORKSPACE del proyecto activo (p.ej. `z_scripts/.agent/collaboration/`), no en el motor. El motor es code-only; apuntar al workspace correcto via `AGENT_PROJECT_ROOT` o `--project-root`.
- `.agent/runtime/memory/`: memoria persistente por proyecto.
- `.agent/council/`: broker de consejo y auditoria paralela.
- `REPOSITORY_STRUCTURE.md`: mapa interno publicable del repositorio.

## Contrato de version y portabilidad

- `pyproject.toml` define la version del paquete portable.
- `.agent/.version_manifest.json` define la version tecnica del core.
- `MANIFEST.distribute` define la frontera del motor central (codigo operativo).
- `MANIFEST.workspace` define el contrato del workspace destino (estado, memoria, config).
- Los comandos canonical y legacy se documentan por separado.
- Estado actual: `v9.14.1` motor central + workspace destino, sesión cerrada con hardening y CHANGELOG completo.
- El motor vive una unica vez en `orquestador_de_agentes/`; los proyectos destino lo referencian externamente.

## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)

Los archivos `MANIFEST.distribute` y `MANIFEST.workspace` en la raiz del repositorio definen el contrato estricto del motor central y el workspace destino:

- **MANIFEST.distribute**: Define la frontera del motor central (codigo operativo del repo fuente). El motor NO se copia; este manifiesto delimita que rutas forman parte del codigo operativo.
- **MANIFEST.workspace**: Define que se conserva EN el workspace destino (estado, memoria, eventos, configuracion del proyecto).
- **Arquitectura**: El motor vive una unica vez en `orquestador_de_agentes/`; cada proyecto destino conserva solo su `.agent/` de workspace y referencia el motor externo.

**Superficies vivas en `.agent/collaboration/`** (NO archivar, el codigo las escribe):
- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md`, `review_queue.md`

**Excluidos del workspace** (historial, runtime transitorio, caches):
- `PLAN_WP-*.md`, `AUDIT_WP-*.md`, `_archive/`, `archive/`
- `.agent/runtime/tmp/`, `uv-cache/`, `test_logs/`, `__pycache__/`, `reviews/`, `compare/`
- `.ruff_cache/`, `.cache/`, `.uv-cache/`, `.venv/`
- Logs y diagnosticos: `debug.log`, `opencode_models_error.log`

## Comandos principales

- Instalacion inicial: `python scripts/install_agent_system.py --install`
- Sincronizacion estricta: `python scripts/install_agent_system.py --sync`
- Sincronizacion interactiva: `python scripts/install_agent_system.py --sync --prune`
- Vista previa: `python scripts/install_agent_system.py --sync --dry-run`
- Estado del sistema: `python .agent/agent_controller.py`
- Auditoria local: `python scripts/local_audit.py`
- Memoria consolidada: `python scripts/memory_consolidate.py [--apply|--dry-run]`
- Migrar config: `python .agent/agents_config.py --migrate [--dry-run]`
- Comparar con repo GitHub: skill `/repo-compare`
- Interaccion por terminal: `python scripts/ticket_supervisor.py --reactive`
- Tests: `python scripts/run_pytest_safe.py`
- Calidad: `ruff check . && ruff format .`
- Auditoria de dependencias: `uv run pip-audit .`
- Archivar colaboracion: `python scripts/archive_collaboration_artifacts.py [--dry-run]`

## Convenciones

- Lee `PROJECT.md` antes de tocar arquitectura o estado.
- Lee `INTERACTION_MODES.md` antes de operar por chat o por terminal.
- Para arrancar una sesion nueva con cualquier agente, usa el bootstrap canonico en `prompts/session_bootstrap.md` (apunta a archivos clave en lugar de embeber).
- Usa `pathlib` y `try/except` explicito para I/O.
- Mantiene la raiz limpia: no metas basura temporal en el arbol portable.
- Usa `.agent/collaboration/work_plan.md` y `.agent/collaboration/execution_log.md` para el estado canonico.

## Archivado de colaboracion (WP-2026-100)

- `scripts/archive_collaboration_artifacts.py` mueve `PLAN_WP-*.md` y `AUDIT_WP-*.md` cerrados a `.agent/collaboration/_archive/plan_audit/`.
- El ticket activo conserva solo sus documentos vivos en `collaboration/`.
- El archivador es idempotente: segunda ejecucion = no-op.
- Usa `--dry-run` para previsualizar sin modificar, `--list-active` para ver archivos activos.

## Superficies vivas vs historicas en `.agent/collaboration/` (WP-2026-107)

No todo lo que parece "viejo" en `collaboration/` es archivable. Distingue:

- **Superficies vivas (NO archivar, las escribe el codigo en cada ciclo):**
  - `archive/`: rotacion de snapshots de `notifications.md`. La escribe
    `agent_controller.py` (`ARCHIVE_DIR`) cada vez que rota la proyeccion.
    NO es legacy; borrarla rompe el controlador.
  - `review_queue.md`: log vivo de reviews del Manager. Le hace append
    `manager_review_bridge.py` (`_record_review`) en cada review.
  - `notifications.md`: proyeccion viva validada por `--validate`. Solo se
    resetea a placeholder, nunca se archiva entera.
- **Superficie historica (`_archive/`):** solo cubre historicos de
  `PLAN_WP-*.md` / `AUDIT_WP-*.md` cerrados (`_archive/plan_audit/`) y
  snapshots legacy no operativos (`_archive/legacy/`). Su contenido puede
  ser un registro unico (p.ej. `_archive/legacy/review_queue.md` conserva
  reviews de WPs que el log vivo ya no tiene): verifica antes de borrar.

Regla: antes de "limpiar" un archivo de `collaboration/`, comprueba si algun
script lo escribe activamente. Si lo hace, es superficie viva.

## Convenciones de docstrings y testing

Adaptado de las directrices operativas open-source en `dify-agent`:

### 1. Docstrings como especificación de ejecución (Docstrings-as-Spec)

Cada función, clase o módulo operativo del sistema debe contar con un docstring claro y estructurado en **3 fases**. El agente o auditor contrastará la firma técnica con esta especificación semántica para asegurar el cumplimiento:
- **Before (Pre-condiciones):** Qué estados, variables, archivos o privilegios requiere la función antes de invocarse.
- **During (Proceso y Recursos):** Cuál es el flujo de transformación de datos, qué efectos colaterales (I/O, llamadas de red) realiza y qué recursos del sistema consume.
- **After (Post-condiciones y Errores):** Qué salidas exactas se garantizan, cómo cambian los estados canónicos y qué excepciones específicas se interceptan y lanzan.

### 2. Rúbrica de testing de alta fidelidad (Test Útil vs Basura)

Para evitar la inflación artificial de cobertura sin validación lógica real, el Builder y los quality gates rechazarán cualquier test cosmético. Se define la siguiente rúbrica de aceptación:
- **Test Inútil (descartable):** Aquel que solo hace aserciones pasivas como `assert obj is not None` o verifica constantes mocked estáticas sin desencadenar lógica real.
- **Test Útil (aceptado):** Aquel que fuerza casos límite (boundary limits), valida transiciones reales de estado (en el Event Bus, archivos de configuración o memoria persistente) y verifica explícitamente el lanzamiento de excepciones esperadas (`pytest.raises`).

**Anti-patrones de test que el Builder debe evitar y el Manager debe rechazar:**
- **Mock drift:** el patch apunta a `X` pero el código llama a `Y` (distinta API). El test pasa sin probar nada real. Ejemplo: parchear `pathlib.Path.open` cuando el código usa el built-in `open()`.
- **Floor assertion:** el umbral de una aserción numérica es satisfecho por el valor base sin la feature probada. Ejemplo: `assert score >= 150` cuando el score de recencia solo ya es `~20_000_000`.

### 3. Anti-patrones de implementación

- **Zero-logic wrapper:** una función cuyo cuerpo completo es una única llamada delegada 1:1 sin lógica propia debe ser inlineada o eliminada. Añade indirección cognitiva sin valor.

## Skills Formales de Proceso

El repositorio define skills operativas formales para estructurar el trabajo del agente.
Úsalas invocando sus triggers (ej. `/tdd`, `/debug`):

- **Test-Driven Development (TDD)** (`skills/test-driven-development/SKILL.md`): Usar para asegurar cobertura y evitar regresiones en código nuevo o fixes. Obliga a escribir el test primero (Red), el código mínimo (Green) y refactorizar con calidad (`ruff` + `pytest`).
- **Systematic Debugging** (`skills/systematic-debugging/SKILL.md`): Usar ante errores no triviales. Exige investigación de causa raíz antes de parchear y establece un límite estricto de 3 intentos antes de detener la iteración y cuestionar el entendimiento del problema.

No uses estos skills si contradicen el flujo general (ej. usar TDD para escribir un README o depuración para un typo reportado por el linter).

## Atribuciones externas (CREDITS.md)

Cuando un WP incorpora una idea/patrón de un repositorio externo:

1. **`repo-compare`** emite al final de su reporte un bloque candidato listo para pegar en `CREDITS.md`.
2. El humano decide cuándo adoptar la idea y pega la fila correspondiente en `CREDITS.md` (raíz del repo).
3. El WP que implementa la idea incluye `Origen externo:` o `Inspired by:` en `work_plan.md`.
4. **`project-finalize` Paso 8d** verifica que la fila CREDITS exista antes de cerrar el WP. Si falta, bloquea el cierre.

Formato: tabla compacta `| WP | Source | Pattern | License | Adapted vs Ported |`. Detalle en `CREDITS.md`.

**Limitación conocida:** `CREDITS.md` vive en raíz; `scripts/install_agent_system.py` actualmente solo copia `.agent/`. Por tanto, esta convención **no se propaga automáticamente** a proyectos derivados. Si forks/derivados quieren la convención, deben replicar `CREDITS.md` + skills `repo-compare` y `project-finalize` manualmente.

## Memoria por proyecto

- `.agent/runtime/memory/observations.jsonl` guarda observaciones persistentes.
- `.agent/runtime/memory/MEMORY.md` es un indice humano acotado, con tope de 80 lineas.
- La historia completa y la busqueda profunda viven en `observations.jsonl`, no en `MEMORY.md`.
- La regla vive aqui para evitar drift; actualiza esta seccion si cambia el cap o el marcador de truncado.
- Regenera el indice solo de forma explicita.
- `scripts/memory_consolidate.py` declara `MEMORY_MD_LINE_CAP = 80` y trunca el indice con un marcador visible cuando se supera el limite.

## deliverable_type (work_plan schema, V2)

Cada `work_plan.md` declara `deliverable_type` en su sección Metadata. Valores:
- `code` — el deliverable principal es código fuente (Python u otro).
- `documentation` — markdown, AGENTS.md, READMEs.
- `research` — análisis comparativos, reportes (gap analysis, repo-compare).
- `analysis` — estudios técnicos, audits.
- `mixed` — combinación legítima (ej. WP que toca código y docs).

`agent_controller --validate` valida que exista el campo y no tenga valores inválidos.

## Quality gates dispatch by deliverable_type (WP-2026-089)

`bui-run-quality-gates` invoca ahora `scripts/run_gates_dispatch.py` que lee `deliverable_type` del work_plan activo y dispatchea:

- `code` / fallback → ruff + pytest-safe + pip-audit (condicional)
- `mixed` → ambos sets (code gates + deliverable existence check)
- `documentation` / `research` / `analysis` → solo deliverable existence check

**Conditional pip-audit policy (WP-2026-092)**:
Para los perfiles `code` y `mixed`, `pip-audit` se ejecutará de forma exclusiva cuando la lista `Files Likely Touched` dentro de `work_plan.md` incluya un archivo de manifiesto de dependencias (`pyproject.toml`, `uv.lock`, `requirements.txt`, etc). Si no hay cambios en la superficie de dependencias, la política emitirá un salto auditable, reduciendo latencia.

**Pre-commit Ruff Scope Guard (WP-2026-093)**:
Para evitar regresiones o cambios accidentales en `.pre-commit-config.yaml` que expandan el alcance de `ruff` y causen falsos positivos en tickets no-código (Markdown, documentación, análisis, etc.), se implementa `scripts/check_ruff_hook_scope.py`. Este script verifica que los hooks `ruff-check` y `ruff-format` permanezcan limitados estrictamente a Python (`types: [python]` o `files: \.py$`). Cualquier desviación detiene las gates de pytest inmediatamente.

El dispatcher, sus políticas y guardias son stdlib only; no añaden dependencias.

## Host-first skill precedence & Config Profiles (WP-2026-090)

- **Host-first precedence**: Cuando el bundle `orquestador_de_agentes` se instala en un proyecto de destino (host), las skills definidas en el host (`<destino>/.agent/skills/`) toman precedencia absoluta sobre las homónimas del bundle (`orquestador_de_agentes/skills/`). El bundle actúa estrictamente como un fallback determinista.
- **Config Profiles**: `agents.json` define `"active_profile"`. El repo local de desarrollo usa `"engine-dev"`. El instalador `install_agent_system.py` cambia automáticamente este valor a `"host-project"` en el destino durante `--install` o `--sync`.

## Host setup hook (WP-2026-094)

El proyecto destino puede declarar un script ejecutable `.agent/host-setup.sh`
(o `.ps1` en Windows) que `scripts/install_agent_system.py` detecta tras la
copia del bundle. Comportamiento:

- Si el hook existe: el instalador muestra las primeras 20 líneas + pide
  confirmación humana (`y/N`) antes de ejecutarlo. `--yes` salta el prompt.
- Si el hook devuelve exit != 0: el install aborta y propaga el código.
- Si el hook no existe: silencio (backward-compat absoluto).

Plantillas: `.agent/host-setup.sh.example` / `.agent/host-setup.ps1.example`.
Origen del patrón: OpenHands `.openhands/setup.sh` (MIT).

## Pluggable manager review rubric by deliverable_type (WP-2026-091)

- **Pluggable Prompts**: El Review Bridge (`bus/review_bridge.py`) lee el campo `deliverable_type` del plan de trabajo activo. En lugar de utilizar un prompt único y ciego, adapta el prompt de revisión enviado al backend OpenCode Manager:
  - `code`: Verifica la correctitud del código, cobertura de tests y estándares de estilo.
  - `mixed`: Combina la verificación técnica de código con la revisión estructural y exhaustiva de todos los entregables no-código declarados.
  - `documentation` / `research` / `analysis`: Enfoca la revisión del Manager estrictamente en la claridad, profundidad, calidad e integridad estructural de los entregables documentales correspondientes, omitiendo criterios de código irrelevantes.
- **Salida formal**: Se conserva estrictamente el contrato canónico de salida (`DECISION: APPROVE` o `DECISION: CHANGES`) para mantener la interoperabilidad total del bus de eventos y la máquina de estados.
- **Fallback**: Si `deliverable_type` no está declarado o contiene un tipo desconocido, se activa un fallback seguro y automático a la estrategia `code`.

## Secretos y seguridad

- No guardes credenciales, tokens ni rutas sensibles.
- No toques `privada/`.
- No desactives `guard_paths` para trabajar mas rapido.
- No pidas dependencias nuevas sin aprobacion.

## Robust Builder Relaunch (WP-2026-084)

- **Liveness check**: El supervisor verifica si el Builder está vivo via PID + `tasklist` (Windows) antes de relanzar tras un CHANGES. Fallback: mtime <15 min.
- **Flag `-ResumeBuilder`**: Launcher lo recibe del supervisor en requeue. Skip cleanup agresivo (`Stop-ProjectAgentProcesses`, `Remove-StaleRuntimeArtifacts`, `Assert-StartupAlignment`) para no matar Builder vivo.
- **ADITIVIDAD**: Launcher sin `-ResumeBuilder` (primera apertura) comporta igual que antes. Cero regresión.
- **Diagnóstico**: Supervisor captura stdout/stderr del launcher si falla, loggea a stderr con prefijo `[ticket-supervisor]`.

## Criterio de cierre

> Detalle operativo de los quality gates y comandos diarios (incluye flags exactos y secuencia recomendada): ver [QUICKSTART.md sección "6. Comandos diarios"](QUICKSTART.md#6-comandos-diarios).

Considera una tarea cerrada solo cuando:
1. `ruff`, `pytest` y `pip-audit` pasan.
2. El codigo nuevo usa rutas y manejo de errores correctos.
3. Las decisiones importantes quedan consolidadas en `PROJECT.md` o `CHANGELOG.md`.
4. La revision aplica el principio de Google de aprobar cuando el cambio mejora la salud del codigo, aun si no es perfecto: https://google.github.io/eng-practices/review/reviewer/standard.html
