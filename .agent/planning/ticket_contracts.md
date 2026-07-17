# Ticket Contracts

> Contratos formales de Contract Formation. Validacion mecanica:
> `python scripts/validate_contract_formation.py .agent/planning/ticket_contracts.md`
> El validador cubre ESTRUCTURA; `prompts/audit_cf_ticket_contract.md` cubre INTENCION
> y suficiencia. Ninguno sustituye al otro.

## WOT-2026-021k

- **status:** frozen
- **FROZEN CON WAIVER EXPLICITO -- NO es un frozen canonico.** `audit_cf_ticket_contract.md`
  exige `repo_charter.md` y `plan_graph.md` como **entradas obligatorias**, y **NINGUNO
  EXISTE en este repo** -> el **Intent Audit (punto 8 del checklist) es INEJECUTABLE**, no
  "debil": no hay Non-Goals / Quality Bar / Security Constraints contra los que contrastar.
  **Un auditor futuro que bloquee este contrato por eso TIENE RAZON.**
  - **Quien lo autoriza:** el USUARIO, 2026-07-13, de forma explicita.
  - **Alcance del waiver:** SOLO la ausencia de infra CF. **Todo lo demas del contrato esta
    verificado por probe EJECUTADO**, no por relato: premisa, regla del ceiling, las 2
    barreras, sus 2 mutaciones, la precedencia y el DoD-6.
  - **Por que no se bloquea:** la infra CF **nunca se materializo** en este repo (existen el
    validador y los prompts, no los artefactos). Bloquear 021k por eso seria **scope hijack**.
  - **Caducidad:** **WOT-2026-023m** (materializar charter + plan_graph, y **adaptar
    `audit_cf_ticket_contract.md` para que DISTINGA "repo sin CF materializado" de "contrato
    mal formado"**). **Su DoD-(e) es RETIRAR este waiver.**
  - **El waiver NO es precedente.** No lo copies a otro contrato: reclama 023m.
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Objective-Link:** OBJ-HERMETICIDAD -- ningun test que invoque git contra un fixture
  dentro del arbol del repo puede hacer que un guard de topologia **APRUEBE (rc=0)** una
  topologia que no es la suya. (El charter formal de este repo NO existe; ver
  CONTRACT_GAP-2.)
- **Plan-Link:** PLAN-SANDBOX-HERMETICITY (familia WOT-2026-020p/020q/020r/021k). El fix
  de RAIZ -- sacar `TEST_RUNTIME_ROOT` fuera del arbol -- es **ticket aparte** (blast
  radius: 4048 tests).

### Premise

Medido 2026-07-13 sobre HEAD `b81c6db`. **Este contrato es la v2: la v1 fue REFUTADA por
la auditoria adversarial y dos de sus claims eran FALSOS. Se documentan abajo para que no
se reintroduzcan.**

1. **El flaky historico YA NO SE DISPARA.** 7 corridas de suite completa concurrente, 0
   apariciones de `test_case_b`/`test_case_h`, **incluso con la barrera neutralizada**.
   Causa: **WOT-2026-020p** apago el DISPARADOR (`_pid_is_alive`, `tests/conftest.py:114`:
   impide purgar el sandbox de un worker xdist VIVO, que era lo unico que dejaba el `.git`
   incompleto).
   -> **El DoD original ("los 2 tests pasan 3 corridas seguidas") MIDE AZAR, NO CONTRATO:
   se habria cerrado en FALSO-VERDE.**

2. **El MECANISMO sigue vivo** (reproducido de forma DETERMINISTA, padre real y sintetico):
   un fixture git con el `.git` INCOMPLETO dentro del arbol hace que `git rev-parse`
   **ASCIENDA al repo padre**; `symbolic-ref` devuelve `main` (la rama del PADRE) y
   `check_topology` responde **rc=0** con `"topologia correcta: worktree del motor
   (_dev/main) y workspace correctos"` -> **el guard APRUEBA una topologia que no es la
   suya.** No es un rojo intermitente: es un **FALSO-VERDE SILENCIOSO**. **Ese rc=0 es EL
   DANO, y es lo unico que este ticket debe eliminar.**

   CONDICIONES NECESARIAS Y SUFICIENTES (padre SINTETICO basta):
   1. el fixture cuelga DENTRO del arbol de un repo padre cuya worktree en `main` tiene
      basename acabado en `_dev`;
   2. su `.git` esta INCOMPLETO (basta borrar `.git/HEAD`) -> git ASCIENDE;
   3. el workspace del fixture declara un link con `ticket_prefix: "WOT"` -> Verification B
      RESUELVE y no corta antes (**sin esto el probe MIENTE: da rc=2 y ENMASCARA el rc=0**);
   4. sin `GIT_CEILING_DIRECTORIES` en un **ancestro estricto**.

3. **REGLA REAL DEL CEILING (verificada por 3 probes independientes; la v1 la tenia AL
   REVES y la v2 la tenia INCOMPLETA):**

   > **`GIT_CEILING_DIRECTORIES` solo trunca el walk de git POR ENCIMA del ceiling.**
   > **El ceiling debe caer ESTRICTAMENTE ENTRE el directorio escaneado y el repo cuyo
   > ascenso quieres cortar.**
   > - ceiling **en el directorio escaneado** -> **ASCIENDE** (no protege);
   > - ceiling **por encima del repo ofensor** -> **ASCIENDE** (no protege: el walk llega
   >   al ofensor antes de tocar el ceiling);
   > - ceiling **entre ambos** -> **CORTA** (protege).

   > **CLAIM FALSO DE LA v1, NO LO REINTRODUZCAS:** "los 2 tests con barrera son PLACEBOS y
   > hay que migrar su ceiling hacia arriba". **ES FALSO.** Ponen el ceiling en `tmp_path` y
   > escanean `tmp_path/<algo>`, con el repo ofensor (el motor real) **por encima** de
   > `tmp_path`: el ceiling cae ENTRE ambos -> **SI PROTEGEN.** Esos 2 tests **NO SE TOCAN**
   > (ver Forbidden Surfaces). El error nacio de un artefacto de probe (ceiling puesto en el
   > propio dir escaneado), que **no es** lo que hacen los tests.

4. **`tmp_path` CAE DENTRO DEL ARBOL** (verificado ejecutando un test:
   `tests/sandbox/test_runtime/session_<pid>/factory/...`; `tests/conftest.py:20` +
   `ProjectTmpPathFactory`). Hoy **solo 2 ficheros** de test ponen ceiling
   (`tests/unit/test_check_worktree_topology.py`, `tests/unit/test_prefix_resolver.py`)
   -- **los 2 que ya se quemaron.** Es **disciplina post-mortem, no estructura**.

   > **HAY DOS AMENAZAS DISTINTAS, Y UN SOLO MECANISMO NO CUBRE LAS DOS** (esto tumbo a la
   > v2; verificado por probe):
   >
   > **AMENAZA A -- ascenso al MOTOR REAL.** Un test monta un fixture git bajo `tmp_path`
   > (que esta DENTRO del arbol) y git asciende al `.git` del motor. El **fixture autouse
   > global** con el ceiling en `tmp_path` **SI la mata** (el motor esta por encima de
   > `tmp_path` -> el ceiling cae entre medias). **Es la amenaza de PRODUCCION.**
   > **PERO SOLO para lo que cuelga de `tmp_path`:** lo que se construye FUERA (bajo
   > `REAL_SYSTEM_TEMP`, `tempfile.mkdtemp()`, rutas fijas) **NO queda cubierto** -- el
   > ceiling no es ancestro suyo. Residuo vivo: `tests/test_init_session_scratch.py`,
   > `tests/unit/test_run_pytest_safe.py`. **Follow-up, no scope de 021k.**
   >
   > **AMENAZA B -- ascenso a un PADRE SINTETICO que el propio test fabrica** bajo
   > `tmp_path` (es lo que hace el probe canonico: crea `motor/` + `motor_dev/` y cuelga el
   > fixture roto de `motor_dev/tests/sandbox/`). Ese padre esta **DEBAJO** del ceiling
   > global -> **el fixture global NO LO TOCA: sigue dando rc=0.**
   >
   > **CONSECUENCIA (el falso-verde que la v2 no vio):** un test de la AMENAZA B "protegido"
   > por el fixture global daria **rc=0 con y sin el fixture** -> su mutation-verify **no
   > discrimina nada**. Por eso el DoD de abajo tiene **DOS barreras separadas, cada una con
   > su mutacion**, y no una sola.

> ### ERRATUM FECHADO 2026-07-17 (WOT-2026-023p) -- NO es una correccion de este contrato
>
> **El texto de arriba NO se reescribe: era y SIGUE siendo tecnicamente correcto.** La REGLA
> REAL DEL CEILING de 021k (`ceiling == dir escaneado -> ASCIENDE`; `ceiling entre el dir
> escaneado y el repo ofensor -> CORTA`) se re-verifico con probe EJECUTADO el 2026-07-17
> (`python scripts/probe_sandbox_git_ascension.py`, motor `_dev` @ 7588ce6):
> `ceiling=scanned_dir -> rc=0` (falso-verde) y `ceiling=strict_ancestor -> rc=2`
> (fail-closed). La regla se confirma punto por punto.
>
> **Que cambia:** el residuo que 021k scopeo explicitamente como follow-up -- *"git invoked
> with cwd == tmp_path exactly ... KNOWN residue, follow-up, not 021k's scope"*
> (`tests/conftest.py`) -- queda **CERRADO** por **WOT-2026-023p**, que migra el ceiling del
> fixture autouse **GLOBAL** de `str(tmp_path)` a `str(tmp_path.parent)` (ancestro ESTRICTO
> de todo `tmp_path`, aun muy por debajo de `PROJECT_ROOT`). 023p **EJECUTA el follow-up que
> este contrato declaro**; no corrige un error suyo.
>
> **Que NO cierra (no conflacionar los dos follow-ups):** la Premise-4 de este contrato
> declara un follow-up DISTINTO -- los fixtures construidos FUERA de `tmp_path`
> (`REAL_SYSTEM_TEMP`, `tempfile.mkdtemp()`, rutas fijas: `tests/test_init_session_scratch.py`,
> `tests/unit/test_run_pytest_safe.py`), para los que el ceiling no es ancestro. **023p NO lo
> cierra** y sigue VIVO. Son dos residuos distintos: 023p cierra el de `cwd == tmp_path`.
>
> **Que NO cambia (Forbidden Surface de 021k, respetada):** los **2 ceilings MODULE-LEVEL**
> (`tests/unit/test_check_worktree_topology.py:137`, `tests/unit/test_prefix_resolver.py:322,417`)
> **NO se tocan.** Siguen poniendo su ceiling en `tmp_path` y escaneando `tmp_path/<algo>`
> (ancestro estricto -> SI protegen), tal y como este contrato establecio en su bloque
> *"CLAIM FALSO DE LA v1, NO LO REINTRODUZCAS"*. 023p toca **solo el ceiling GLOBAL de
> `tests/conftest.py`**: son dos superficies distintas y el claim prohibido NO se reintroduce.
>
> **Blast radius MEDIDO** (suite `--level all` con el ceiling nuevo, 2026-07-17): exactamente
> **3 tests CAMBIAN DE VEREDICTO** -- los 2 asserts del valor en
> `tests/unit/test_sandbox_git_hermeticity.py` y el falso-verde vivo
> `tests/test_delivery_hygiene_check.py::test_run_delivery_hygiene_check_artifacts_excluded`
> (que 023p convierte en repo local honesto con `git init`). Ningun otro test SE ROMPE:
> `tmp_path.parent` no sobre-corta nada legitimo (4393 passed / 3 failed esperados).
>
> **LIMITE DEL INSTRUMENTO (leccion de la auditoria adversarial 2026-07-17):** contar
> CAMBIOS DE VEREDICTO **no mide AFLOJAMIENTO de barreras**. Un test que sigue VERDE pero
> pierde discriminacion es INVISIBLE a ese recuento por construccion. Medido con mutacion:
> el ceiling nuevo dejaba 3 tests hermanos (`mutator_in_pre_push`, `no_stages`,
> `artifacts_not_excluded`) SOBRE-DETERMINADOS -- sin `.git` local, el ceiling forzaba
> `exit_code=1` por rc=128, y su `assert exit_code == 1` pasaba aunque el check de config
> estuviera muerto (mutacion: matar ambos checks -> PRE-023p 3 failed / 023p 3 passed).
> **023p les da `git init` propio** y la discriminacion queda restaurada (mutacion
> re-ejecutada: 3 failed). Medir aflojamiento EXIGE mutacion, no recuento de veredictos.

5. **rc=2 ES EL VEREDICTO CORRECTO, NO UN FALLO** (la v1 lo trataba como fallo -> DoD
   imposible). Con un `.git` corrupto la topologia **NO ES DETERMINABLE**: el veredicto
   honesto es **rc=2 (fail-closed)**, no rc=1 ("topologia incorrecta conocida"). Exigir rc=1
   era una **premisa falsa**: ninguna configuracion del ceiling lo produce, y el guard de
   produccion es Forbidden Surface -> el contrato v1 estaba **muerto al nacer**.

### Premise Re-check

Read-only, reproducible, determinista (no depende del azar del flaky):

```
command:   .venv\Scripts\python.exe scripts\probe_sandbox_git_ascension.py
expect:    "PREMISA VIVA: N falso(s)-verde(s) (rc=0)"  con N >= 1
           sin ceiling (o ceiling en el dir escaneado) -> rc=0   (falso-verde: EL DANO)
           ceiling en ancestro estricto                -> rc=2   (fail-closed: CORRECTO)
exit_code: 0
```

**El probe esta TRACKED** (`git ls-files scripts/probe_sandbox_git_ascension.py` -> no
vacio): se commiteo **ANTES** de congelar este contrato, para que el re-check sea
reproducible por un tercero en un clone fresco. (Nacio en `.agent/runtime/session/`, que es
scratch gitignored; dejarlo alli habria hecho que el Builder no pudiera correr su propia
puerta de entrada.)

Si el probe ya NO reproduce el rc=0 -> **la premisa esta MUERTA: PARAR y reencuadrar.**

### Context Baseline

- **Baseline:** motor `_dev` == principal == `origin/main` == `b81c6db`; arboles limpios.
  Suite `--level all`: **4048 passed / 0 failed**, `tested_sha == HEAD`.
- **Files Likely Touched (FLT):**
  - `tests/conftest.py` -- fixture **autouse GLOBAL** (`monkeypatch.setenv`, scope FUNCION)
    que fije `GIT_CEILING_DIRECTORIES` a **`tmp_path`** de cada test. Eso cubre la
    **AMENAZA A** (ascenso al motor real), que es la de produccion. **NO cubre la AMENAZA B**
    (padres sinteticos que el propio test fabrica bajo `tmp_path`) -- ver Premise-4.
  - Los **DOS tests nuevos** (BARRERA A y BARRERA B del DoD). Ubicacion libre **pero BAJO
    `tests/`**: el fixture global vive en `tests/conftest.py` y **solo alcanza a ese arbol**.
  - **`scripts/probe_sandbox_git_ascension.py` YA ESTA TRACKED** (commiteado antes de
    congelar este contrato, precisamente para que el `Premise Re-check` sea reproducible por
    un tercero). **NO es scope del Builder.**
- **NO se toca codigo de PRODUCCION.** El defecto vive en el HARNESS de test.
- **PRECEDENCIA DE CEILING (resuelta aqui; el Builder NO pregunta).**

  > **EL TERRENO NO ES LO QUE LAS v1/v2 DECIAN** (claim falso heredado, refutado con
  > `grep -n autouse`): **NO** hay "2 modulos con fixture de ceiling propio". Hay **DOS
  > FORMAS DISTINTAS** de ceiling propio, y **ambas GANAN al global, por mecanismos
  > distintos** (verificado):
  >
  > 1. **`tests/unit/test_check_worktree_topology.py` (16 tests):** fixture **autouse de
  >    MODULO** `_isolate_git_discovery` (l.131-137). Gana porque, a igual scope de funcion,
  >    los autouse de conftest se resuelven ANTES que los de modulo -> el `setenv` del modulo
  >    se aplica DESPUES.
  > 2. **`tests/unit/test_prefix_resolver.py` (42 tests): NO TIENE FIXTURE AUTOUSE
  >    (`grep -n autouse` -> VACIO).** Solo **2 de sus 42 tests** ponen ceiling, **INLINE en
  >    el cuerpo** (l.322 y l.417). Ganan porque el cuerpo del test corre despues de TODOS
  >    los fixtures. **Los otros 40 NO tienen ceiling hoy y PASARAN a heredarlo
  >    (`= tmp_path`) con el fixture global: es un CAMBIO DE COMPORTAMIENTO REAL sobre 40
  >    tests, y es esperado.** (Medido: siguen verdes.)

  **HAZLO ESTRUCTURAL, no declarativo:** el fixture global **DEBE** usar `monkeypatch.setenv`
  con **scope de FUNCION** (NO `scope="session"`, NO `os.environ` crudo), para que ambas
  formas ganen por construccion y no por accidente de orden. **DoD-6 lo verifica.** Si el
  global AFLOJA cualquiera de las dos -> **STOP**, corregir el scope del global; **nunca
  relajar una barrera existente para que pase el fix.**

- **COSTE ESPERADO (no es una regresion):** el fixture global pide `tmp_path`, asi que lo
  **MATERIALIZA en TODOS los tests** (`ProjectTmpPathFactory.mktemp` hace `mkdir`
  incondicional, `tests/conftest.py:49-64`) -> ~4048 directorios por sesion bajo
  `session_<pid>/factory/`. **Coste medido: ~3% en `tests/unit` (90s -> 93s), 0 fallos.** Es
  una consecuencia esperada del fix, no un bug.
- **Trampas de entorno (verificadas):** `--level all` corre **EN SERIE** (`resolve_xdist`,
  `run_pytest_safe.py:872-915`: xdist solo con `--level unit`) -> **NO ejerce el vector
  concurrente**; usar `--level unit --xdist-workers auto`. Para mutar: copiar a ruta CORTA
  (`C:\tmp\...`) o git revienta con "Filename too long". LEER "N passed / N failed" del
  output REAL, **NUNCA el exit code del wrapper**.

### Forbidden Surfaces

- **`scripts/check_worktree_topology.py`** -- el guard de PRODUCCION es GENUINO (verificado
  por mutation en 021g y de nuevo en 023i). El defecto vive en el harness. Tocarlo seria
  arreglar el termometro en vez de la fiebre.
- **`tests/unit/test_check_worktree_topology.py` y `tests/unit/test_prefix_resolver.py`** --
  **NO anadir ni migrar ceilings en estos 2 ficheros.** Los ceilings que ya tienen (un
  fixture autouse de modulo en el primero; **2 `setenv` inline** en el segundo, que **NO
  tiene fixture autouse**) **YA CORTAN** el ascenso: el ceiling cae ENTRE el dir escaneado y
  el motor. (La v1 mandaba "migrarlos hacia arriba" sobre una premisa FALSA; la v3 afirmaba
  que ambos tenian fixture de modulo, tambien FALSO. **Verifica con `grep -n autouse` antes
  de creerte cualquier descripcion de estos ficheros, incluida esta.**)
- **`tests/conftest.py:114` `_pid_is_alive` / `:155` `_purge_orphan_session_dirs`** -- son de
  WOT-2026-020p y FUNCIONAN. No romperlos.
- **Sacar `TEST_RUNTIME_ROOT` fuera del arbol** -- fix de RAIZ, blast radius alto. **Ticket
  aparte.** Si concluyes que es la unica salida -> CONTRACT_GAP.
- **`tests/test_init_session_scratch.py` / lock-TTL-takeover** -- es **WOT-2026-023l**,
  mecanismo DISTINTO. **Mezclarlos produce falso-verde en AMBOS.**

### DoD

Binario. Cada criterio es un comando con exit code o un test pass/fail.

> **DOS BARRERAS SEPARADAS, CADA UNA CON SU MUTACION.** La v2 las fundia en una y su
> mutation-verify **no discriminaba** (Premise-4, AMENAZA A vs B). **No las vuelvas a
> fundir.**

1. **BARRERA A -- el fixture global mata el ascenso AL MOTOR REAL.**
   Test: crear un directorio **plano** (sin `.git`) bajo `tmp_path` y assertar que
   `git -C <dir> rev-parse --git-common-dir` **NO resuelve** (falla; no devuelve el `.git`
   del motor).
   `command: pytest <test_barrera_a> -q` -> `expect: passed`
2. **MUTATION A (bidireccional, real):**
   - **con** el fixture global -> `git rev-parse` **falla** (rc != 0) -> test PASA;
   - **sin** el fixture global -> `git rev-parse` resuelve a `<motor>/.git` -> test **CAE**.
   (Medido: exactamente asi. Esta mutacion **si** discrimina.)
3. **BARRERA B -- la regla del ceiling, sobre el padre SINTETICO.**
   Test determinista que monta las 4 condiciones de la Premise (padre sintetico bajo
   `tmp_path`) y asserta el veredicto del guard segun **el ceiling INTERNO** (el que cae
   ENTRE el fixture y el padre sintetico):
   - **con** ceiling interno -> `check_topology` devuelve **rc == 2**;
   - **sin** ceiling interno -> devuelve **rc == 0** (el falso-verde).
   `command: pytest <test_barrera_b> -q` -> `expect: passed`
4. **MUTATION B (bidireccional, real):** la variable mutada es **el ceiling interno**, que
   es la que gobierna el resultado. **NO uses el fixture global aqui: no toca este caso**
   (el padre sintetico esta DEBAJO de `tmp_path`) y la mutacion daria rc=0 en **ambas**
   direcciones -> **mutation-verify que no discrimina = falso-verde de barrera.**
5. **rc=2 ES EXITO, NO FALLO.** Ambas barreras asertan **fail-closed**, no rc=1. **NO se
   exige rc=1**: no es alcanzable con el instrumento permitido y **no es el veredicto
   correcto** (Premise-5).
6. **El global NO AFLOJA ninguna barrera existente, y los 40 tests que heredan ceiling nuevo
   no cambian de veredicto.** Mide las TRES cosas a la vez (ver PRECEDENCIA en Context
   Baseline: NO son "2 modulos con fixture propio"):
   (a) el fixture autouse de modulo de `test_check_worktree_topology.py` (16 tests);
   (b) los **2** `setenv` INLINE de `test_prefix_resolver.py` (l.322, l.417);
   (c) los **40** tests de `test_prefix_resolver.py` que HOY no tienen ceiling y pasaran a
       heredarlo.
   `command: pytest tests/unit/test_check_worktree_topology.py tests/unit/test_prefix_resolver.py -q`
   -> `expect: >= 62 passed, 0 failed` (medido con el global simulado: **62 passed**).
7. **El Premise Re-check es reproducible por un tercero:** el probe esta **TRACKED**.
   `command: git ls-files scripts/probe_sandbox_git_ascension.py` -> **salida NO vacia**.
8. **Suite completa:** `run_pytest_safe.py --level all` -> **`0 failed`** y
   **`passed >= 4048`** del output REAL (habra +N por los tests nuevos; el criterio es
   "0 failed", no un numero exacto), `tested_sha == HEAD`.
9. **Suite CONCURRENTE:** `--level unit --xdist-workers auto` -> sin regresion.
   **OJO:** si ves rojo, **comprueba si es `TestMaidenVoyage` (WOT-2026-023l, flaky vivo al
   ~57%) ANTES de culpar a tu cambio.**

> **NO hay DoD de "auditar los N ficheros que invocan git"** -- pero **NO** por la razon que
> daba la v3, que era FALSA y merece quedar escrita:
>
> **CLAIM FALSO DE LA v3 (refutado por probe):** *"el fixture global cubre la AMENAZA A para
> TODOS por construccion: estructura en vez de disciplina"*. **ES FALSO, y se refuta con la
> propia regla del ceiling de la Premise-3:** el ceiling solo protege lo que cuelga **por
> debajo** de el. Un ceiling `= tmp_path` **no es ancestro** de nada que viva FUERA de
> `tmp_path`. **Medido:** con el global activo, un dir del arbol que no cuelga de `tmp_path`
> -> `git rev-parse` **ASCIENDE igual** al `.git` del motor.
>
> **La v3 RETIRO UN CRITERIO DE CIERRE APOYANDOSE EN UNA COBERTURA IMAGINARIA. Es EL MISMO
> MOVIMIENTO que produce los falsos-verdes que este ticket existe para matar**, reproducido
> dentro de su propio contrato. Queda aqui como aviso: no lo repitas.
>
> **ALCANCE REAL del fixture global:** cubre la AMENAZA A **para todo test cuyo fixture git
> cuelgue de `tmp_path`** -- que es el patron DOMINANTE, y por eso el fix vale la pena.
> **NO cubre** lo que se construye fuera de `tmp_path` (`REAL_SYSTEM_TEMP`,
> `tempfile.mkdtemp()`, rutas fijas). **Residuo VIVO y conocido (verificado con git grep):**
> `tests/test_init_session_scratch.py`, `tests/unit/test_run_pytest_safe.py` y el propio
> `tests/conftest.py` construyen bajo `REAL_SYSTEM_TEMP`.
>
> El censo de ese residuo **NO es criterio de cierre de 021k** (el DoD de la v1 no era
> binario: cuatro conteos dieron 43, 44, 48 y 27 segun el regex, y "o queda justificado con
> excepcion explicita" hacia descartable cualquier fichero con prosa). Es **FOLLOW-UP con un
> comando FIJADO** en su propia ficha.

### STOP conditions

- **El probe del Premise Re-check ya no reproduce el rc=0** -> premisa MUERTA: PARAR y
  reencuadrar. No implementar.
- **El fix exige tocar codigo de PRODUCCION** (`check_worktree_topology.py`) -> PARAR.
- **El fix exige sacar el sandbox del arbol** -> PARAR (blast radius; ticket aparte).
- **El fixture global no puede coexistir con los 2 de modulo sin AFLOJARLOS** -> PARAR
  (emitir CG). Nunca relajar una barrera existente para que pase el fix.
- **La suite concurrente se pone roja por `TestMaidenVoyage`** -> NO es tu cambio: es
  WOT-2026-023l. No lo arregles aqui.

### CONTRACT_GAP

Ante premisa falsa, ambiguedad, superficie prohibida necesaria o criterio incompleto, el
Builder emite `CG-WOT-2026-021k.md` y **BLOQUEA**. No muta el contrato en silencio.

- **CONTRACT_GAP-1 (RESUELTO en la v2 -- no preguntes):** *"se acepta rc=2 o hay que llegar a
  rc=1?"* -> **rc=2 ES EL OBJETIVO.** Con un `.git` corrupto la topologia no es determinable;
  fail-closed es el veredicto honesto. La v1 exigia rc=1 (inalcanzable con el instrumento
  permitido) y por eso estaba muerta al nacer.
- **CONTRACT_GAP-2 -- NO es un gap del Builder: es el WAIVER de este contrato.** Ver el bloque
  **FROZEN CON WAIVER EXPLICITO** arriba. Resumen: sin `repo_charter.md` / `plan_graph.md`, el
  **Intent Audit es INEJECUTABLE** y el `Objective-Link`/`Plan-Link` son **declarativos, no
  derivados**. Autorizado por el USUARIO (2026-07-13); **caduca con WOT-2026-023m**, cuyo
  DoD-(e) es retirarlo. **El Builder NO emite CG por esto** (ya esta resuelto arriba); si el
  Builder encuentra que la ausencia de charter le impide decidir algo CONCRETO de la
  implementacion, ESO si es un CG nuevo -> PARA y reporta.

### Builder clarification

**Builder clarification budget: 0.**

Las CUATRO preguntas que un Builder razonable haria estan respondidas **en el contrato**, no
en un documento de arranque. **Cada una tumbo una version previa de este contrato:**

1. *"se acepta rc=2 o hay que llegar a rc=1?"* -> **rc=2 ES el objetivo** (DoD-5,
   CONTRACT_GAP-1, Premise-5). Con un `.git` corrupto la topologia NO es determinable;
   exigir rc=1 seria hacer mentir al guard en la direccion contraria. **La v1 exigia rc=1 ->
   muerta al nacer.**
2. *"migro el ceiling de los 2 tests existentes?"* -> **NO. Ya es correcto** (Premise-3,
   Forbidden Surfaces). **Ese claim de la v1 era FALSO** y fue refutado por auditoria.
3. *"que ceiling gana si el global choca con el que ya existe?"* -> **gana el existente**, y
   por DOS mecanismos distintos (**NO hay "2 modulos con fixture propio": ese claim de la v3
   era FALSO**): el **fixture autouse de modulo** de `test_check_worktree_topology.py` gana
   porque los autouse de conftest se resuelven antes (a igual scope de funcion); y los **2
   `setenv` INLINE** de `test_prefix_resolver.py` (que **no tiene** fixture autouse) ganan
   porque el cuerpo del test corre despues de todos los fixtures. Por eso el global **DEBE**
   ser `monkeypatch.setenv` scope FUNCION. **DoD-6 lo verifica.** Si afloja alguno -> STOP.
4. *"basta el fixture global para que el test determinista pase?"* -> **NO, y este es el
   error que tumbo a la v2.** El fixture global (ceiling en `tmp_path`) **NO toca** un padre
   sintetico que el test fabrique **debajo** de `tmp_path`: seguiria dando rc=0 **con y sin
   el fixture** -> mutation-verify que no discrimina. Por eso el DoD tiene **DOS barreras
   separadas** (A: motor real, via fixture global; B: padre sintetico, via ceiling interno),
   **cada una con su mutacion**. **NO LAS FUNDAS.**

## WOT-2026-023r

- **status:** frozen
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **RECATEGORIZADO (v2).** La ficha y la v1 de este contrato lo llamaban **"FALSO ROJO"**. **Es
  una etiqueta INCOMPLETA y la auditoria adversarial la tumbo.** El test no registra UN modo de
  fallo, sino **DOS, indistinguibles desde el `AssertionError`**:
  - **modo LEGITIMO** (`same sid`): reentrada idempotente -> el sistema CUMPLE su contrato y el
    assert MIENTE. Es un falso rojo de verdad.
  - **modo CATASTROFICO** (`sids distintos`): **TOCTOU REAL en `_takeover_lock`** -> bug de
    PRODUCCION vivo (**WOT-2026-023s**).
  **Luego 023r no es "un falso rojo": es un TEST AMBIGUO.** Cerrarlo como falso rojo dejaria el
  TOCTOU **invisible a todo gate futuro**. Este contrato lo desambigua.
- **Objective-Link:** OBJ-TESTS-HONESTOS -- un test debe declarar bug si y solo si el sistema
  incumple su contrato, y **cuando falle debe decir DE QUE mecanismo habla**. Un assert que
  fusiona un comportamiento correcto con un bug real es peor que no tener test: hace
  inatribuible todo rojo futuro.
- **Plan-Link:** PLAN-SESSION-LOCK. Familia por MECANISMO: **023n** (ownership `(pid, sid)`,
  CERRADO) - **023r** (este: el TEST) - **023s** (TOCTOU de `_takeover_lock`, NUEVO, produccion)
  y **023l** (`got 0`, marker `.takeover`, SIN DETERMINAR). **Un mecanismo, un ticket. No los
  fundas.**

> **ESTE CONTRATO NO ES CF CANONICO, y no lo disimula.** `repo_charter.md` y `plan_graph.md` no
> existen en este repo -> el **Intent Audit es INEJECUTABLE** y `Objective-Link`/`Plan-Link` son
> **DECLARATIVOS, no derivados**. **NO es una copia del waiver de 021k** (que dice explicitamente
> que no es precedente): es la misma carencia de infra, propiedad de **WOT-2026-023m**.

### Premise

Medido 2026-07-13 sobre HEAD `13c9b91`. **La v1 de este contrato fue BLOQUEADA por la auditoria
adversarial: su Premise-4 era FALSA. Se deja escrito abajo para que no se reintroduzca.**

1. **El modo dominante NO es un bug del lock.** El fixture monta un lock EXPIRADO de pid AJENO
   (999999). El hilo A hace el takeover y **escribe un lock NUEVO con `os.getpid()` y el MISMO
   `sid`**. El hilo B lee ESE lock y entra por la rama idempotente de 023n
   (`init_session_scratch.py:452-454`, "held by THIS process for THIS session -> True") ->
   `wins = 2`. **Reentrada legitima, no dos propietarios.**
   `command: .venv\Scripts\python.exe scripts\probe_lock_reentrancy_got2.py` -> `exit 0`.
2. **La opcion (b) de la ficha esta REFUTADA.** Proponia "mismo sid -> el assert correcto es
   `wins == 2`". **FALSO Y MEDIDO:** con el MISMO sid, `A-luego-B` da 2 y `los-dos-en-takeover`
   da 1, **y AMBOS son correctos**. `assert wins == 2` seria TAN dependiente de la intercalacion
   como `assert wins == 1`: **el mismo pecado con el signo contrario.** No la implementes.
3. **!!! LA PREMISA QUE TUMBO LA v1 -- HAY *TRES* INTERCALACIONES, NO DOS !!!**
   La v1 afirmaba: *"con sids DISTINTOS, `wins == 1` en LAS DOS intercalaciones"*. **ES FALSO.**
   `_acquire_lock` lee el lock **UNA sola vez** (`:449`) y `_takeover_lock` **NO REVALIDA NADA**:
   gana el marker y hace `unlink()` **a ciegas** (`:490-491`). Un contendiente cuya decision
   "stale" quedo **OBSOLETA borra un lock VIVO Y AJENO** y escribe el suyo.

       I1  A-luego-B                 -> wins = 1
       I2  los-dos-en-takeover       -> wins = 1
       I3  TOCTOU (B lee stale, A completa el takeover, B despierta y ROBA)  -> wins = 2

   **Medido (verificacion independiente del orquestador, sids DISTINTOS):** `A=True`, `B=True`,
   lock final de `sid-b`, y **`_release_lock(sid-a) = False`** -> **A adquirio pero NO puede
   soltar: FALSA PROPIEDAD.** Es **exactamente la clase de bug que el docstring de
   `_acquire_lock` (`:430-433`) declara cerrada**: 023n cerro la ruta SECUENCIAL; **la
   CONCURRENTE sigue abierta**, y es **cross-process**.
   -> **Es WOT-2026-023s (produccion). NO se arregla aqui.**
4. **CONSECUENCIA (la que define el DoD):** `assert wins == 1` **NO es un invariante** mientras
   023s viva, **ni con sids distintos**. Con sids distintos SI queda **eliminado POR
   CONSTRUCCION** el modo dominante (el idempotente): `_acquire_lock` devuelve `holder == sid`,
   y con `holder=sid_a` / `sid=sid_b` eso es **False SIEMPRE**, sin pasar por el takeover
   (`:452-454`). **Lo que queda vivo es el TOCTOU, y es RARO** (el auditor: 800 rondas con
   scheduler natural -> 0 reproducciones; la ventana la abre el descheduling del SO bajo carga
   xdist). **Frecuencia residual: NO MEDIDA. No la inventes.**
5. **El test con HILOS no puede ser la victima de la mutacion.** Medido: con sids distintos,
   T1 **MUERE** en I1 pero **SOBREVIVE** en I2. Un mutation-verify sobre el es **una moneda al
   aire**. Las barreras DEBEN ser SECUENCIALES (T2, T3).
6. **La mutacion mata tests que YA EXISTEN.** `TestLockOwnershipIsIdentityAware` (`:1121`,
   `:1139`, de 023n) **cae con la MISMA mutacion aunque T2 y T3 no existan**. Por tanto
   **"el mutante murio" NO prueba nada de lo nuevo**: el mutation-verify **DEBE ejecutar T2 y T3
   AISLADOS por id** y ver caer **ESOS DOS**. (Es el falso-verde de mutation-verify que ya cazo
   la cadena 021t/021u: **no AISLA la rama mutada**.)

### Premise Re-check

```
.venv\Scripts\python.exe scripts\probe_lock_reentrancy_got2.py
```
-> `expect: exit 0`, `ESCENARIO 1 wins = 2`, `ESCENARIO 2 wins = 1`.
**Si no reproduce -> premisa MUERTA: PARAR y reencuadrar.** (Probe TRACKED desde `13c9b91`.)

### Context Baseline

- HEAD al congelar la v2: **`13c9b91`** (`_dev`/main, arbol limpio).
- **Suite baseline MEDIDA (no supuesta):** `--level all` -> **4058 passed, 0 failed** en 310s,
  `tested_sha == 13c9b91`. (Subio de 4057 a 4058 porque `scripts/encoding_guard.py:103` globa
  `scripts/**/*.py` y el probe nuevo anade un caso parametrizado.)
- **TRAMPA (auditor):** `collect_files_to_check()` globa el **DISCO**, no git. Un `.py` de
  scratch olvidado bajo `scripts/` **mueve el conteo**. Verificar `git status --porcelain -uall`
  antes de leer el numero.
- Codigo vivo (lineas verificadas): `_acquire_lock` `:422` (rama idempotente `:452-454`, lectura
  unica `:449`, caida al takeover `:457`) - `_takeover_lock` `:460` (unlink ciego `:490-491`, el
  perdedor del marker se rinde `:476-477`) - test defectuoso `tests/test_init_session_scratch.py:1032`
  y `TestLockOwnershipIsIdentityAware` `:1089`.
- El fichero de tests importa ya `_acquire_lock`, `_read_lock`, `_lock_is_live`, `_write_lock`,
  `_try_create_lock_exclusive` (`:31-49`) y `REAL_SYSTEM_TEMP` (`:51`); helpers `_make_repo`/
  `_sentinel_id` en `:59-70`. **El fix es implementable SIN tocar produccion.**

### Files Likely Touched

- `tests/test_init_session_scratch.py` -- **el UNICO fichero que muta este ticket.**
- `scripts/probe_lock_reentrancy_got2.py` -- ya tracked (`13c9b91`). **No volver a tocar.**

### Forbidden Surfaces

- **`scripts/init_session_scratch.py`** (`_acquire_lock` / `_takeover_lock` / `_release_lock`)
  -- **NO SE TOCA EN ESTE TICKET.** La rama idempotente (023n) es CORRECTA. El TOCTOU es REAL
  pero es **WOT-2026-023s**. Mezclar el fix del TEST con un fix de PRODUCCION concurrente es el
  patron que produjo el lio 023l/023n (un fix real que **no era EL fix**) y hace inatribuible
  todo rojo futuro. Si te ves obligado a tocarlo -> **PARA y emite CG**.
- **El modo `got 0`** -- es **WOT-2026-023l** (marker `.takeover`), mecanismo DISTINTO y SIN
  DETERMINAR. **NO lo arregles aqui.**
- **`tests/conftest.py`** -- 021k lo acaba de tocar y **023p** lo tocara. NO lo toques.

### DoD

Binario. Cada criterio es un comando con exit code o un test pass/fail.

1. **DoD-1 (CUMPLIDO en `13c9b91`): probe TRACKED.**
   `command: git ls-files scripts/probe_lock_reentrancy_got2.py` -> **salida NO vacia**.
2. **DoD-2 -- T1 desambiguado: competicion REAL (sids DISTINTOS) + ATRIBUCION.**
   `test_takeover_competition_exactly_one_wins` lanza los 2 hilos con **`sid` DISTINTO**; el
   assert `wins == 1` se CONSERVA. **El modo idempotente queda eliminado POR CONSTRUCCION**
   (Premise-4), no por suerte.
   **OBLIGATORIO -- el discriminante (BLOCKER-2 del auditor):** el test **cuenta los
   `_try_create_lock_exclusive` con exito** y lo pone **en el mensaje del assert**:
   **`creates == 2` -> TOCTOU (WOT-2026-023s)**; **`creates == 1` -> reentrada idempotente**
   (= el test perdio su montaje de sids distintos). **Sin esto, un `got 2` futuro vuelve a ser
   inatribuible y el ticket no ha resuelto NADA.**
   **T1 ASERTA SU PROPIO MONTAJE:** antes de la carrera, `assert` que el lock inicial esta
   **EXPIRADO** y es de **pid AJENO**, y que `sid_a != sid_b`.
   `command: pytest tests/test_init_session_scratch.py -k test_takeover_competition_exactly_one_wins -q`
   -> `expect: passed`
   > **T1 es un CANARIO, no una barrera.** Mientras 023s viva puede ponerse rojo (raro) por el
   > TOCTOU. **Eso NO es una regresion de este ticket**: el `creates=2` lo dira. **023s lo
   > ASCIENDE a invariante real** (su DoD lo recoge).
3. **DoD-3 -- T2, BARRERA determinista (SIN hilos), sobre la RUTA REAL.** Tras un takeover
   **REAL** (lock producido por `_takeover_lock`, **no escrito a mano**), una sesion AJENA del
   MISMO proceso **NO puede robar**:
   `_acquire_lock(dir, sid_a)` -> True ; `_acquire_lock(dir, sid_b)` -> **False**.
   **T2 ASERTA SU PROPIO MONTAJE (M-1 del auditor):** tras el takeover, `assert` que el lock es
   `pid == os.getpid()`, `session_id == sid_a` y **live**. **Sin ese assert, T2 es un clon
   cosmetico de `:1121`.**
   `command: pytest ... -k <T2> -q` -> `expect: passed`
4. **DoD-4 -- T3, BARRERA determinista (SIN hilos): la reentrada LEGITIMA sobre la RUTA REAL.**
   Tras el MISMO takeover real, el MISMO `sid` reentra -> **True** Y el lock queda
   **byte-for-byte IGUAL** (el assert de BYTES es lo que le da dientes). Aserta su montaje igual
   que T2. Documenta el `wins=2` legitimo que hacia falso el assert viejo.
   `command: pytest ... -k <T3> -q` -> `expect: passed`
5. **DoD-5 -- MUTATION-TO-PROVE, AISLADA POR ID (BLOCKER-3 del auditor).**
   En un **CLON bajo `C:\tmp`** (NUNCA en el arbol), revertir la rama de identidad de 023n:
       `if pid != os.getpid() and _is_pid_alive_best_effort(pid): return False`  -> cae al takeover
   - **Ejecutar T2 y T3 AISLADOS (por id) sobre el clon mutado -> AMBOS deben CAER.**
     (Medido en probe: T2 -> el 2o acquire da True; T3 -> el lock se REESCRIBE.)
   - **PROHIBIDO** dar por bueno el mutation-verify porque "el mutante murio": `:1121` y `:1139`
     (de 023n) **caen igual sin que T2/T3 existan** -> seria un **FALSO-VERDE de barrera**.
   - **T1 NO cuenta como victima** (Premise-5: sobrevive en I2).
   - **Restaurar el clon y verificar por bytes/md5**, no por "lo volvi a escribir".
6. **DoD-6 -- suite completa:** `run_pytest_safe.py --level all` -> **`0 failed`** y
   **`passed >= 4060`** (4058 + T2 + T3), leido del **output REAL**, **NUNCA del exit code del
   wrapper**. `tested_sha == HEAD` (suite **DESPUES** del commit).
7. **DoD-7 -- lint:** `ruff check` y `ruff format --check` **verdes**.
8. **DoD-8 -- backlog:** abrir **WOT-2026-023s** (TOCTOU, produccion) con la evidencia de
   Premise-3; **recategorizar la ficha de 023r** (TEST AMBIGUO, no "falso rojo"); anadir a
   **023l** la hipotesis del `got 0` como **HIPOTESIS, no como hecho**.

> **NO hay DoD de "5 corridas sin `got 2`"** -- y **NO** por ahorro, sino porque **NO ES
> BINARIO** (M-3 del auditor). Con el TOCTOU vivo, 5 corridas verdes **no prueban nada**: es el
> mismo razonamiento que el contrato aplica al `got 0` ("5 corridas verdes no son una prueba").
> **La eliminacion del modo dominante es ESTRUCTURAL (Premise-4), y eso SI se puede afirmar.**
> Un DoD estadistico aqui seria justo el falso-verde que este ticket existe para matar.

### STOP conditions

- **El probe del Premise Re-check ya no reproduce `wins=2`** -> premisa MUERTA: PARAR.
- **El fix exige tocar `_acquire_lock`/`_takeover_lock`** -> **PARAR y emitir CG.** Es 023s.
- **T2 o T3 NO caen bajo la mutacion AISLADA** -> no son barreras: PARAR y redisenarlas.
- **Aparece `got 0`** -> es 023l. RECOVERABLE: re-correr. **NO arreglarlo.**
- **Aparece `got 2` con `creates == 2`** -> es el TOCTOU (023s), **NO una regresion de 023r**.
- **Tentacion de "estabilizar" T1 quitandole los hilos** -> **NO.** T1 es el UNICO test que
  ejerce el takeover concurrente: es el canario de 023s y de 023l. Se DESAMBIGUA, no se desactiva.

### CONTRACT_GAP

Ante premisa falsa, ambiguedad, superficie prohibida necesaria o criterio incompleto, el Builder
emite `CG-WOT-2026-023r.md` y **BLOQUEA**. No muta el contrato en silencio.

- **CONTRACT_GAP-1 (RESUELTO -- NO preguntes):** *"opcion (a) o (b)?"* -> **(a) + T2 + T3.** La
  (b) esta **REFUTADA POR PROBE** (Premise-2).
- **CONTRACT_GAP-2 (RESUELTO -- NO preguntes):** *"y el TOCTOU que hace flaky a T1?"* -> **es
  WOT-2026-023s, ticket APARTE, y va DESPUES de este.** Decidido con el usuario 2026-07-13: el
  test roto contamina el gate ~3/4 de las corridas, luego **hay que calibrar el instrumento
  ANTES de usarlo para medir el fix de produccion**. **No lo arregles aqui.**
- **CONTRACT_GAP-3 (NO es un gap del Builder):** ausencia de infra CF -> es **023m**.

### Review 2 (fresh-context, mutante) -- lo que cazo

**APROBADO CON CAMBIOS. El BLOCKER que encontro es la leccion de 021k, repetida por mi:**

- **BLOCKER-1 -- T2/T3 pasaban VERDE sin ejercer el takeover.** `_reclaimed_by` asertaba solo el
  **POST**-estado (lock nuestro, vivo, con nuestro sid) -- **y un create fresco satisface los
  cuatro asserts**. Sin lock previo, `_acquire_lock` toma la rama `not lock_path.exists()`
  (`:446-447`) y crea el lock directamente: **`_takeover_lock` NO CORRE**. **Medido:** con el
  fixture saboteado (que no escribe lock), **las 2 barreras pasaban verde igualmente**,
  certificando una ruta que nunca recorrian. El contrato **exigia** este assert (DoD-3) y la
  implementacion **no lo cumplia**: el contrato acerto, el codigo no.
  **FIX:** `_reclaimed_by` aserta ahora el **PRE**-estado (lock **presente**, **pid AJENO**,
  **EXPIRADO**) antes del acquire. Con el sabotaje, las 2 barreras **CAEN**.
- **M-1 -- los dientes de T3 eran TEMPORALES, no estructurales.** Su unico discriminante era la
  comparacion de BYTES, y los dos locks difieren **solo en los timestamps**. En una maquina de
  reloj grueso (`time.get_clock_info('time').resolution` anuncia **15.6 ms** en esta) las dos
  escrituras podrian caer en el **mismo tick** -> lock **byte-identico** -> **T3 verde contra el
  mutante**. **FIX:** T3 cuenta las invocaciones de `_takeover_lock`: una reentrada idempotente
  **no puede** pasar por el takeover. **No depende de la resolucion del reloj.**
- **M-2 -- la atribucion no cubria el `got 0`.** El mensaje solo enumeraba `creates==2` y
  `creates==1`, **y ambos presuponen `wins == 2`**. El flaky VIVO (023l) es `wins == 0` y cae en
  ESTE test. **FIX:** el assert enumera ahora tambien `wins==0 -> WOT-2026-023l`.
- **M-3 (medido, se acepta):** T1 sigue rojo **~0.10%** (3/3000 carreras in-process). **TODOS** los
  rojos residuales salieron `wins=2, creates=2` = **el TOCTOU (023s), correctamente atribuido**.
  La atribucion FUNCIONA en vivo. Es el riesgo documentado del canario: **023s lo cierra.**

### Builder clarification

**Builder clarification budget: 0.**

**Honestidad sobre este budget:** la **v1 de este contrato fue BLOQUEADA** por la auditoria
adversarial (su Premise-4 era falsa: midio 2 de 3 intercalaciones y declaro estabilidad). Esta v2
**si** ha pasado por esa auditoria y por una verificacion independiente. Su budget 0 se apoya en
**MEDICIONES EJECUTADAS**, no en pedigri:

1. *"(a) o (b)?"* -> **(a)**, mas T2/T3. La (b) esta refutada (Premise-2, CG-1).
2. *"`assert wins == 1` es un invariante?"* -> **NO mientras 023s viva** (Premise-3/4). Es un
   **canario** con discriminante `creates`. **Conservalo, pero no lo vendas como barrera.**
3. *"Puedo usar T1 para el mutation-verify?"* -> **NO** (Premise-5). Las victimas son **T2 y T3**,
   **AISLADAS POR ID** (Premise-6, DoD-5).
4. *"Arreglo el TOCTOU / el `got 0`?"* -> **NO.** Son **023s** y **023l** (Forbidden Surfaces).

## WOT-2026-023s

- **status:** frozen
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Objective-Link:** OBJ-LOCK-HONESTO -- una adquisicion de lock NUNCA debe entregar propiedad
  que su release no reconoce. Un contendiente que "adquiere" (True) pero cuyo `_release_lock`
  devuelve False tiene FALSA PROPIEDAD: el lock nunca se suelta -> deadlock latente.
- **Plan-Link:** PLAN-SESSION-LOCK. **023n** cerro la ruta SECUENCIAL del robo de lock; **023s**
  cierra la CONCURRENTE (TOCTOU), que 023n dejo abierta. **023r** (el TEST) ya esta cerrado y
  dejo el test `test_takeover_competition_exactly_one_wins` como CANARIO de ESTE ticket.

### Premise

Medido 2026-07-13 sobre HEAD `e6ab17e`, con probe EJECUTADO.

1. **EL TOCTOU ES REAL Y REPRODUCE.** `_acquire_lock` lee el lock UNA sola vez
   (`init_session_scratch.py:449`); si lo ve stale cae a `_takeover_lock` (`:457`), que **NO
   REVALIDA**: gana el marker y hace `lock_path.unlink()` **a ciegas** (`:490-491`). Si entre la
   lectura stale y el unlink OTRO contendiente completo su takeover, el rezagado **BORRA un lock
   VIVO Y AJENO** y escribe el suyo.
   **Medido (sids DISTINTOS, sin azar):** `A=True`, `B=True`, lock final de `sid-b`, y
   **`_release_lock(sid-a) = False`** -> A adquirio pero NO puede soltar = **FALSA PROPIEDAD**.
   Es cross-thread Y cross-process.
2. **EL FIX CANDIDATO YA ESTA MEDIDO (no deducido), en un CLON.** Revalidar el lock **DESPUES de
   ganar el marker y ANTES del unlink** (`:488-491`): re-leer; si es VIVO y de OTRO `(pid, sid)`
   con pid vivo -> **return False** (no robar); si es VIVO y MIO -> **return True** (reentrada
   idempotente, no reescribir); si sigue stale -> proceder con el unlink+create como hoy.
   **Medido con el fix aplicado:**
   ```
   I3 TOCTOU dist-sid : A=True B=False wins=1  lock=sid-a  _release_lock(sid-a)=True
   I3 reentrada same  : A=True B=True  wins=2  (reentrada idempotente correcta)
   I1 A-luego-B dist  : A=True B=False wins=1
   takeover legitimo  : True  (lock stale de pid muerto -> se reclama)
   ```
3. **LA PREMISA QUE HACE SUFICIENTE EL FIX (escribirla o alguien reabre el bug):** el marker
   `.takeover` **SERIALIZA los takeovers entre si**. Enumeracion COMPLETA de los escritores de
   `lock.json` fuera del marker (corregida tras el plan-audit; la v1 decia "el UNICO es
   _try_create_lock_exclusive" y eso era una ENUMERACION INCOMPLETA presentada como completa):
   - **`_try_create_lock_exclusive`** en la rama "no existe lock" de `_acquire_lock` (`:446-447`):
     usa **O_EXCL**, solo escribe si NO hay lock. Si pisa entre el unlink y el create del takeover,
     el `_try_create_lock_exclusive` del takeover falla (FileExistsError) y devuelve False limpio.
   - **`_release_lock`** (`:509-521`): borra el lock, pero **solo si `(pid, session_id)` coincide
     con el llamante** -> NUNCA fabrica propiedad ajena; como mucho adelanta un unlink que el
     takeover iba a hacer igualmente (absorbido por el `suppress(OSError)`). Ademas hoy **no lo
     llama ningun `cmd_*` de produccion** (grep: solo aparece en tests).
   - **`_write_lock`** (`:375-386`, desde `cmd_init`): solo tras un `mkdir` EXCLUSIVO del session
     dir -> por construccion no hay lock previo ahi para ningun contendiente.
   **Ninguno puede producir falsa propiedad**, cada uno por una razon distinta y verificada. Por
   eso revalidar DENTRO del marker basta. **Un futuro que "optimice" o quite el marker REABRE el
   TOCTOU.**

### Premise Re-check

```
python <scratch>/verify_blocker1.py   (o su equivalente)  -> wins=2, _release_lock(sid-a)=False
```
Sobre HEAD, sin el fix, el TOCTOU reproduce. **Si NO reproduce -> premisa MUERTA: HARD STOP.**

### Context Baseline

- HEAD `e6ab17e`, 3 arboles limpios. Suite `--level all`: 4063 passed / 0 failed.
- `_read_lock`, `_lock_is_live`, `_is_pid_alive_best_effort`, `_try_create_lock_exclusive` ya
  existen y estan a mano de `_takeover_lock`. El fix NO anade dependencias.
- **023r dejo `test_takeover_competition_exactly_one_wins` como CANARIO** con instrumentacion de
  atribucion (`creates`). Con 023s cerrado, `assert wins == 1` (sids distintos) pasa a ser
  invariante en LAS TRES intercalaciones -> el canario **ASCIENDE a barrera**.

### Files Likely Touched

- `scripts/init_session_scratch.py` -- **`_takeover_lock` (`:488-491`), y SOLO ahi.**
- `tests/test_init_session_scratch.py` -- el test de la barrera del TOCTOU.

### Forbidden Surfaces

- **`_acquire_lock` (`:422-457`)** -- 023n es correcto. El fix vive en `_takeover_lock`, no aqui.
- **La logica del MARKER (`:467-486`)** -- **NO la toques.** Es la que SERIALIZA los takeovers y
  hace suficiente la revalidacion (Premise-3). Tocarla reabre el bug.
- **El modo `got 0`** -- es **WOT-2026-023l**, mecanismo DISTINTO (el marker, no el unlink). **NO
  lo arregles aqui.** Mezclarlos produce falso-verde en ambos.
- **`tests/conftest.py`** -- es 023p.

### DoD

Binario. Cada criterio = un comando con exit code o un test pass/fail.

1. **DoD-1 -- BARRERA: el TOCTOU cerrado, DETERMINISTA (SIN HILOS -- esto NO es cosmetico).**
   Medido por el plan-audit: el mismo escenario con HILOS REALES da `wins=2` solo ~1% de las
   veces (198/200 dieron wins=1 incluso SIN el fix). Un test con hilos pasaria el 99% del tiempo
   sobre el codigo ROTO -> mutation-verify hueco. **Serializar es la UNICA forma de que el DoD-4
   tenga dientes.** Test NUEVO que serializa I3 (A completa el takeover; B, que ya decidio stale,
   entra a `_takeover_lock` con sid AJENO):
   `_takeover_lock(dir, sid_b)` -> **False**, y el lock **sigue siendo de sid_a** (bytes de A
   intactos), y **`_release_lock(dir, sid_a)` -> True** (A conserva su propiedad).
   El test **ASERTA SU MONTAJE**: antes, `_acquire_lock(dir, sid_a)` reclamo un lock stale REAL.
2. **DoD-2 -- la reentrada legitima sigue viva.** Mismo escenario con MISMO sid: el 2o
   `_takeover_lock(dir, sid_a)` -> **True** y el lock queda byte-identico (idempotente).
3. **DoD-3 -- el takeover legitimo NO se rompe.** Un lock stale de pid muerto se sigue
   reclamando (`_acquire_lock` -> True). (Es el `test_expired_lock_of_a_dead_pid_is_still_reclaimed`
   existente; verificar que sigue verde.)
4. **DoD-4 -- MUTATION-TO-PROVE (clon bajo C:\tmp, AISLADA POR NODE-ID).** Quitar la revalidacion
   (volver al unlink a ciegas) -> **el test del DoD-1 CAE** (B roba el lock: B=True). Restaurar y
   verificar por bytes.
5. **DoD-5 -- ASCENDER EL CANARIO DE 023r.** `test_takeover_competition_exactly_one_wins` (sids
   distintos) con el fix: `wins == 1` es ahora invariante. **DoD: correr 5 veces
   `--level unit --xdist-workers auto` -> sin `got 2` con `creates == 2`** (el modo que era el
   TOCTOU). **Si aparece `got 0`, es 023l, RECOVERABLE, NO es este ticket.**
6. **DoD-6 -- suite:** `run_pytest_safe.py --level all` -> **0 failed**, output REAL, `tested_sha
   == HEAD`. **DoD-7 -- lint** verde.

> **Nota operativa (plan-audit, no bloqueante):** en el caso raro del TOCTOU, la revalidacion
> llama a `_is_pid_alive_best_effort`, que en Windows invoca `tasklist` (timeout 5s), y ahora eso
> ocurre DENTRO del marker (antes era fuera). El radio es solo otros contendientes de la MISMA
> sesion. No se mitiga aqui; se deja escrito para que un timeout de marker relacionado no sorprenda.

### STOP conditions

- **El TOCTOU ya no reproduce en el Premise Re-check** -> premisa MUERTA: HARD STOP.
- **El fix exige tocar el MARKER o `_acquire_lock`** -> PARA y emite CG.
- **La mutacion no mata el test del DoD-1** -> no es barrera: PARA y redisena.
- **Aparece `got 2` con `creates == 1`, o `got 0`** -> NO es este ticket (023r/023l).

### CONTRACT_GAP

Ante premisa falsa, ambiguedad o superficie prohibida necesaria, el Builder emite
`CG-WOT-2026-023s.md` y BLOQUEA.

- **CONTRACT_GAP-1 (RESUELTO):** *"revalidar como, exactamente?"* -> re-leer con `_read_lock`
  DENTRO del marker. **Orden de identidad IDENTICO al de `_acquire_lock:452-454`: PRIMERO pid,
  LUEGO sid** (si comparas solo sid, un lock de OTRO proceso que casualmente comparta session_id
  se trataria como "mio"). vivo + `pid==getpid()` + `sid` igual -> True (reentrada); vivo +
  `pid==getpid()` + sid distinto -> False; vivo + pid ajeno vivo -> False; stale -> proceder.
  **Medido** (Premise-2). NO uses O_EXCL para "detectar" al otro: el marker ya serializa (Premise-3).

### Builder clarification

**Builder clarification budget: 0.**

1. *"Toco el marker?"* -> **NO.** Es lo que hace suficiente el fix (Premise-3). Forbidden Surface.
2. *"Y si al revalidar el lock es MIO?"* -> **return True** (reentrada), no reescribir (Premise-2).
3. *"Arreglo el got 0 de paso?"* -> **NO.** Es 023l, otro mecanismo (el marker), sin determinar.
