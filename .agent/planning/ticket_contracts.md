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
