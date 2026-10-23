# AGENTS.md - Instrucciones transversales

## Backends y roles

- **Backend IA:** producto o LLM que ejecuta trabajo. Ejemplos: Claude Code,
  Codex y GitHub Copilot. Un backend IA puede encarnar varios roles segun el
  turno del pipeline.
- **Roles canonicos, por categoria** (armonizado 2026-10-12 tras bucle
  adversarial de 3 lentes -- codex, nan-fs, opencode/glm -- sobre
  vocabulario de roles; ver Nota de enums de codigo abajo). Usa "rol
  builder" o "rol manager", no "agente builder":
  - **Pipeline secuencial de un ticket:** `orchestrator`, `manager`,
    `builder`, `auditor`.
  - **Capa de revision independiente (sistema de 4 capas/"personas"):**
    `revisor` (anadido WOT-2026-098b). Persona-2 (Revisor) del nucleo
    `prompts/agent_execution_modes.md` -- NUNCA el mismo backend/modelo que
    implemento (condicion dura, ver `prompts/persona_system.md` Seccion 2).
    Para entender la numeracion de personas 0/1/2/3 y su correlacion con
    las Capas del nucleo, lee la cadena completa: `prompts/
    agent_execution_modes.md` -> `prompts/persona_system.md`.
  - **Rol de gobierno/ensemble (no secuencial, no de pipeline de ticket):**
    `proposer` / `challenger` (lentes adversariales de bucles de gobierno:
    CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE, DESIGN_REVIEW). Ver
    `prompts/ensemble_loop.md`.
  - **Actor humano:** `user`. No es backend IA, no tiene model_id que
    resolver -- analogo a `ACTOR_RUNTIME_ROLES` (`SUPERVISOR`, ver abajo):
    actor fuera de los enums de codigo que validan backend, no un olvido.
- **Nota de enums de codigo:** NO hay un enum 1:1 con esta lista -- existen 3 enums de codigo
  con dominios DISTINTOS por diseno que no se fusionan. Detalle:
  `.agent/rules/common/backends_roles_detail.md`.
- **Supervisor:** actor runtime del bus ya existente (`bus/supervisor.py`,
  eventos `actor="SUPERVISOR"`). No es sinonimo de orchestrator ni de backend IA.
- **Artefactos:** prompts, skills, scripts, gates y DEC. No llamarlos agentes.
- Claude Code: backend IA principal en esta instalacion.
- Codex / GitHub Copilot: backends IA soportados si leen este archivo dentro del arbol.
- **No confundir Builder real con lente de ensemble:** una tarea de implementacion, lectura o
  escritura con filesystem usa el CLI directo del agente y `prompts/builder_invocation_contract.md`;
  una revision adversarial corta usa `ensemble_dispatch.py loop-round` y `prompts/ensemble_loop.md`.
  `ensemble_dispatch.py` no es un mecanismo generico para encargar tareas.

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
- `REPOSITORY_STRUCTURE.md`: mapa interno publicable del repositorio.

## Vocabulario canonico

No usar "workspace" a secas: el termino es ambiguo porque describe tanto el repo destino como el entorno multi-root del IDE.
**No usar "research"** para designarlas: lo que produce una sesion de planificacion es un DISENO
(un artefacto: el flight plan, la ficha, el DAG), no una investigacion.
**Regla de aislamiento por worktree: aplica al `repo_motor` igual que al `repo_destino`.**
**REGLA: en contextos inter-ticket o inter-repo, usa el ID COMPLETO con prefijo.**
**Nunca usar `repo_motor/.agent/collaboration/` como operativo.** El guard anti-drift bloquea escrituras operativas ahi sin `AGENT_PROJECT_ROOT`.

Ver vocabulario completo (terminos `repo_motor`/`repo_destino`/`workspace_activo`, tipos de
sesion DISENO/DESARROLLO, modos de ejecucion Tradicional/4capas/Intermedio, convencion de
worktrees pareados, glosario de nomenclatura de ticket y la tabla motor-vs-destino de
`.agent/collaboration/`) en
[vocabulario_canonico.md](.agent/rules/common/vocabulario_canonico.md).

## Contrato de version y portabilidad

- `pyproject.toml` define la version del paquete portable.
- `.agent/.version_manifest.json` define la version tecnica del core.
- `MANIFEST.distribute` define la frontera del motor central (codigo operativo).
- `MANIFEST.workspace` define el contrato del workspace destino (estado, memoria, config).
- Los comandos canonical y legacy se documentan por separado.
- Estado actual: ver `PROJECT.md` (version, hitos recientes).
- El motor vive una unica vez en `orquestador_de_agentes/`; los proyectos destino lo referencian externamente.
- La senal VIVA de staleness NO es esta cadena de version hardcodeada (queda fija hasta el proximo bump manual): es `motor_sha` en el link motor<->destino, comparado en vivo contra el HEAD real del motor en cada `destination_context.py --bootstrap` (WOT-2026-024j, WARN de drift, nunca gate).

## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)

Los archivos `MANIFEST.distribute` y `MANIFEST.workspace` en la raiz del repositorio definen el contrato estricto del motor central y el workspace destino. Detalle (referencia bajo demanda, consulta al tocar la frontera de distribucion o el workspace destino): `.agent/rules/common/manifest_contracts.md`.

## Comandos principales

When running from an external-motor destination workspace (repo_motor + repo_destino topology),
append `--project-root <destino>` to commands that operate on project state.

- Instalacion inicial: `python scripts/install_agent_system.py --install`
- Sincronizacion estricta: `python scripts/install_agent_system.py --sync`
- Sincronizacion interactiva: `python scripts/install_agent_system.py --sync --prune`
- Vista previa: `python scripts/install_agent_system.py --sync --dry-run`
- Estado del sistema: `python .agent/agent_controller.py [--project-root <workspace>]`
- Auditoria local: `python scripts/local_audit.py` (NO acepta `--project-root`)
- Memoria consolidada: `python scripts/memory_consolidate.py [--apply|--dry-run]`.
   El scope se determina por `AGENT_PROJECT_ROOT` o por `motor_destination_link.json` del destino.
- Integridad del motor: `python scripts/check_motor_pristine.py --snapshot --motor-root <repo_motor> --out <snapshot.json>` y despues `python scripts/check_motor_pristine.py --check --snapshot-file <snapshot.json> --report <result.json> --motor-root <repo_motor>`
- Auditoria de publicacion Git: `python scripts/classify_publication.py --repo-root <repo_destino> --out <repo_destino>/orchestrator_pipeline/reports/publication_manifest.json`
- Migrar config: `python .agent/agents_config.py --migrate [--dry-run] [--project-root <workspace>]`
- Comparar con repo GitHub: skill `/repo-compare`
- Orquestar backlog por chat: skill `/pipeline` (`prompts/orchestrator_pipeline.md`)
- Orquestar un OBJETIVO como Manager (estrategia -> planes -> Builders -> bucles F/S): nucleo portable
  `prompts/manager_orchestrator_loop.md` + su adaptador a este motor `prompts/manager_orchestrator_loop_adapter_motor.md`
  (skill `manager-orchestrator-loop`). No confundir con `/pipeline`, que ejecuta tickets ya formados.
- Dispatch padre/hijo multi-ticket y multi-backend (Claude Code/Kilo/OpenCode), capa EXPERIMENTAL que
  se apila sobre `/autonomous-ticket-batch` cuando un vuelo necesita backends distintos por ticket:
  `prompts/orchestrator_child_dispatch_multiticket_multibackend_unlimited.md`
  (skill `orchestrate-child-dispatch-multiticket-multibackend-unlimited`). No sustituye el PREDICATE,
  las 8 barreras ni el `GROUP_STOP_REPORT` de ese ejecutor.
- Meta-auditar pipeline cerrado: skill `/audit-pipeline`
- Auditar publicacion Git: skill `/audit-git-publication`
- Auditar salud del sistema post-cambio (motor+destino+integracion): skill `/audit-system-health`. Recolector determinista (read-only): `python scripts/collect_system_health.py --motor-root <repo_motor> --project-root <repo_destino> --mode auto`. Detalle de salida e indice opt-in: `prompts/audit_post_change_system_health.md`.
- Interaccion por terminal: `python scripts/ticket_supervisor.py --reactive [--project-root <workspace>]`
- Tests: `python scripts/run_pytest_safe.py` (NO acepta `--project-root`; runs against `repo_motor` tests by design)
  - NO usar `python -m pytest` directo sobre tests que importan el controller (resuelve
    `runtime` al modulo equivocado via sys.path). Causa medida y barrera de state-leak:
    `.agent/rules/common/comandos_tests_runner_detail.md`.
- Calidad: `ruff check . && ruff format .`
- Auditoria de dependencias: `python scripts/pip_audit_project.py`
- Archivar colaboracion: `python scripts/archive_collaboration_artifacts.py [--dry-run] [--project-root <workspace>]`

## Convenciones

### Prompt/contrato citado => LEELO ENTERO antes de redactar contra el (2026-07-29)

**Norma dura, no consejo.** Si un prompt te lo pegan en el chat, lo enlaza otro prompt que te pegaron, o un proceso lo declara como su contrato, **lo abres y lo lees ENTERO antes de producir nada que se mida contra el**. Ver detalles, fallos medidos y agravantes en .agent/rules/common/contract_full_read_and_process_search.md.

### Decision de proceso sin instruccion exacta => BUSCA protocolo documentado antes de suponer uno (2026-10-14)

**Norma con barrera de FORMA parcial (WOT-2026-104b):** antes de actuar sobre una decision de proceso sin instruccion exacta, busca si ya existe un protocolo documentado. Mecanismo, limites y clases de decision: `.agent/rules/common/contract_full_read_and_process_search.md`.

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

### Orden de trabajo: AGRUPA los commits, la suite va la ULTIMA (WOT-2026-026t)

**La suite canonica es el ULTIMO paso antes del push, nunca uno intermedio.** El contrato exige
`tested_commit_sha == HEAD` (`pre_handoff_guard.py:561`), asi que **cualquier commit posterior a la
suite la invalida** y obliga a re-correrla entera (~7 min).

```
ORDEN CORRECTO                          ORDEN QUE DESPERDICIA
1. TODOS los commits                    suite -> commit -> suite -> commit -> suite
2. suite canonica (UNA vez)             (medido 2026-08-04: 3 corridas, ~15 min tirados)
3. verificar tested_commit_sha == HEAD
4. push
```

**Es la misma familia que la regla del bucle** (`obs-canonical-suite-runs-after-the-loop-not-before`:
el bucle adversarial pide cambios, asi que una suite previa queda invalidada). Ahora generalizada:
**cualquier** escritura posterior invalida la corrida, venga de un bucle o de un commit propio.

**Barrera cableada, no norma** (`scripts/check_suite_freshness.py`, hook `check-suite-freshness` en
`pre-commit`): avisa ANTES de commitear si existe una suite verde COMPLETA en el HEAD actual que
ese commit invalidaria, citando cuantos tests se pierden. **No bloquea** -- un commit a mitad de
sesion es legitimo, y bloquearlo forzaria a correr la suite entre cada par de commits, que es el
desperdicio que se quiere evitar. La barrera BLOQUEANTE (no publicar con suite stale) ya existe y
vive en `pre_handoff_guard`.

**No uses `-k` como evidencia de cobertura de una funcion compartida: selecciona por nombre de
clase/fichero, no por grafo de call-sites, asi que una funcion ejercitada desde otra clase puede
quedar sin cubrir aunque `-k` de verde.** La evidencia final debe venir de la suite canonica
completa (`--level all`), nunca de un `-k` por nombre. Caso forense completo (incidente medido
WOT-2026-079d, 3 regresiones reales que `-k` dejo pasar, memoria
`obs-canonical-suite-k-filter-insufficient-for-shared-function-coverage`): [T1].

**Asignacion de rol en despacho trio (Manager/Builder/Revisor, WOT-2026-104k): en el protocolo
`prompts/kilo_trio_dispatch/`, SOLO el Manager corre `--level all`, nunca el Builder ni el
Revisor.** El Builder se limita a focales; el Revisor corre sus propios focales de forma
independiente, sin esperar al Manager. **Alcance: cubre SOLO el protocolo trio -- NO toca
`scripts/run_gates_dispatch.py` ni `skills/builder-run-quality-gates`**, donde el Builder SI es
el unico verificador legitimo de `--level all` (tickets de un solo Builder sin Revisor/Manager
separados). Enforcement mecanico (WOT-2026-117a): `scripts/check_manager_role_for_suite.py`,
cableado en `run_pytest_safe.py --level all`, bloquea la invocacion si
`.agent/collaboration/TURN.md` declara un rol no-Manager, con exencion explicita (no inferida)
para el self-check del Builder via `run_gates_dispatch.py`. Caso forense completo (incidente
medido WOT-2026-104j, bucle de gobierno `UNI-5`): [T2].

#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)

**La publicacion es una accion del VUELO, no del ticket: NO se pushea entre tickets, solo al
final con autorizacion registrada.** Detalle completo (decision de proceso, busqueda previa,
motivo y estado `PUBLICACION_PENDIENTE_AUTORIZACION`): `.agent/rules/common/flight_push_policy.md`.

#### Extension: push a una rama con trafico concurrente de otras sesiones (2026-10-14)

**Default fail-closed: si la rama remota avanzo con commits de otras sesiones, el Gate 2
relajado NO aplica salvo que se cumplan TODAS estas 5 condiciones: (1) TU propio commit ya
paso el Gate 1 con evidencia registrada (sin eso, suite completa, sin excepcion); (2) evidencia
VERIFICABLE de que el lado entrante tambien corrio su Gate 1; (3) ningun lado toca una
superficie transversal de alto blast radius; (4) sin import cruzado entre los lados; (5) commit
NO-merge y menos de 2 rechazos previos sin re-suite.** Por que: sin las 5, el HEAD integrado
publicado queda sin verificacion real (evidencia no atribuible), rompiendo `tested_commit_sha
== HEAD`. Checklist completa (criterio de merge disjunto vs mismo-fichero) y riesgo residual
declarado (sin verificador CI tercero equivalente): `.agent/rules/common/flight_push_policy.md` [G1].

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

#### No MEZCLES vias de escritura en el mismo fichero (line endings, medido 2026-08-04)

**Regla operativa:** elige UNA via de escritura por fichero (para `.py`/`.md` del motor,
`Write`/`Edit`; si amplias por `Bash`, usa la MISMA via con que se creo). Mezclar `Write`/`Edit`
con heredoc/`cat >>` sobre el mismo fichero deja finales de linea MIXTOS y el commit ABORTA --
anadir asi a un fichero creado con `Write` es el caso que mas muerde. Comprobacion correcta
(cuenta bare LF, no compara totales): `raw.count(b"\r\n")` vs `raw.count(b"\n")`; si la
diferencia es > 0 **y** hay CRLF, esta MIXTO. Si el hook ya aborto: no es un fallo, es el flujo
-- el fichero queda arreglado en disco, repite `git add`+commit y verifica que tus cambios
sobrevivieron. Sintoma, causa medida y las dos creencias falsas que NO conviene heredar: [E1].

### Nomenclatura de perfiles ensemble (`ensemble_profiles` en `agents.json`)

- **Forma canonica:** `<rol>_<backend>_<familia>[_<caracteristica>]`, con `familia` = UNA
  palabra que identifica el modelo SIN version ni tamano (el campo `model` del perfil ya lleva
  la version exacta; el nombre no la duplica). Colar version/tamano en el nombre es error:
  `challenger_groq_qwen38` es INCORRECTO. Especificacion completa de campos, ejemplos y origen
  de la norma: `.agent/rules/common/ensemble_profile_nomenclature.md`.
- **No renombrar `challenger_opencode_glm_5_2` sin revisar primero** `grep -rn
  "challenger_opencode_glm_5_2" tests/`. Excepcion legacy (por que, estado exacto, consecuencia
  para rutas de seleccion nuevas): `docs/protocol/ensemble_profile_naming_legacy_case.md`.

## Archivado de colaboracion (WP-2026-100)

- `scripts/archive_collaboration_artifacts.py` mueve `PLAN_WP-*.md` y `AUDIT_WP-*.md` cerrados a `.agent/collaboration/_archive/plan_audit/`.
- El ticket activo conserva solo sus documentos vivos en `collaboration/`.
- El archivador es idempotente: segunda ejecucion = no-op.
- Usa `--dry-run` para previsualizar sin modificar, `--list-active` para ver archivos activos.

## Superficies vivas vs historicas en `.agent/collaboration/` (WP-2026-107)

Ver las superficies vivas NO archivables y la regla de limpieza en .agent/rules/common/collaboration_live_surfaces.md.

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

**Fallback ante duda de diseno sin contrato que la resuelva:** `CONSTITUTION.md` (raiz del motor, carga ON-DEMAND, leelo entero cuando lo consultes) tiene la jerarquia de 6 niveles y 15 tenets de ingenieria que amplian lo de abajo.

- **Contrato antes que fix:** identifica que comportamiento canonico protege el cambio antes de tocar codigo o tests.
- **Evidencia antes que relato:** ningun auto-reporte de agente es evidencia; usa diff, exit code, test, evento de bus, commit o artefacto verificable.
- **Un `exit 0` puede significar "no hice nada":** en operaciones IDEMPOTENTES o con SKIP (cierres, syncs, instaladores), `exit 0` es indistinguible de "ya estaba hecho" o "me salte el trabajo". `exit code` es evidencia NECESARIA pero no SUFICIENTE para estas: verifica el ARTEFACTO (fichero/informe/diff/contador que la operacion debia producir), no solo el codigo de salida; y busca en la salida las palabras de skip (`already`, `skipped`, `nothing to do`, `none present`, `up to date`, `no files to check`). Y lee el CODIGO antes de temer un flag: un `--force` puede vencer SOLO la idempotencia sin tocar los gates (leer 12 lineas convierte un "no me atrevo" en un cierre real). [F1]
- **El exit code tras una tuberia MIENTE (autoengano-por-pipe):** `$?` tras `cmd | tail` lee el rc del ULTIMO tramo de la tuberia (el consumidor), no del productor: un comando que FALLA se disfraza de exit 0. Cuando necesites a la vez esquilar la salida Y reportar el rc REAL, usa el wrapper aprobado `scripts/tools/run_and_exit.py` (WOT-2026-022p): `python scripts/tools/run_and_exit.py --tail 20 -- <cmd> [args...]` imprime las ultimas lineas y despues `[run-and-exit] exit_code: <n>`, y el proceso sale con ese mismo codigo (127 si el comando no existe, 2 si no hay comando). [F2]
- **Equivalencia de ruta productiva (evidencia exploratoria vs evidencia de cierre):** un `exit_code:` solo es evidencia de CIERRE si el probe **reproduce la ruta que corre en produccion**. Aplica **rigor proporcional**: obligatorio para todo lo que toca runtime (hooks, guards, CI, tests, scripts ejecutables, instalador); se salta para docs, typos y prosa sin logica de ejecucion. [F3]
- **El conflicto entre probes ES el hallazgo:** si dos mediciones del mismo hecho se contradicen, **no elijas la que confirma tu tesis, ni promedies, ni descartes la incomoda**: averigua QUE mide cada una, porque casi siempre **una de las dos no es produccion**. [F4]
- **Memoria despues de aprender:** si una familia de fallos puede repetirse, deja barrera automatica o deuda explicita con ticket y criterio de salida.
- **Rigor proporcional:** docs y typos no cargan la misma ceremonia que bus, supervisor, seguridad, rutas o estado compartido.
- **Barrera verificada:** un guard, hook o test nuevo no cuenta hasta demostrar que bloquea el fallo que promete bloquear.
- **Barrera cableada:** ademas de morder, algo tiene que INVOCARLA. Un guard solo es barrera si lo llama un camino que corre solo (pre-commit, CI, `prepush_check`, closeout, preflight, controlador, hooks de tool-call). Citarlo en un prompt, una skill o este AGENTS.md **no es cableado: es una norma**, y una norma depende de que alguien se acuerde. Barrera de la barrera: `scripts/check_guard_wiring.py` (WOT-2026-024u) - un guard nuevo sin cablear FALLA; la deuda legacy solo puede quedar en WARN si esta DECLARADA con su ticket dueno.
- **Aplicate tu propia vara (y que lo diga otro):** un guard que mide una propiedad P tiende a medirla con una vara MAS FLOJA que la que predica, y sale verde igual. [F5]
- **Barrera del alcance, no solo del mecanismo:** un guard puede estar cableado, morder, y no mirar donde ocurre el fallo. [F6]
- **Criterio invariante, evidencia fechada:** un DoD debe ser un INVARIANTE, no una MEDICION. Un criterio que fija un numero ("quedan 11 hits", "243 auditorias") caduca solo, sin que nadie toque la ficha, y el Builder ya no puede distinguir "el numero cambio porque el mundo avanzo" de "cambio porque he roto algo". El numero es EVIDENCIA: va etiquetado como snapshot fechado, nunca como criterio de aceptacion (WOT-2026-024t).
- **Un umbral en una MESETA no es un umbral medido** (corolario de la regla anterior, medido 2026-07-22): un numero puede pasar todos los gates y no haberse medido nunca. [F7]
- **Fixtures realistas:** un test verde contra un fixture irreal es sospechoso; cuando el contrato sea operativo, contrasta contra artefactos reales.
- **Gates self-service:** un gate preserva autonomia solo si explica que fallo, como reproducirlo y como volver a validar sin escalar al humano.
- **Relaunch con root verificado:** antes de relanzar Builder, valida `AGENT_PROJECT_ROOT`, `repo_motor`, `repo_destino`, bus legible y ticket activo.

Referencia ampliada: `.agent/rules/common/sustainable_engineering.md`. Los punteros
`[F1]`-`[F7]` de arriba son claves de referencia (letra = fichero, numero = ancla dentro de
ese fichero); leyenda completa en `docs/registry/reference_keys.md`. Casos forenses
completos: `.agent/rules/common/cem_v0_evidencia_forense.md`.

## Hacer ahora vs aplazar (criterio de decision)

El coste de APLAZAR **no es cero**. **Cada gate se responde con un ARTEFACTO, no con un juicio.** Ante duda no resuelta POR EVIDENCIA, **aplazar gana**. Ver criterio completo de 8 gates, balanza minima, STOP de degeneracion y dos reglas durables en .agent/rules/common/do_now_vs_defer.md.

## Skills Formales de Proceso

El repositorio define skills operativas formales para estructurar el trabajo del agente.
Úsalas invocando sus triggers (ej. `/tdd`, `/debug`):

- **Test-Driven Development (TDD)** (`skills/test-driven-development/SKILL.md`): Usar para asegurar cobertura y evitar regresiones en código nuevo o fixes. Obliga a escribir el test primero (Red), el código mínimo (Green) y refactorizar con calidad (`ruff` + `pytest`).
- **Systematic Debugging** (`skills/systematic-debugging/SKILL.md`): Usar ante errores no triviales. Exige investigación de causa raíz antes de parchear y establece un límite estricto de 3 intentos antes de detener la iteración y cuestionar el entendimiento del problema.

No uses estos skills si contradicen el flujo general (ej. usar TDD para escribir un README o depuración para un typo reportado por el linter).

### Gobierno skill<->prompt: skill apunta, prompt gobierna (WOT-2026-014r / X-09)

PROHIBIDO re-declarar criterios normativos (gates, veredictos, estados, barreras) en la `SKILL.md`: viven una vez en el prompt y la skill remite. Ver criterio de re-declaracion prohibido, auditoria automatica y matriz de ownership en .agent/rules/common/x09_skill_prompt_governance.md.

### Gobierno prompt-hijo<->prompt-nucleo: extension de X-09 un nivel arriba (2026-10-08)

El prompt-hijo REMITE a las secciones del nucleo que coinciden en OBJETO, no las REDECLARA en prosa paralela. Detalle y caso medido en .agent/rules/common/x09_skill_prompt_governance.md.

## Atribuciones externas (CREDITS.md)

**Limitación conocida:** CREDITS.md vive en raíz. Ver protocolo completo y formato de tabla en .agent/rules/common/credits_external_attributions.md.

## Memoria por proyecto

**Lo primero, porque es lo que mas se malinterpreta (WOT-2026-057a/b):**

- **Si tu contexto no trae el bloque delimitado del indice de memoria: ejecuta
  `python scripts/memory_context.py --bootstrap`.** Es un INDICE acotado (`id` +
  titular), no el corpus; el pie cuenta lo omitido.
- **`--recall` es la puerta de EXPANSION**, y entrega la leccion ENTERA:
  `python scripts/memory_context.py --recall --query "<termino>"` (ordenado por
  cobertura, con fallback por terminos) o
  `python scripts/memory_context.py --recall --id obs-<slug>` (exacto,
  fail-closed). Ejecutalo ANTES de medir o disenar.
- **El archive portable se lee como UNION de MOTOR + root activo**, con cuota por
  origen: la recencia no es relevancia, y sin cuota el repo tocado mas recientemente
  expulsa al otro entero.
- **El hook `SessionStart` inyecta el indice (solo Claude Code).** Sin hook, la
  comprobacion de arriba es el detector. La EXPANSION sigue siendo manual.
- **La memoria PRIVADA de un backend no es autoritativa:** lo canonico es lo
  versionado. Una leccion que solo vive en la memoria privada de un agente NO EXISTE
  para el sistema.

Arquitectura completa (jerarquia L3/L2/L1, `bus/memory_loader.py` y sus topes por
puerta, contrato de `MEMORY.md`, historia A1/A2 y limites declarados) -- referencia
bajo demanda, consulta al disenar o depurar el propio mecanismo de memoria:
`.agent/rules/common/memory_hierarchy.md`.

## deliverable_type (work_plan schema, V2)

Cada `work_plan.md` declara `deliverable_type` en su sección Metadata. Valores:
- `code` — el deliverable principal es código fuente (Python u otro).
- `documentation` — markdown, AGENTS.md, READMEs.
- `research` — análisis comparativos, reportes (gap analysis, repo-compare).
- `analysis` — estudios técnicos, audits.
- `mixed` — combinación legítima (ej. WP que toca código y docs).

`agent_controller --validate` valida que exista el campo y no tenga valores inválidos.

### Contrato operativo por tipo de ticket

El `deliverable_type` no es decorativo: cambia que evidencia debe producir el Builder y que debe
auditar el Manager. Detalle (referencia bajo demanda, consulta al redactar o revisar un
`work_plan.md`): `.agent/rules/common/deliverable_type_dispatch.md`.

## Quality gates dispatch by deliverable_type (WP-2026-089)

`builder-run-quality-gates` despacha los gates segun el `deliverable_type` del work_plan activo
via `scripts/run_gates_dispatch.py`: `code`/`mixed` -> ruff + pytest-safe + pip-audit
(condicional); `documentation`/`research`/`analysis` -> solo deliverable existence check.
Politica de pip-audit condicional, guard de alcance de ruff y detalle completo:
`.agent/rules/common/deliverable_type_dispatch.md`.

## Host-first skill precedence & Config Profiles (WP-2026-090)

En un destino, las skills del host (`<destino>/.agent/skills/`) toman precedencia absoluta sobre
las homonimas del bundle, que actua solo como fallback determinista. `agents.json` define
`active_profile`: `engine-dev` en el motor; `install_agent_system.py` lo cambia a `host-project`
en el destino durante `--install`/`--sync`. Detalle (referencia bajo demanda):
`.agent/rules/common/host_install_integration.md`.

## Host setup hook (WP-2026-094)

Si el destino declara un script ejecutable `.agent/host-setup.sh`/`.ps1`,
`scripts/install_agent_system.py` lo detecta tras la copia del bundle, muestra sus primeras 20 lineas y
solo lo ejecuta con confirmacion humana (`y/N`; `--yes` la salta); exit != 0 aborta el install y
propaga el codigo; sin hook, silencio. Detalle (referencia bajo demanda):
`.agent/rules/common/host_install_integration.md`.

## Pluggable manager review rubric by deliverable_type (WP-2026-091)

`bus/review_bridge.py` adapta el prompt de review del Manager al `deliverable_type` del plan
(tipo ausente o desconocido: fallback seguro y automatico a `code`) y conserva intacta la salida
canonica `DECISION: APPROVE` / `DECISION: CHANGES` (interoperabilidad con el bus y la maquina de
estados). Detalle (referencia bajo demanda): `.agent/rules/common/deliverable_type_dispatch.md`.

## Secretos y seguridad

- No guardes credenciales, tokens ni rutas sensibles.
- No toques `privada/`.
- No desactives `guard_paths` para trabajar mas rapido.
- No pidas dependencias nuevas sin aprobacion.
- `OpenCode Permission Preflight`: si el backend es OpenCode y el ticket toca rutas fuera de
  `.agent/collaboration/`/`scripts/`, verifica ANTES que esten permitidas en
  `.opencode/opencode.json` (`external_directory`); si no, bloquea el arranque con
  diagnostico claro. Detalle completo (allowlist de root, portabilidad del fichero
  versionado): `.agent/rules/common/opencode_permission_preflight.md`.
- Proteger `main` del motor en origin (WOT-2026-024i): `main` es la fuente
  canonica de los destinos; debe llevar un ruleset de GitHub que bloquee
  force-push y deletion (sin exigir PRs, para no romper el push directo del
  cierre). La activacion es accion humana; la verificacion re-ejecutable y la
  prueba de rechazo no destructiva viven en `RELEASE_CHECKLIST.md` (paso 6).

## Robust Builder Relaunch (WP-2026-084)

Tras un CHANGES, el supervisor verifica que el Builder siga vivo (PID + `tasklist`; fallback
mtime <15 min) antes de relanzar y pasa `-ResumeBuilder` al launcher, que entonces salta el
cleanup agresivo para no matar un Builder vivo; sin el flag, el launcher se comporta igual que
antes (aditivo, cero regresion). Detalle (referencia bajo demanda):
`.agent/rules/common/builder_relaunch.md`.

## Criterio de cierre

> Detalle operativo de los quality gates y comandos diarios (incluye flags exactos y secuencia recomendada): ver [QUICKSTART.md sección "6. Comandos diarios"](QUICKSTART.md#6-comandos-diarios).

Considera una tarea cerrada solo cuando:
1. `ruff`, `pytest` y `pip-audit` pasan.
2. El codigo nuevo usa rutas y manejo de errores correctos.
3. Las decisiones importantes quedan consolidadas en `PROJECT.md` o `CHANGELOG.md`.
4. La revision aplica el principio de Google de aprobar cuando el cambio mejora la salud del codigo, aun si no es perfecto: https://google.github.io/eng-practices/review/reviewer/standard.html
