# Ticket Contracts

> Contratos formales de Contract Formation. Validacion mecanica:
> `python scripts/validate_contract_formation.py .agent/planning/ticket_contracts.md`
> El validador cubre ESTRUCTURA; `prompts/audit_cf_ticket_contract.md` cubre INTENCION
> y suficiencia. Ninguno sustituye al otro.

## WOT-2026-021k

- **status:** review
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
  - Los **DOS tests nuevos** (BARRERA A y BARRERA B del DoD; ubicacion a criterio del
    Builder, p.ej. `tests/unit/`).
  - **`scripts/probe_sandbox_git_ascension.py` YA ESTA TRACKED** (commiteado antes de
    congelar este contrato, precisamente para que el `Premise Re-check` sea reproducible por
    un tercero). **NO es scope del Builder.**
- **NO se toca codigo de PRODUCCION.** El defecto vive en el HARNESS de test.
- **PRECEDENCIA DE CEILING (resuelta aqui; el Builder NO pregunta):** los 2 tests que ya
  ponen su ceiling (`_isolate_git_discovery` a nivel de modulo) **CONSERVAN el suyo y GANAN**
  si hay colision. El fixture global es una **RED DE SEGURIDAD para los que NO lo ponen**,
  no un reemplazo.
  **Y NO BASTA CON DECLARARLO -- hay que hacerlo ESTRUCTURAL:** el fixture global **DEBE**
  usar `monkeypatch.setenv` con **scope de FUNCION** (NO `scope="session"`, NO `os.environ`
  crudo), para que el `setenv` del modulo se aplique DESPUES y gane por construccion, no por
  accidente del orden de autouse. **DoD-6 lo verifica** (los 62 tests de esos 2 modulos
  siguen verdes con el global activo). Si el global los AFLOJA -> **STOP**, corregir el
  scope del global; **nunca relajar una barrera existente para que pase el fix.**
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
  **su ceiling YA ES CORRECTO** (ancestro estricto). **NO migrarlos, NO "arreglarlos".**
  (La v1 de este contrato mandaba justo eso, sobre una premisa FALSA.)
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
6. **Los 2 modulos con ceiling propio siguen verdes CON el fixture global activo** (el
   global NO debe AFLOJARLOS):
   `command: pytest tests/unit/test_check_worktree_topology.py tests/unit/test_prefix_resolver.py -q`
   -> `expect: >= 62 passed, 0 failed`.
7. **El Premise Re-check es reproducible por un tercero:** el probe esta **TRACKED**.
   `command: git ls-files scripts/probe_sandbox_git_ascension.py` -> **salida NO vacia**.
8. **Suite completa:** `run_pytest_safe.py --level all` -> **`0 failed`** y
   **`passed >= 4048`** del output REAL (habra +N por los tests nuevos; el criterio es
   "0 failed", no un numero exacto), `tested_sha == HEAD`.
9. **Suite CONCURRENTE:** `--level unit --xdist-workers auto` -> sin regresion.
   **OJO:** si ves rojo, **comprueba si es `TestMaidenVoyage` (WOT-2026-023l, flaky vivo al
   ~57%) ANTES de culpar a tu cambio.**

> **NO hay DoD de "auditar los N ficheros que invocan git".** La v1 lo pedia sin fijar N
> (los conteos dieron 43, 44, 48 y 27 segun el regex): **no era binario, era
> auto-certificable.** El fixture autouse GLOBAL cubre la AMENAZA A para TODOS por
> construccion: **estructura en vez de disciplina.** Si se quiere el censo, es follow-up con
> un comando fijado, no un criterio de cierre de este ticket.

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
- **CONTRACT_GAP-2 (deuda de infra; NO bloquea este ticket -- decision del usuario
  2026-07-13):** este repo **no tiene** `.agent/planning/repo_charter.md` ni `plan_graph.md`,
  que `audit_cf_ticket_contract.md` exige como entradas. Consecuencia honesta: el **Intent
  Audit contra Non-Goals/Quality Bar/Security Constraints es NO VERIFICABLE**, y el
  `Objective-Link`/`Plan-Link` de arriba son **declarativos, no derivados**. Bloquear 021k por
  una infra que nunca se materializo en este repo seria **scope hijack**. -> **Follow-up
  propio** (materializar charter + plan_graph, y adaptar `audit_cf_ticket_contract.md` para
  distinguir "repo sin CF materializado" de "contrato mal formado").

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
3. *"que ceiling gana si el global choca con los 2 de modulo?"* -> **gana el de modulo**, y
   no por cortesia: el global usa `monkeypatch.setenv` con **scope de FUNCION**, asi que el
   del modulo se aplica despues. **DoD-6 lo verifica.** Si el global los AFLOJA -> STOP.
4. *"basta el fixture global para que el test determinista pase?"* -> **NO, y este es el
   error que tumbo a la v2.** El fixture global (ceiling en `tmp_path`) **NO toca** un padre
   sintetico que el test fabrique **debajo** de `tmp_path`: seguiria dando rc=0 **con y sin
   el fixture** -> mutation-verify que no discrimina. Por eso el DoD tiene **DOS barreras
   separadas** (A: motor real, via fixture global; B: padre sintetico, via ceiling interno),
   **cada una con su mutacion**. **NO LAS FUNDAS.**
