# Work Plan - WOT-2026-016z

## Metadata
- **ID:** WOT-2026-016z
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Guard de sesion anti-contaminacion de la identidad git local del motor (barrera preventiva, no aislamiento de fixture).
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Anadir un fixture autouse en tests/conftest.py que snapshotee git config --local
user.email y user.name del motor (PROJECT_ROOT) antes de cada test y, en teardown,
detecte si algun test los muto, los restaure al valor original y falle nombrando el
nodeid del test contaminante -- clonando exactamente el patron ya aprobado de
_isolate_controller_event_bus / _enforce_motor_bus_isolation /
motor_bus_isolation_guard (tests/conftest.py:250-293, WOT-2026-007f/016h).

Verificacion del objetivo (comando literal):
.venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v
da todos los tests en passed, incluyendo uno que demuestra MUTATION (sin el guard la
contaminacion simulada pasa desapercibida; con el guard, falla y restaura).

## Contexto (diagnostico de Fase 0 del Orquestador, CORREGIDO con evidencia -- premisa original de la ficha era falsa)

La ficha original de WOT-2026-016z asumia que "un fixture de test deja test@test.com
en la config LOCAL del motor -> recontamina en silencio". Fase 0 (Orquestador) CORRIGIO
esa premisa con evidencia dura:

1. Grep exhaustivo de "git config user.email" / "git config --local user.email" en
   tests/: cada una de las ocurrencias encontradas usa cwd=tmp_path, cwd=repo,
   cwd=repo_path o cwd=repo_root -- repos temporales de fixture, NUNCA PROJECT_ROOT
   (el motor real).
2. Las ocurrencias que usan literalmente test@test.com
   (tests/test_delivery_hygiene_check.py:348/371/420) tambien usan cwd=tmp_path.
3. Prueba empirica decisiva: correr
   pytest tests/test_delivery_hygiene_check.py tests/test_destination_context.py
   (47 tests) NO altero la config local del motor
   (git config --local user.email = noreply ANTES y DESPUES de la corrida). Ningun
   fixture activo contamina el motor hoy.
4. La config local del motor esta limpia ahora mismo (verificado en esta sesion,
   2026-07-04): git config --local user.email =
   128408907+FDL32@users.noreply.github.com, git config --local user.name = FDL32.

Conclusion: el dano de WOT-2026-016w (commits historicos con autor
Test <test@test.com>) fue de origen MANUAL/historico (alguien ejecuto
git config --local user.email test@test.com en el motor una vez), NO un fixture de
test. Ya esta corregido y no hay fixture que aislar.

Pero hay valor defensivo real (decision del humano): implementar una BARRERA
PREVENTIVA. Aunque ningun fixture contamina hoy, no existe barrera que IMPIDA la
recontaminacion futura (un test nuevo con cwd=motor por error, o repetir el comando
manual). El pre-push cazo el dano de 016w tarde (post-commit); este ticket anade una
barrera que lo detecta ANTES, en el mismo ciclo de test, con el mismo mecanismo ya
aprobado para el bus de eventos.

## Diseno del guard (verificado en codigo contra el modelo, tests/conftest.py:218-293)

El modelo (bus de eventos) tiene 4 piezas que este ticket replica 1:1 para la identidad
git:

1. _MOTOR_EVENTS_FILE (constante de ruta) -> equivalente nuevo: no hace falta una ruta,
   el "recurso" observado es la salida de dos comandos git config --local con
   cwd=PROJECT_ROOT.
2. _restore_motor_bus_if_changed(events_file, before) -> bool (lee estado actual,
   compara con before, restaura si cambio, retorna si cambio) -> equivalente nuevo
   _restore_motor_git_identity_if_changed(before: tuple[str | None, str | None]) -> bool.
3. _enforce_motor_bus_isolation(events_file, before, nodeid) -> None (si
   _restore_... reporta cambio, pytest.fail con el nodeid) -> equivalente nuevo
   _enforce_motor_git_identity_isolation(before, nodeid) -> None.
4. motor_bus_isolation_guard fixture que expone la funcion de enforcement para tests de
   barrera -> equivalente nuevo motor_git_identity_guard fixture que expone
   _enforce_motor_git_identity_isolation.
5. _isolate_controller_event_bus fixture autouse que hace snapshot al inicio y llama al
   enforcement en el finally del yield -> equivalente nuevo
   _isolate_motor_git_identity fixture autouse.

### Que lee el guard

Dos valores por separado (no una tupla concatenada en string), leidos con
subprocess.run(["git", "config", "--local", "user.email"], cwd=PROJECT_ROOT,
capture_output=True, text=True) y el mismo comando con "user.name". PROJECT_ROOT
ya existe como constante en tests/conftest.py linea 17 (no crear una nueva _MOTOR_ROOT;
usar la ya presente para no duplicar la nocion de "root del motor" con dos nombres).
Si el comando devuelve returncode distinto de 0 (clave ausente, caso raro pero valido en
git), tratar el valor como None (git config con clave ausente sale con returncode 1 y
stdout vacio); no lanzar excepcion en ese caso, es un estado legitimo (aunque no se
espera en este repo, que ya tiene ambas claves seteadas).

### Como detecta cambio y restaura

_restore_motor_git_identity_if_changed(before) lee el estado ACTUAL (misma llamada
subprocess.run que en el snapshot inicial) y compara before == after (tupla de 2
str-o-None). Si son iguales, retorna False (no hubo cambio, nada que restaurar). Si
difieren, restaura cada clave INDEPENDIENTEMENTE:
- Si before del indice i no es None: git config --local user.email (o user.name) con
  el valor original como argumento.
- Si before del indice i es None (la clave no existia antes, caso defensivo): git
  config --local --unset user.email (o user.name), con manejo de returncode 5 (clave ya
  no existe) para no fallar si ya esta ausente.
Retorna True (hubo cambio, se restauro).

### Como falla con nodeid

_enforce_motor_git_identity_isolation(before, nodeid): si
_restore_motor_git_identity_if_changed(before) retorna True, pytest.fail(pytrace=False)
con un mensaje que (a) nombra el nodeid contaminante y (b) es accionable: instruye usar
git -c user.email=... -c user.name=... inline, o cwd=tmp_path / cwd=repo (fixture de
repo temporal), nunca git config --local persistente sobre PROJECT_ROOT. Mensaje
literal (Builder lo usa tal cual, interpolando solo el nodeid):

Test mutated the real motor git identity (user.email/user.name) and was isolated:
{nodeid}. Use a git -c user.email=... inline override or cwd=tmp_path/cwd=repo (a
temporary repo fixture); never a persistent git config --local change on the real
motor.

### Scope: per-test (no session) -- razonamiento del trade-off

El ticket pide razonar per-test vs session. Decision: per-test, igual que el bus.

- Por que NO session-scope: el criterio de aceptacion 1 exige "un fixture autouse
  snapshotea la identidad git del motor y falla (NOMBRANDO EL TEST) si un test la
  muta". Con scope de sesion, el snapshot se toma una sola vez al inicio de toda la
  corrida y la comparacion final solo puede decir "la identidad cambio en algun punto de
  la sesion completa", sin poder atribuir el cambio a un test concreto (podrian haber corrido
  miles de tests entre el snapshot y la deteccion). Para nombrar el nodeid exacto hace
  falta snapshotear y comparar ALREDEDOR DE CADA TEST, que es exactamente el scope
  per-test.
- Costo real de per-test: 2 subprocesos (git config --local user.email / user.name) por
  test, leidos una vez al entrar y una vez en el finally (no 4): el "before" de cada
  test ya es el estado restaurado tras el test anterior, asi que basta con snapshotear
  una vez al abrir el yield y una vez en el finally. Esto es exactamente lo que hace el
  patron del bus (una lectura al entrar, una en el finally): 2 lecturas por test, no 4.
  Es mas caro que el bus (que solo hace Path.read_bytes(), sin subproceso), pero el
  costo absoluto de un git config --local --get es del orden de milisegundos y el repo
  ya paga costos similares en otros fixtures autouse (_clear_runtime_project_root_cache
  importa un modulo en cada test). No es un cambio de orden de magnitud en el tiempo de
  la suite canonica comparado con los mas de 3400 tests existentes.
- Conclusion: per-test es la unica opcion que cumple el criterio de aceptacion (nombrar
  el test exacto) y su costo es marginal frente al resto de la suite.

## Alcance (cambio minimo, clonar el patron del bus)

Anadir a tests/conftest.py:
1. import subprocess (no esta importado hoy; verificado con grep).
2. Reusar PROJECT_ROOT (YA existente en tests/conftest.py linea 17) como cwd; no crear
   una constante _MOTOR_ROOT duplicada.
3. _read_motor_git_identity() -> tuple[str | None, str | None] (email, name).
4. _restore_motor_git_identity_if_changed(before: tuple[str | None, str | None]) -> bool.
5. _enforce_motor_git_identity_isolation(before: tuple[str | None, str | None], nodeid: str) -> None.
6. Fixture motor_git_identity_guard que expone _enforce_motor_git_identity_isolation
   (para el test de barrera).
7. Fixture autouse _isolate_motor_git_identity(request) que snapshotea al entrar,
   hace yield, y en el finally llama al enforcement -- estructura identica a
   _isolate_controller_event_bus.

Crear tests/unit/test_motor_git_identity_barrier.py con 3 tests que repliquen la misma
estructura de tests/unit/test_motor_bus_isolation_barrier.py (mismos 3 casos:
cambia-valor-existente / crea-valor-nuevo-que-no-existia / no-cambia-nada), pero
simulando el antes/despues de la identidad git con TUPLAS EN MEMORIA via monkeypatch de
la funcion lectora interna (nunca invocando git config --local real sobre el motor ni
sobre ningun repo real): el test usa monkeypatch.setattr sobre el simbolo del modulo
conftest que lee el git config (o equivalente) para forzar el valor "after" simulado, y
llama a motor_git_identity_guard(before_simulado, nodeid) para forzar la rama de
"cambio detectado". Ver seccion "Barrera" del reporte final para el mecanismo exacto sin
contaminar.

### Non-goals

- NO tocar los fixtures existentes de tests (usan tmp_path/cwd=repo, ya estan bien;
  migrarlos es scope creep -- follow-up si el humano lo pide).
- NO tocar _isolate_controller_event_bus, _restore_motor_bus_if_changed,
  _enforce_motor_bus_isolation ni motor_bus_isolation_guard, ni el archivo
  test_motor_bus_isolation_barrier.py existente.
- NO anadir un hook pre-commit/pre-push nuevo. El pre-push ya existe y cazo 016w; este
  ticket es una barrera de TEST (sesion de pytest), no de git hooks.
- NO cambiar la config git real del usuario (global) ni la config local actual del
  motor: el guard solo debe RESTAURAR si detecta cambio durante la suite, nunca alterar
  el valor de partida cuando no hay contaminacion.
- NO crear una constante _MOTOR_ROOT nueva: reusar PROJECT_ROOT (tests/conftest.py
  linea 17).

## Files Likely Touched

### repo_motor

- tests/conftest.py
- tests/unit/test_motor_git_identity_barrier.py

## Tests Esperados

1. Nuevo tests/unit/test_motor_git_identity_barrier.py con 3 tests, paralelos a
   test_motor_bus_isolation_barrier.py:
   - test_motor_git_identity_barrier_restores_existing_value: usa monkeypatch para que
     la funcion lectora interna (la que el guard usa para leer el estado "after" real)
     devuelva un valor simulado distinto del "before" tambien simulado que el test
     pasa. Con el "after" simulado distinto del "before" simulado, el guard debe
     intentar restaurar (verificar via el mismo monkeypatch que la llamada de
     restauracion se invoco con el valor de before) y pytest.fail con el nodeid en el
     mensaje. Usar pytest.raises(pytest.fail.Exception, match=...) igual que el test
     equivalente del bus.
   - test_motor_git_identity_barrier_handles_previously_unset_value: before = (None,
     None) simulado (paridad con "crea archivo nuevo" del bus) y "after" simulado con
     un valor -- el guard debe fallar y la restauracion (verificada via monkeypatch)
     debe invocar el camino de --unset en vez de escribir un valor.
   - test_motor_git_identity_barrier_allows_unchanged_value: before y "after" simulados
     IGUALES -- el guard NO debe fallar ni intentar restaurar (verificar via
     monkeypatch que no se invoco ninguna escritura).
   Los 3 tests usan monkeypatch (fixture pytest estandar) para interceptar la funcion
   que el guard usa para leer/escribir el git config real, de forma que NINGUN
   subprocess real toque PROJECT_ROOT durante estos 3 tests. Esto satisface el
   requisito explicito del ticket de no contaminar de verdad el motor.
2. MUTATION (documentado en execution_log.md, no como test pytest nuevo separado):
   demostrar, invocando directamente la funcion de enforcement
   _enforce_motor_git_identity_isolation con un before y un "after" simulados (via el
   mismo monkeypatch de los tests de barrera) que representan "no cambio", que el guard
   NO falla (rama sin contaminacion); y luego con un "after" simulado que representa
   "cambio", que el guard SI falla con el nodeid en el mensaje (rama con
   contaminacion). Esto ya queda cubierto por los 3 tests de barrera del punto 1 (el
   tercer test es el caso "sin contaminacion no dispara fallo"; los dos primeros son el
   caso "con contaminacion, el guard la caza y restaura"). Registrar en
   execution_log.md el resultado literal de ambas ramas (pasa-sin-fallo /
   falla-con-mensaje-nodeid), citando los nombres exactos de los 3 tests como evidencia.
3. No-regresion: la suite completa de tests/unit/test_motor_bus_isolation_barrier.py
   sigue en verde (el guard nuevo no debe interferir con el fixture del bus: ambos
   fixtures autouse coexisten en el mismo conftest.py).

## Criterios de Aceptacion (binarios)

1. Un fixture autouse en tests/conftest.py (_isolate_motor_git_identity) snapshotea
   git config --local user.email y user.name del motor al inicio de cada test y, en
   teardown, si detecta que un test los muto, RESTAURA el valor original y falla con
   pytest.fail(pytrace=False) nombrando el request.node.nodeid del test contaminante.
   Verificado leyendo el codigo final de tests/conftest.py y confirmando que la
   estructura es paralela a _isolate_controller_event_bus (snapshot en apertura del
   yield, enforcement en el finally).
2. La barrera es viva: .venv/Scripts/python.exe -m pytest
   tests/unit/test_motor_git_identity_barrier.py -v da 3 passed, 0 failed -- los tests
   que simulan contaminacion (via monkeypatch, sin tocar el motor real) demuestran que
   el guard dispara pytest.fail con el nodeid esperado en el mensaje, y el test de "sin
   cambio" demuestra que el guard NO falla cuando no hay contaminacion.
3. MUTATION: documentado literalmente en execution_log.md con las dos ramas
   (sin-contaminacion no dispara fallo / con-contaminacion dispara fallo con el nodeid
   y restaura el valor). No basta con narrar "se verifico"; se exige el nombre del test
   o la llamada exacta y el resultado.
4. git config --local user.email y git config --local user.name del motor, leidos
   DESPUES de correr la suite canonica completa, siguen siendo
   128408907+FDL32@users.noreply.github.com / FDL32 (sin cambio real: el guard nuevo no
   debe alterar el estado de partida cuando no hay contaminacion real durante la
   corrida).
5. Suite canonica: .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all con
   last-run.json en status=finished, exit_code=0, level=all,
   args_mode=default_discovery y tested_commit_sha == HEAD del commit que se entrega.
6. ruff check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py -> exit
   code 0.
7. uv run ruff format --check tests/conftest.py
   tests/unit/test_motor_git_identity_barrier.py -> exit code 0 (si uv no arranca en
   este entorno segun el diagnostico ya documentado de WOT-2026-016c, usar
   .venv/Scripts/python.exe -m ruff format --check con las mismas rutas como
   equivalente y documentar la sustitucion en execution_log.md; no declarar el gate
   como "no aplica" sin evidencia).
8. validate (Manager gate, ver abajo) en 0 errors / 0 warnings.

## Quality Gates

- Builder ejecuta:
  - .venv/Scripts/python.exe -m pytest tests/unit/test_motor_git_identity_barrier.py -v
  - .venv/Scripts/python.exe -m pytest tests/unit/test_motor_bus_isolation_barrier.py -v
    (no-regresion del hermano)
  - ruff check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py
  - uv run ruff format --check tests/conftest.py tests/unit/test_motor_git_identity_barrier.py
  - .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
  - git config --local user.email y git config --local user.name (antes y despues de
    la corrida completa; deben coincidir)
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json --project-root .

## STOP conditions

- Si el guard nuevo requiere tocar _isolate_controller_event_bus,
  _restore_motor_bus_if_changed, _enforce_motor_bus_isolation o
  motor_bus_isolation_guard: DETENTE, es fuera de scope (Non-goals); el guard nuevo debe
  coexistir como fixture independiente, no fusionarse con el del bus.
- Si el unico modo de simular contaminacion en los tests de barrera termina invocando
  git config --local real con cwd=PROJECT_ROOT (el motor real) en vez de monkeypatch:
  DETENTE, viola el requisito explicito de no contaminar el motor real; usa
  monkeypatch.setattr sobre la funcion lectora interna.
- Si tras correr la suite canonica completa git config --local user.email o user.name
  del motor real cambiaron de forma PERSISTENTE (no restaurada): DETENTE, el guard tiene
  un bug de restauracion; no se puede cerrar el ticket con la identidad del motor
  alterada.
- Si run_pytest_safe.py --level all no cierra con tested_commit_sha == HEAD del commit
  final: no reportes cierre canonico; re-corre tras el commit final antes de
  --mark-ready.
- Si "uv run ruff format --check" no arranca en este entorno (mismo sintoma documentado
  en WOT-2026-016c): no lo declares "no aplica"; usa
  .venv/Scripts/python.exe -m ruff format --check con las mismas rutas como equivalente
  y documenta la sustitucion con el output literal en execution_log.md.

## Riesgos

- Bajo: el patron a clonar (_isolate_controller_event_bus) ya esta en produccion desde
  WOT-2026-007f/016h, revisado y con su propia barrera de tests
  (test_motor_bus_isolation_barrier.py) como precedente directo.
- Medio: el mecanismo de simulacion sin contaminar (monkeypatch de la funcion lectora)
  es mas indirecto que el del bus (que usa un archivo real en tmp_path, porque el
  "recurso" ahi es un path). Mitigado exigiendo en Tests Esperados que el Builder
  documente explicitamente cual simbolo interno se monkeypatchea y por que eso basta
  para probar la logica de deteccion/restauracion sin tocar subprocess o git real.

## Decision Arquitectonica

Clonar el patron ya aprobado del bus de eventos (snapshot, yield, enforcement en el
finally, con una fixture que expone la funcion de enforcement para tests de barrera) en
vez de disenar un mecanismo nuevo. Minimiza el riesgo (patron ya revisado y con
precedente de barrera propio) y el diff. Alternativas descartadas: ver Trade-offs.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Clonar el patron per-test del bus (snapshot/yield/finally) | Paridad exacta con mecanismo ya aprobado y con barrera propia; nombra el test exacto | 2 subprocesos extra por test (costo marginal) | Elegida |
| Guard de sesion (snapshot unico al inicio, comparacion al final) | Mas barato (2 subprocesos por sesion) | No puede nombrar el test contaminante exacto; no cumple el criterio de aceptacion 1 tal como esta redactado | Descartada |
| Hook pre-commit/pre-push nuevo | Cazaria contaminacion persistida | Fuera de scope explicito (Non-goals); el pre-push ya existe y cazo 016w; este ticket es sobre barrera de TEST, no de git hooks | Descartada |

## Criterios de Aceptacion Global
- [ ] Fixture autouse _isolate_motor_git_identity snapshotea y restaura user.email/user.name del motor, fallando con el nodeid si detecta mutacion
- [ ] motor_git_identity_guard expone la funcion de enforcement para tests de barrera
- [ ] 3 tests nuevos en tests/unit/test_motor_git_identity_barrier.py, paralelos a test_motor_bus_isolation_barrier.py, sin tocar el motor real (monkeypatch)
- [ ] MUTATION documentado literalmente en execution_log.md (sin-contaminacion no falla / con-contaminacion falla y restaura)
- [ ] Identidad git del motor sin cambio real tras la suite canonica completa
- [ ] Suite canonica run_pytest_safe.py --level all verde con tested_commit_sha == HEAD
- [ ] ruff check + ruff format --check en verde
- [ ] validate --json 0 errors / 0 warnings (Manager gate)
