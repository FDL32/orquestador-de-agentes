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
  - `agent_system/templates/repomix.config.json`: plantilla de configuracion de Repomix.
- `scripts/`: utilidades de instalacion, upgrade, rollback y validacion.
- `skills/`: micro-habilidades reutilizables.
- `.agent/collaboration/`: estado operacional canonico — vive en el `repo_destino`, no en el motor. El motor contiene seeds neutros; apuntar al destino via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`.
- `.agent/runtime/memory/`: memoria persistente por proyecto.
- `.agent/context/repomix.xml`: contexto comprimido del workspace generado por Repomix (bootstrapping).
- `.agent/council/`: broker de consejo y auditoria paralela.
- `.session/repomix_local.xml`: contexto local comprimido para comparacion acelerada (repo-compare skill).
- `.session/repomix_remote.xml`: contexto remoto comprimido para comparacion acelerada (repo-compare skill).
- `REPOSITORY_STRUCTURE.md`: mapa interno publicable del repositorio.

## Vocabulario canonico

No usar "workspace" a secas: el termino es ambiguo porque describe tanto el repo destino como el entorno multi-root del IDE.

| Termino | Descripcion |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` — motor portable, fuente canonica del sistema. Tiene su propio repo git. No contiene estado operativo de tickets. |
| `repo_destino` | El proyecto que usa el motor. Tiene su propio `.agent/` con estado operativo (tickets, memoria, config). Nunca comparte estado con otros destinos. |
| `workspace_activo` | Raiz operativa con `.agent/` desde la que corre el ticket actual. En la topologia actual coincide con `repo_destino`. Se configura via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`. |
| `entorno_multi_root` | IDE abierto con `repo_motor` + `repo_destino` a la vez (VS Code multi-folder workspace). No es un concepto de codigo: solo describe el entorno de desarrollo. |

**Regla de repos:** toda operacion git del tooling (diff, log, commit) corre con `cwd=repo_motor`. El estado operativo (tickets, memoria, events) vive en `repo_destino`.

**Regla de `AGENT_PROJECT_ROOT`:** el motor se invoca siempre con esta variable apuntando al `workspace_activo`. Sin ella, el motor usa modo code-only y bloquea escrituras operativas.

### Distincion critica: `.agent/collaboration/` del motor vs del destino

| Ubicacion | Rol | Contenido |
|-----------|-----|-----------|
| `repo_motor/.agent/collaboration/` | **Seed neutro** | Archivos en estado READY_TO_START/IDLE. Molde para nuevos destinos instalados. No contienen tickets activos. |
| `repo_destino/.agent/collaboration/` | **Estado operativo activo** | `work_plan.md`, `execution_log.md`, `TURN.md`, `STATE.md`, `backlog.md` con el ticket real en curso. |

**Nunca usar `repo_motor/.agent/collaboration/` como operativo.** El guard anti-drift bloquea escrituras operativas ahi sin `AGENT_PROJECT_ROOT`.

## Contrato de version y portabilidad

- `pyproject.toml` define la version del paquete portable.
- `.agent/.version_manifest.json` define la version tecnica del core.
- `MANIFEST.distribute` define la frontera del motor central (codigo operativo).
- `MANIFEST.workspace` define el contrato del workspace destino (estado, memoria, config).
- Los comandos canonical y legacy se documentan por separado.
- Estado actual: `v9.15.0` motor central + workspace destino, cierre canonico con suite verde, encoding guard endurecido y CEM v0 adoptado.
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

When running from a Model B destination workspace (where the motor lives externally),
append `--project-root <destino>` to commands that operate on project state.

- Instalacion inicial: `python scripts/install_agent_system.py --install`
- Sincronizacion estricta: `python scripts/install_agent_system.py --sync`
- Sincronizacion interactiva: `python scripts/install_agent_system.py --sync --prune`
- Vista previa: `python scripts/install_agent_system.py --sync --dry-run`
- Estado del sistema: `python .agent/agent_controller.py [--project-root <workspace>]`
- Auditoria local: `python scripts/local_audit.py [--project-root <workspace>]`
- Memoria consolidada: `python scripts/memory_consolidate.py [--apply|--dry-run] [--project-root <workspace>]`
- Migrar config: `python .agent/agents_config.py --migrate [--dry-run] [--project-root <workspace>]`
- Comparar con repo GitHub: skill `/repo-compare`
- Interaccion por terminal: `python scripts/ticket_supervisor.py --reactive [--project-root <workspace>]`
- Tests: `python scripts/run_pytest_safe.py [--project-root <workspace>]`
- Calidad: `ruff check . && ruff format .`
- Auditoria de dependencias: `python scripts/pip_audit_project.py`
- Archivar colaboracion: `python scripts/archive_collaboration_artifacts.py [--dry-run] [--project-root <workspace>]`

## Convenciones

- Lee `PROJECT.md` antes de tocar arquitectura o estado.
- Lee `INTERACTION_MODES.md` antes de operar por chat o por terminal.
- Para tickets que tocan sincronizacion de estado, bus, proyecciones o codigo topologia-aware (`repo_motor + repo_destino`), comprueba primero si el sintoma encaja con un patron documentado en `docs/KNOWN_FAILURE_PATTERNS.md` antes de proponer un fix nuevo.
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

## CEM v0 - Contrato, Evidencia y Memoria

CEM es el contrato minimo para trabajar con agentes sin convertir cada ticket en burocracia. Se aplica con rigor proporcional al riesgo del cambio.

- **Contrato antes que fix:** identifica que comportamiento canonico protege el cambio antes de tocar codigo o tests.
- **Evidencia antes que relato:** ningun auto-reporte de agente es evidencia; usa diff, exit code, test, evento de bus, commit o artefacto verificable.
- **Memoria despues de aprender:** si una familia de fallos puede repetirse, deja barrera automatica o deuda explicita con ticket y criterio de salida.
- **Rigor proporcional:** docs y typos no cargan la misma ceremonia que bus, supervisor, seguridad, rutas o estado compartido.
- **Barrera verificada:** un guard, hook o test nuevo no cuenta hasta demostrar que bloquea el fallo que promete bloquear.
- **Fixtures realistas:** un test verde contra un fixture irreal es sospechoso; cuando el contrato sea operativo, contrasta contra artefactos reales.
- **Gates self-service:** un gate preserva autonomia solo si explica que fallo, como reproducirlo y como volver a validar sin escalar al humano.
- **Relaunch con root verificado:** antes de relanzar Builder, valida `AGENT_PROJECT_ROOT`, `repo_motor`, `repo_destino`, bus legible y ticket activo.

Referencia ampliada: `.agent/rules/common/sustainable_engineering.md`.

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

La memoria del proyecto sigue una jerarquia de tres niveles (L3 -> L2 -> L1),
centralizada en `bus/memory_loader.py` para bootstrap, review bridge y pre-compact hook:

- **L3 — `memory_profile.md`** (generado por `memory_consolidate.py --apply`): Perfil breve del proyecto con dominios activos, tickets referenciados y senales recientes. Cargado primero por `memory_loader.get_bootstrap_context()`.
- **L2 — `memory_rules.md`** (generado por `memory_consolidate.py --apply`): Reglas deterministas organizadas por dominio, con IDs estables (R-XXX). Cargado por `memory_loader.get_review_context(domain)` para el review bridge.
- **L1 — `observations.jsonl`**: Fuente de evidencia canonica. Contiene todas las observaciones persistentes. `memory_loader.recall_observations()` ofrece acceso directo con filtro opcional por keyword.
- `MEMORY.md` es un indice humano acotado, con tope de 80 lineas. No es una fuente primaria.
- `scripts/memory_consolidate.py` declara `MEMORY_MD_LINE_CAP = 80` y trunca el indice con un marcador visible cuando se supera el limite. Ademas genera L2 y L3 con `--apply`.
- `bus/memory_loader.py` es la unica puerta de entrada: `get_bootstrap_context()` (L3 -> L2 -> L1), `get_review_context(domain)` (L2 por dominio), `get_compact_context()` (L3+L2).<｜｜DSML｜｜parameter name="endString" string="true">
## deliverable_type (work_plan schema, V2)

## deliverable_type (work_plan schema, V2)

Cada `work_plan.md` declara `deliverable_type` en su sección Metadata. Valores:
- `code` — el deliverable principal es código fuente (Python u otro).
- `documentation` — markdown, AGENTS.md, READMEs.
- `research` — análisis comparativos, reportes (gap analysis, repo-compare).
- `analysis` — estudios técnicos, audits.
- `mixed` — combinación legítima (ej. WP que toca código y docs).

`agent_controller --validate` valida que exista el campo y no tenga valores inválidos.

### Contrato operativo por tipo de ticket

El `deliverable_type` no es decorativo: cambia que evidencia debe producir el
Builder y que debe auditar el Manager.

- `code`: requiere diff/commit productivo del ticket, tests/ruff aplicables y
  evidencia de gates en `execution_log.md`.
- `mixed`: requiere el contrato de `code` mas existencia verificable de los
  artefactos no-codigo declarados.
- `documentation` / `research` / `analysis`: no debe exigirse commit de codigo
  ni pytest/ruff salvo que el plan toque codigo. El cierre se basa en artefactos
  documentales declarados y una linea de evidencia en `execution_log.md` que
  combine artefacto y gate final, por ejemplo:
  `Reporte .agent/runtime/compare/<archivo>.md creado. Validate: exit code 0, 0 errors, 0 warnings.`

En tickets documentales, separa explicitamente las superficies:
- `Builder`: archivos que debe crear o modificar y que cuentan como entregables.
- `Read/inspect only`: fuentes que puede leer pero no deben contar como
  entregables ni como scope productivo.
- `Manager-only`: gates o revisiones que ejecuta el Manager y no el Builder.

Si el plan mezcla estas superficies, `check_deliverables_exist.py` puede bloquear
el handoff o validar una evidencia equivocada. El plan debe dejar claro que existe
en disco al final y que solo era contexto.

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
- `OpenCode Permission Preflight`: si el ticket requiere modificar archivos
  fuera de `.agent/collaboration/` o `scripts/` del `repo_destino` (por
  ejemplo `PROJECT.md`, `AGENTS.md` o `CHANGELOG.md`), el plan o el arranque
  debe verificar antes que esas rutas esten permitidas en
  `.opencode/opencode.json` bajo `external_directory`. Si no lo estan, el
  Builder debe bloquear el arranque con diagnostico claro en vez de continuar
  ciego. En OpenCode, esa allowlist puede necesitar el root completo del
  `repo_destino` (`repo_destino\*`) y no solo permisos por archivo, porque el
  backend puede resolver la lectura como acceso al arbol externo completo.
- La configuracion versionada de `.opencode/opencode.json` debe permanecer
  portable y sin rutas absolutas del `repo_destino` actual. Los permisos
  `external_directory` especificos del proyecto se inyectan en runtime desde el
  launcher y se restauran al terminar; no deben quedar commiteados en el motor.

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
