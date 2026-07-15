# AGENTS.md - Instrucciones transversales

## Backends y roles

- **Backend IA:** producto o LLM que ejecuta trabajo. Ejemplos: Claude Code,
  Codex y GitHub Copilot. Un backend IA puede encarnar varios roles segun el
  turno del pipeline.
- **Roles canonicos:** `orchestrator`, `manager`, `builder`, `auditor`, `user`.
  Usa "rol builder" o "rol manager", no "agente builder".
- **Supervisor:** actor runtime del bus ya existente (`bus/supervisor.py`,
  eventos `actor="SUPERVISOR"`). No es sinonimo de orchestrator ni de backend IA.
- **Artefactos:** prompts, skills, scripts, gates y DEC. No llamarlos agentes.
- Claude Code: backend IA principal en esta instalacion.
- Codex / GitHub Copilot: backends IA soportados si leen este archivo dentro del arbol.
- Goose / Claw: **[DEPRECATED - WT-2026-254a]** motores orquestados por `scripts/orquestador.py`. No usar en proyectos nuevos; reemplazados por Claude Code como backend IA principal.

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

### Glosario de nomenclatura de ticket (WOT-2026-010a)

Nomenclatura canonica de identificadores y artefactos de ticket. "Plan" se
reserva para la familia completa; el artefacto de estrategia de un ticket es
`STRATEGY_`, no `PLAN_`.

| Termino | Descripcion |
|---------|-------------|
| `WOT-YYYY-NNNx` | **Prefijo canonico de ticket** (tres letras). Ej. `WOT-2026-010a`. Es el ID que usan generadores, validadores y bus. |
| `WP-` / `WT-` | **Legacy historico.** Prefijos de tickets antiguos (161 `WP-`, 72 `WT-`). NO se migran en masa; los consumidores los aceptan como `legacy-compat`. |
| familia / plan | El plan/familia completo, ej. `WOT-2026-009` agrupa `009a..009g`. "Plan" NUNCA designa el artefacto de un ticket individual. |
| `work_plan.md` | **Contrato operativo del ticket activo.** Una unica copia viva en `.agent/collaboration/`. Lo lee el scope gate y lo ejecuta el Builder. Sin cambio de nombre. |
| `STRATEGY_WOT-<ID>.md` | **Estrategia tecnica del ticket** (opcional). Sustituye al antiguo `PLAN_WT-<ID>.md`. Libera "PLAN" para la familia. Legacy: `PLAN_WP-*`, `PLAN_WT-*`. |
| `AUDIT_WOT-<ID>.md` | **Criterios de auditoria del ticket.** Solo cambia el prefijo `WT->WOT`. Legacy: `AUDIT_WP-*`, `AUDIT_WT-*`. |

**REGLA: en contextos inter-ticket o inter-repo, usa el ID COMPLETO con prefijo.**
Referencia cada ticket con su identificador completo `<PREFIJO>-YYYY-NNNx` (p.ej.
`CTL-2026-008k`, `WOT-2026-020p`, `EXF-2026-007a`) en chat, commits, memoria, backlog,
work_plan y cualquier artefacto operativo. Motivo: se trabajan varios repos/destinos en
PARALELO, y cada uno tiene su propio prefijo (`CTL-`, `WOT-`, `EXF-`, ...); la forma corta
`008k` a secas es AMBIGUA -- es imposible saber a que repositorio/destino pertenece. El
numero `NNNx` solo es unico DENTRO de un prefijo+ano, no globalmente. La forma corta `008k`
solo es aceptable si el prefijo/familia ya quedo EXPLICITAMENTE desambiguado en el mismo
contexto inmediato (p.ej. tras citar `WOT-2026-009a`, referir `009b..009g` como esa familia
en el mismo parrafo); fuera de ese contexto local, siempre el ID completo.

El prefijo ademas RESUELVE el repo destino: cada destino declara su `ticket_prefix` en su
`motor_destination_link.json` / `PROJECT.md`, y el mapeo inverso prefijo->repo se deriva de
ahi (ver WOT-2026-020s: prefix-resolver + bootstrap guard). Convencion para repos NUEVOS
(sin retrofit de los existentes): sugerir el prefijo desde las iniciales del nombre (3
letras, mayusculas) y verificar unicidad contra los prefijos ya declarados antes de
adoptarlo -- la convencion sugiere, el registro (los links por-destino) resuelve.

**Clases de patron para consumidores de codigo** (archivador, pre-handoff guard,
validador de prosa, review bridge, motor_checkpoint):
- `canonical`: `STRATEGY_WOT-*`, `AUDIT_WOT-*`.
- `legacy-compat`: `PLAN_WP-*`, `PLAN_WT-*`, `AUDIT_WP-*`, `AUDIT_WT-*`. Se
  conservan con alias de transicion; eliminarlos dejaria sin archivar los
  tickets historicos.

**Prompt de auditoria de contrato:** `prompts/audit_ticket_contract.md` (renombrado
desde `audit_plan.md`; stub retirado en WOT-2026-011d). Audita el contrato/plan operativo
del ticket ANTES de Builder; no confundir con review de implementacion, bus,
cierre o publicacion.

**Generador vs historia (regla de gate, WOT-2026-010a):** la gate de
nomenclatura distingue dos usos muy distintos de un ID con prefijo legacy:

- **Generador / ejemplo vivo** (DEBE usar `WOT-`): plantillas, placeholders,
  ejemplos de comando, texto de `--help`, esquemas de formato (`source_ticket`,
  `Plan ID`, `Ticket relacionado`, `--ticket WP-...`). Crean o enseñan
  nomenclatura nueva. La gate FALLA si usan `WP-`/`WT-` sin etiqueta.
- **Historia de commit** (legacy-compat implicito, NO se reescribe): un
  comentario o docstring de la forma `# <TICKET>: <descripcion de lo que se
  hizo>` documenta en que ticket historico se realizo un cambio. Reescribirlo
  falsearia la trazabilidad. La gate lo PERMITE como legacy-compat por su forma
  (`# <TICKET>:` o referencia historica), sin marca por-linea.
- **Bloque legacy etiquetado** (legacy-compat explicito): un ejemplo que
  conserva un ID historico a proposito para demostrar retrocompatibilidad debe
  llevar una nota `legacy-compat (WOT-2026-010a): ...` cerca.

Gate ejecutable: `scripts/check_ticket_nomenclature.py` clasifica cada hit y
falla solo ante un generador/ejemplo vivo con prefijo legacy sin etiqueta.

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
- Estado actual: `v9.17.1` motor central + workspace destino, cierre canonico con suite verde, pipeline autonomo por chat, meta-auditoria, auditoria de publicacion Git, guard de integridad del motor, encoding guard endurecido y CEM v0 adoptado.
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

When running from an external-motor destination workspace (repo_motor + repo_destino topology),
append `--project-root <destino>` to commands that operate on project state.

- Instalacion inicial: `python scripts/install_agent_system.py --install`
- Sincronizacion estricta: `python scripts/install_agent_system.py --sync`
- Sincronizacion interactiva: `python scripts/install_agent_system.py --sync --prune`
- Vista previa: `python scripts/install_agent_system.py --sync --dry-run`
- Estado del sistema: `python .agent/agent_controller.py [--project-root <workspace>]`
- Auditoria local: `python scripts/local_audit.py [--project-root <workspace>]`
- Memoria consolidada: `python scripts/memory_consolidate.py [--apply|--dry-run] [--project-root <workspace>]`
- Integridad del motor: `python scripts/check_motor_pristine.py --snapshot --motor-root <repo_motor> --out <snapshot.json>` y despues `python scripts/check_motor_pristine.py --check --snapshot-file <snapshot.json> --report <result.json> --motor-root <repo_motor>`
- Auditoria de publicacion Git: `python scripts/classify_publication.py --repo-root <repo_destino> --out <repo_destino>/orchestrator_pipeline/reports/publication_manifest.json`
- Bundle de contexto para Hermes: `python scripts/hermes_build_context_bundle.py --output-root <hermes_agent>/uploads --soul-output <hermes_agent>/soul.md`. Genera snapshots con version, commit y hashes; no edites copias derivadas como fuentes canonicas.
- Migrar config: `python .agent/agents_config.py --migrate [--dry-run] [--project-root <workspace>]`
- Comparar con repo GitHub: skill `/repo-compare`
- Orquestar backlog por chat: skill `/pipeline` (`prompts/orchestrator_pipeline.md`)
- Meta-auditar pipeline cerrado: skill `/audit-pipeline`
- Auditar publicacion Git: skill `/audit-git-publication`
- Auditar salud del sistema post-cambio (motor+destino+integracion): skill `/audit-system-health`. Recolector determinista: `python scripts/collect_system_health.py --motor-root <repo_motor> --project-root <repo_destino> --mode auto`. El script RECOLECTA (read-only: por defecto no toca ningun fichero TRACKED); el agente AUDITA. Salida en `<repo_destino>/.agent/audits/system_health/general_audit_YYYYMMDD[_HHMM]/`. El registro en `INDEX.md` (fichero tracked en el workspace) es opt-in via `--publish-index`, OFF por defecto (WOT-2026-023x). Ver `prompts/audit_post_change_system_health.md`.
- Interaccion por terminal: `python scripts/ticket_supervisor.py --reactive [--project-root <workspace>]`
- Tests: `python scripts/run_pytest_safe.py [--project-root <workspace>]`
  - NO usar `python -m pytest` directo sobre tests que importan el controller:
    al insertar `.agent/` en sys.path, `runtime` puede resolver a
    `.agent/runtime/` (que tiene `__init__.py`) en vez de `<motor>/runtime/`,
    y la coleccion falla con `No module named 'runtime.project_root'`.
    El runner seguro configura el entorno correcto y ademas incluye la
    barrera de state-leak (falla si la suite muta `.agent/collaboration/`).
- Calidad: `ruff check . && ruff format .`
- Auditoria de dependencias: `python scripts/pip_audit_project.py`
- Archivar colaboracion: `python scripts/archive_collaboration_artifacts.py [--dry-run] [--project-root <workspace>]`

## Convenciones

- Lee `PROJECT.md` antes de tocar arquitectura o estado.
- Lee `INTERACTION_MODES.md` antes de operar por chat o por terminal.
- Para tickets que tocan sincronizacion de estado, bus, proyecciones o codigo topologia-aware (`repo_motor + repo_destino`), comprueba primero si el sintoma encaja con un patron documentado en `docs/KNOWN_FAILURE_PATTERNS.md` antes de proponer un fix nuevo.
- Para arrancar una sesion nueva con cualquier agente, usa el bootstrap canonico en `prompts/orchestrator_session_bootstrap.md` (apunta a archivos clave en lugar de embeber).
- Usa `pathlib` y `try/except` explicito para I/O.
- Mantiene la raiz limpia: no metas basura temporal en el arbol portable.
- Usa `.agent/collaboration/work_plan.md` y `.agent/collaboration/execution_log.md` para el estado canonico.
- En `Files Likely Touched`, escribe una unica ruta parseable por bullet. Las
  aclaraciones van en una linea separada; texto como `o modulo equivalente` en
  el mismo bullet puede impedir que el parser de FLT reconozca la ruta.

### Convencion de encoding y gap v1 (WOT-2026-010e)

- **Preferir Write/Edit sobre heredoc** para contenido no-ASCII en archivos de
  texto (`.md`, `.py`, `.json`, `.toml`, `.yaml`, `.yml`, `.sh`, `.ps1`, `.txt`,
  `.xml`). El hook `encoding_post_write_hook.py` detecta BOM, mojibake y
  question-mark corruption tras cada escritura nativa del agente.
- **Gap v1 conocido:** Bash/heredoc NO esta cubierto por el hook. Las
  escrituras dentro de `Bash`/`RunInTerminal` quedan cubiertas por convencion
  operativa + `check_encoding_guard.py` antes de handoff/commit.
- `TEXT_EXTENSIONS` en `scripts/encoding_guard.py` es la fuente de verdad de
  sufijos texto. No derivarla de `GLOB_PATTERNS`.
- `scripts/check_encoding_guard.py` sigue siendo la autoridad de cierre; el
  hook es defensa en profundidad, no su sustituto.

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
- **Barrera cableada:** ademas de morder, algo tiene que INVOCARLA. Un guard solo es barrera si lo llama un camino que corre solo (pre-commit, CI, `prepush_check`, closeout, preflight, controlador, hooks de tool-call). Citarlo en un prompt, una skill o este AGENTS.md **no es cableado: es una norma**, y una norma depende de que alguien se acuerde. Barrera de la barrera: `scripts/check_guard_wiring.py` (WOT-2026-024u) - un guard nuevo sin cablear FALLA; la deuda legacy solo puede quedar en WARN si esta DECLARADA con su ticket dueno.
- **Aplicate tu propia vara (y que lo diga otro):** un guard que mide una propiedad P tiende a medirla con una vara MAS FLOJA que la que predica, y sale verde igual. `check_guard_wiring` nacio declarando que "una cita en un prompt es una norma, no un mecanismo"... y clasificaba casando nombres contra el TEXTO CRUDO de los ficheros: la misma vara que su docstring llamaba insuficiente. Daba por cableados guards citados solo en un COMENTARIO, o en hooks `stages: [manual]`. Sus 16 tests, los 4 gates y la suite entera (4094 passed) pasaron verdes: todos hermeticos, y el defecto vivia en la frontera con el repo REAL. Lo cazo una auditoria adversarial HERMANA en contexto fresco. Regla: aplica P a tu propio guard **ejecutandolo**, no leyendolo, y no lo des por bueno sin una pasada adversarial externa - el mismo sesgo que escribio el codigo escribio los tests.
- **Barrera del alcance, no solo del mecanismo:** un guard puede estar cableado, morder, y no mirar donde ocurre el fallo. `check_encoding_guard` es fail-closed y corre en pre-commit... y solo mira `.py`. Por eso DOS fugas de markup de modelo vivieron meses dentro de `AGENTS.md` y `MANUAL_PUBLICATION_CHECKLIST.md` - esta ultima desde el commit inicial del repo (WOT-2026-024x).
- **Criterio invariante, evidencia fechada:** un DoD debe ser un INVARIANTE, no una MEDICION. Un criterio que fija un numero ("quedan 11 hits", "243 auditorias") caduca solo, sin que nadie toque la ficha, y el Builder ya no puede distinguir "el numero cambio porque el mundo avanzo" de "cambio porque he roto algo". El numero es EVIDENCIA: va etiquetado como snapshot fechado, nunca como criterio de aceptacion (WOT-2026-024t).
- **Fixtures realistas:** un test verde contra un fixture irreal es sospechoso; cuando el contrato sea operativo, contrasta contra artefactos reales.
- **Gates self-service:** un gate preserva autonomia solo si explica que fallo, como reproducirlo y como volver a validar sin escalar al humano.
- **Relaunch con root verificado:** antes de relanzar Builder, valida `AGENT_PROJECT_ROOT`, `repo_motor`, `repo_destino`, bus legible y ticket activo.

Referencia ampliada: `.agent/rules/common/sustainable_engineering.md`.

## Hacer ahora vs aplazar (criterio de decision)

El coste de APLAZAR **no es cero**: fichar "para la proxima sesion" cuesta prompt de arranque, recarga de contexto, re-medicion y revalidacion de premisas, y sobre todo **asciende el diagnostico de hoy a premisa heredada sin verificar**. Pero ese coste NO autoriza a perseguir parches que degeneran.

**Asimetria (regla de oro, y mas en autonomo):** los gates de abajo son un filtro para PERMITIR hacer ahora, **nunca una obligacion de hacerlo**. Ante duda no resuelta POR EVIDENCIA, **aplazar gana**. Si el trabajo se sale del objetivo del ticket, se ficha y pasa a la sesion siguiente. El sistema debe ser fuente de soluciones, no de problemas: un arreglo dudoso metido a presion es un problema nuevo con commit.

**Cada gate se responde con un ARTEFACTO, no con un juicio.** Un gate que se contesta con una opinion se relaja solo en cuanto el agente quiere avanzar (misma enfermedad que "aplicate tu propia vara"). Si no puedes pegar el artefacto, el gate NO pasa.

### Hazlo ahora SOLO si cumple los 8

1. **Localizacion EJECUTADA EN EL CONTEXTO DE PRODUCCION.** No basta "se la linea"; **ni siquiera basta "lo ejecute"**. Responde: quien lanza esto en produccion, con que shell, PATH y cwd -- y mide AHI. Artefacto: `command:` + `exit_code:` + `shell/cwd:`. **Corolario: si dos probes se contradicen, el conflicto ES el hallazgo; no elijas el que confirma tu tesis.**
2. **DoD con dientes.** Existe test/probe que falla HOY con el bug y pasa con el fix, o mutacion **alcanzable** definida (un test que no puede ALCANZAR la rama que muta no cuenta). Artefacto: node-id + rc rojo previo.
3. **Una superficie acotada.** Una superficie, no una familia. Artefacto: lista de ficheros a tocar (numero cerrado).
4. **Arquitectura existente.** Conecta una pieza ya prevista o corrige una desviacion local; no inventa subsistema. Artefacto: la ruta del mecanismo que extiendes.
5. **Cadena fresca.** "Desbloquea la cadena" solo vale si el DAG/triage se revalido EN ESTA SESION; un DAG en disco caduca solo (WOT-2026-023t). Si esta caducado, **re-triage primero**. Artefacto: fecha/SHA del triage.
6. **Cabe completo:** fix + tests + mutation + gates + commit + review proporcional. Artefacto: la balanza de abajo.
7. **Bisect-safe:** cada commit publicable queda verde en su propio HEAD.
8. **Sin decision humana pendiente.** Trade-off de producto, politica o arquitectura -> se pregunta o se ficha.

### STOP de degeneracion (durante el arreglo)

Si tras el primer parche aparece cualquiera de estos, **parar y re-planificar**: superficie nueva no prevista; heuristica nueva; mas de un fichero/familia adicional; el test inicial no alcanza la rama real; el fix empieza a parecer diseno de sistema. **No parchear el parche:** ficha el alcance nuevo o abre sesion propia (WOT-2026-024u: de 3 lineas a "disenar un analizador estatico" en 5 parches; salio a WOT-2026-025c).

### Aplazalo si

No hay probe ejecutado en contexto de produccion; el DoD es aspiracional; requiere medir la flota completa o datos externos; mezcla familias de commits; depende de decision humana; el DAG esta caducado; la solucion correcta es diseno nuevo; no puede quedar bisect-safe; o el contexto es largo y el riesgo de falso-verde sube.

### Balanza minima obligatoria (con cifras, no adjetivos)

Sin al menos una cifra por columna la balanza es sesgo de presente: el agente subestima siempre lo hipotetico.

| Hacer ahora | Aplazar |
|---|---|
| ficheros tocados (n) | re-medicion requerida: si/no |
| tests/probes nuevos (n) | contexto a recargar |
| tiempo/review estimado | riesgo vivo si se deja |
| blast radius | sesiones futuras estimadas (n) |

### Dos reglas durables

- **Corregir un documento desechable NO corrige el sistema.** Si la ficha/backlog/memoria durable sigue con el diagnostico falso, el arreglo esta A MEDIAS. Un prompt de arranque es desechable y caduca; el backlog es la fuente durable (WOT-2026-024d/024f: el mismo diagnostico falso se pago dos veces).
- **Los 8 gates NO son un detector de premisas falsas.** Caso fundacional (2026-07-15): WOT-2026-020o-B pasaba los 8 -- linea exacta, DoD con mutacion, una superficie, arquitectura existente, cadena fresca, sin decision humana -- y **el bug no existia**: el probe se habia medido en PowerShell, no en Git Bash (el shell REAL del hook). Lo unico que lo cazo fue **seguir midiendo hasta refutarse**, y el hallazgo llego DESPUES de que los 8 gates dieran verde. Por eso el gate 1 exige contexto de produccion y por eso la duda se resuelve aplazando.

## Skills Formales de Proceso

El repositorio define skills operativas formales para estructurar el trabajo del agente.
Úsalas invocando sus triggers (ej. `/tdd`, `/debug`):

- **Test-Driven Development (TDD)** (`skills/test-driven-development/SKILL.md`): Usar para asegurar cobertura y evitar regresiones en código nuevo o fixes. Obliga a escribir el test primero (Red), el código mínimo (Green) y refactorizar con calidad (`ruff` + `pytest`).
- **Systematic Debugging** (`skills/systematic-debugging/SKILL.md`): Usar ante errores no triviales. Exige investigación de causa raíz antes de parchear y establece un límite estricto de 3 intentos antes de detener la iteración y cuestionar el entendimiento del problema.

No uses estos skills si contradicen el flujo general (ej. usar TDD para escribir un README o depuración para un typo reportado por el linter).

### Gobierno skill<->prompt: skill apunta, prompt gobierna (WOT-2026-014r / X-09)

Cuando una skill tiene prompt canonico (declara `contract_id` + `source_prompt`/`source_of_truth`), la skill es
PUNTERO operativo, no fuente normativa. PROHIBIDO re-declarar criterios normativos (gates, veredictos, estados,
barreras) en la `SKILL.md`: viven una vez en el prompt y la skill remite. Si divergen, prevalece el prompt y la
divergencia es un bug de la skill. Verificado en vivo: el SKILL de `manager-review-implementation` OMITIA
mutation-verify (E3) y el de `orchestrate-pipeline` OMITIA el reconcile post-close (E6) por re-declarar en vez de
apuntar.

**Auditoria automatica (R2):** un linter/gate puede grepear las `SKILL.md` por marcadores normativos
(`DECISION:`, `deliverable_type`, `0 errors`, `APROBADO|CHANGES|BLOCKER`, `exit code`). Un marcador en una skill
que TIENE prompt canonico es candidato a re-declaracion: el gate exige que la skill REMITA al prompt (cita
`contract_id`) en vez de definir el criterio. Si el criterio diverge del prompt -> hallazgo automatico, prevalece
el prompt. Verificado (3a pasada): 9 `SKILL.md` contienen esos marcadores -- adopt-existing-project, audit-pipeline,
builder-run-quality-gates, manager-create-work-plan, manager-review-implementation, orchestrate-pipeline,
refactor-manager, session-close-full-audit, setup-agent-system -- candidatas a re-declaracion (una parte solo
menciona el marcador). La matriz de ownership de artefactos asociada vive en `prompts/_shared/artifact_ownership.md`.

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
- `bus/memory_loader.py` es la unica puerta de entrada: `get_bootstrap_context()` (L3 -> L2 -> L1), `get_review_context(domain)` (L2 por dominio), `get_compact_context()` (L3+L2).
- **La memoria PRIVADA de un agente no es autoritativa.** Cada backend (Claude Code, Kilo, Codex...) tiene su propio almacen personal, invisible para los demas y para el repo. Lo canonico es lo VERSIONADO: `archive/observations.YYYY-MM.jsonl`, este AGENTS.md, los prompts, las skills y los tests. Si una leccion solo vive en la memoria privada de un backend, para el sistema NO EXISTE.
- **Deuda conocida (WOT-2026-024r):** `memory_loader` lee `observations.jsonl` (gitignored, por worktree), NO el `archive/` trackeado. O sea: hoy la memoria portable se escribe, se versiona y se pushea, y **nadie la lee de vuelta**. Promover una leccion al archive la hace PORTABLE, no VIVA.

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

`builder-run-quality-gates` invoca ahora `scripts/run_gates_dispatch.py` que lee `deliverable_type` del work_plan activo y dispatchea:

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
