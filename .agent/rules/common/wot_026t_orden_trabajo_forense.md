# WOT-2026-026t -- Evidencia forense (casos completos)

> Modulo de referencia (`referencia-bajo-demanda`). Cada item es el caso forense COMPLETO y
> VERBATIM de la regla de `AGENTS.md` seccion "Orden de trabajo: AGRUPA los commits..." que lo
> cita con `[T<n>]`. La cuspide en `AGENTS.md` retiene solo la frase de refutacion corta con su
> clausula de mecanismo/alcance; este fichero conserva la narrativa completa del incidente.
> Citado desde `docs/registry/reference_keys.md` (letra `T`). Validado por
> `scripts/check_reference_keys.py`. Cada item lleva un ancla HTML (`<a id="t1"></a>`...)
> navegable por enlace (`#t1`) en GitHub/VS Code, ademas del ancla `**T1.**` que valida el guard.

<a id="t1"></a>
**T1.** No uses `-k` como evidencia de cobertura de una funcion compartida. El filtro selecciona por
nombre de clase/fichero, no por grafo de call-sites: una funcion ejercitada desde clases con
nombres distintos al filtro puede quedar sin cubrir aunque `-k` de verde. La evidencia final de
cobertura de una funcion compartida debe venir de la suite canonica completa (`--level all`),
nunca de un `-k` por nombre. Rationale completo (por que la comprobacion previa no bastaba, caso
medido WOT-2026-079d con 3 regresiones reales que `-k` dejo pasar): memoria de
`repo_motor`, `obs-canonical-suite-k-filter-insufficient-for-shared-function-coverage`
(2026-09-27).

Familia de la regla de la seccion (trasladado verbatim desde `AGENTS.md`, WOT-2026-120a):
**Es la misma familia que la regla del bucle** (`obs-canonical-suite-runs-after-the-loop-not-before`:
el bucle adversarial pide cambios, asi que una suite previa queda invalidada). Ahora generalizada:
**cualquier** escritura posterior invalida la corrida, venga de un bucle o de un commit propio.

<a id="t2"></a>
**T2.** Asignacion de rol en despacho trio (Manager/Builder/Revisor, WOT-2026-104k): cuando el
despacho de un ticket se reparte entre tres roles (protocolo `prompts/kilo_trio_dispatch/`),
SOLO el Manager corre la suite completa `--level all`, como gate de cierre, UNA vez,
inmediatamente antes del push -- tras TODOS los commits del ticket, nunca "antes del commit
final" (la regla de arriba ya fija que la suite es el ULTIMO paso, no uno intermedio). El
Builder se limita a tests focales del area tocada durante la implementacion (nunca `--level all`
como su propio cierre); el Revisor ejecuta de forma independiente sus propios tests focales
sobre el area modificada -- NUNCA cita ni espera una corrida del Manager, porque en el orden
canonico del trio (Manager -> Builder -> Revisor -> Manager-cierre) esa corrida todavia no
existe cuando el Revisor actua. Medido en vivo (2026-10-18, WOT-2026-104j, sesion hija 4 capas):
sin esta asignacion explicita, Builder y el Orquestador corrieron `--level all` CADA UNO por su
cuenta, ambas veces antes de que el Revisor tuviera turno -- exactamente el patron de
desperdicio que la regla de arriba ya advertia, mas una corrida redundante que la regla de
arriba no cubria (quien tiene PERMISO de correrla, no solo cuando). Verificado por bucle de
gobierno DESIGN_REVIEW (`UNI-5`, 4 lentes independientes: codex, opencode/glm, gemini, mistral;
3/4 `APROBAR_CON_CAMBIOS` tras corregir una redaccion anacronica del primer borrador). **Alcance
declarado, no se extiende por si solo:** esta regla cubre el protocolo trio
`prompts/kilo_trio_dispatch/`. NO toca `scripts/run_gates_dispatch.py` ni
`skills/builder-run-quality-gates` (hallazgo de la lente codex en el mismo bucle): esos
mecanismos sirven tambien a tickets de un solo Builder sin Revisor/Manager separados, donde el
Builder SI es el unico verificador legitimo de `--level all`.

**Enforcement mecanico anadido (WOT-2026-117a, no reemplaza esta narrativa, la complementa):**
hasta este ticket, la asignacion de rol de arriba era una NORMA (dependia de que el agente se
acordara). `scripts/check_manager_role_for_suite.py`, cableado en
`run_pytest_safe.py::main()` para `--level all`, la verifica de forma mecanica leyendo
`.agent/collaboration/TURN.md` (fila `**ROL**`, unico productor: `agent_controller.py::
update_turn_file()`) -- bloquea (exit 77) si el rol declarado no es MANAGER. Para no romper la
excepcion de arriba (Builder solo, via `run_gates_dispatch.py`), ese script declara una exencion
EXPLICITA por invocador conocido (`RUN_PYTEST_SAFE_SELFCHECK_EXEMPT`) en vez de inferirla de
TURN.md -- una primera version inferida de la ausencia de TURN.md rompia exactamente este caso
(regresion confirmada por revision adversarial, commit `ab0f4ba8` -> fix `7e24d07c`). Riesgo
residual declarado, no resuelto por este ticket: TURN.md proyecta la SIGUIENTE ACCION del
ticket (bus -> controller), no la identidad del PROCESO que invoca `--level all` -- un proceso
podria invocarla manualmente mientras TURN.md aun no se actualizo. Resolverlo del todo exigiria
un mecanismo de identidad de proceso/sesion nuevo, fuera del alcance de WOT-2026-117a.
