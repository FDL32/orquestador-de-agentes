# Fricciones operativas del vuelo 4 capas WOT-2026-104j/104h/104k/104l (2026-10-18/19)

Nota de referencia (no normativa): `agent_execution_modes.md` permanece `frozen`
y no se toca aqui. Este documento registra fricciones REALES medidas durante un
vuelo 4 capas completo (Orquestador = sesion hija `104hj-4capas-20261018-57`,
coordinadora = `orquestador-de-agentes-de [aee00d]`), para que la SIGUIENTE
sesion que opere en modo 4 capas no las reencuentre a ciegas. Cada hallazgo
cita su evidencia en la bitacora de origen.

## F1 -- `pgrep -f "kilo"` da falso negativo de fin de proceso (Windows + wrapper node)

**Sintoma medido:** el sondeo inicial del Orquestador via `pgrep -f "kilo"`
reporto "proceso terminado" mientras Kilo seguia activo -- el log de la
invocacion siguio creciendo de 101KB a 256KB DESPUES de la primera senal de
"completado" (bitacora `104hj-4capas-20261018` destino, lineas 228-236).

**Causa:** en Windows, Kilo CLI corre via wrapper `kilo.cmd`/node; el proceso
que `pgrep` ve no es necesariamente el que sigue escribiendo el log.

**NO existe guia canonica para esto hoy:** `prompts/builder_invocation_contract.md`
no documenta ningun metodo de deteccion de liveness/fin-de-turno para
invocaciones `kilo run` (grep de "pgrep"/"liveness"/"sondeo" sobre ese prompt:
0 hits, verificado 2026-10-19). El Orquestador tuvo que inventar un criterio
ad-hoc en caliente, violando la norma "busca protocolo antes de suponer uno"
no por desobediencia sino porque el protocolo sencillamente no existe.

**Remedio usado en vivo (funciono):** estabilidad del TAMANO del fichero de
log de la invocacion (dos lecturas separadas sin crecimiento) en vez de
`pgrep`, o `tasklist`/PowerShell sobre el PID real.

**Follow-up:** WOT-2026-104m (fichado en `backlog.md`) -- anadir a
`builder_invocation_contract.md` el metodo canonico de deteccion de
liveness/fin-de-turno para invocaciones Kilo en Windows.

## F2 -- Suite completa (`--level all`) lanzada por el Builder como su propio gate de cierre, y colgada

**Sintoma medido:** Builder-nan corrio `run_pytest_safe.py --level all` como
Fase 6 de su propio despacho; el proceso quedo COLGADO (PID padre + PID hijo
pytest, 0% CPU durante 28s+, lock activo). El Orquestador tuvo que matarlo
(`Stop-Process -Force` sobre ambos PIDs) y relanzar con `--force-unlock`.

**Causa combinada con F3:** el despacho del Builder (plantilla pre-WOT-2026-104k)
asignaba la suite completa al Builder como su propio cierre -- exactamente el
patron que WOT-2026-104k elimino.

## F3 -- Secuenciacion suite-antes-de-Revisor (la causa de WOT-2026-104k)

Ya fichado y corregido de forma durable: ver WOT-2026-104k en
`backlog.md`/`AGENTS.md` (seccion "Asignacion de rol en despacho trio"). No se
repite aqui el detalle normativo (X-09: la norma vive una vez en `AGENTS.md`).

## F4 -- pipe a `tail` en la suite pierde la seccion FAILURES (CEM, variante no documentada)

**Sintoma medido (coordinadora, no la hija):** la sesion hija lanzo
`run_pytest_safe.py --level all 2>&1 | tail -10` en background para
diagnosticar un fallo real; perdio la seccion `FAILURES` y repitio la
corrida completa de 17 minutos TRES veces intentando diagnosticar un fallo
del que ya tenia datos completos.

**Hecho no obvio, verificado en el propio codigo (no requirio ninguna
corrida nueva):** `scripts/run_pytest_safe.py` (`RUNTIME_DIR`, linea 87;
`LAST_RUN_LOG`, linea 89) YA persiste el stdout COMPLETO sin truncar en
`.agent/runtime/pytest-safe/last-run.log` en CADA corrida, independientemente
de como se invoque. El pipe a `tail` no pierde informacion que el runner no
tuviera ya guardada en disco -- la pierde solo de la VISTA del agente que
hizo el pipe.

**Remedio:** ante un fallo real de `--level all`, leer
`.agent/runtime/pytest-safe/last-run.log` (o `.json` para los contadores)
directamente en vez de relanzar la suite para "ver mejor" la salida. Esto
generaliza la regla de AGENTS.md "el exit code tras una tuberia MIENTE" a un
caso donde ademas el STDOUT completo (no solo el exit code) esta disponible
sin re-ejecutar nada.

**Relacion con F1-F3:** las tres son variantes de la misma familia ("no
confiar en la senal visible del proceso, verificar el artefacto persistido")
que CEM ya nombra para el exit code; aqui se extiende a liveness (F1) y a
stdout (F4).

## F5 -- Builder-nan no escribe su recibo de cierre (B3) en el primer turno

**Sintoma medido:** en el Turno 2 (104j), el commit `5580867e` existe y es
correcto, pero `builder_recibo_r1.md` (artefacto B3 obligatorio del despacho)
nunca aparecio. En el turno de seguimiento (follow-up del fixture, 2026-10-19)
el Builder-nan SI lo escribio (`builder_recibo_followup_r1.md`) -- friccion
NO recurrente dentro del mismo vuelo una vez declarada.

**Sin accion de seguimiento:** un solo caso corregido en la segunda ocurrencia
no justifica un ticket de barrera nueva (confianza insuficiente, n=1 vs n=1);
se registra aqui como dato para la proxima sesion que quiera evaluar si se
repite en otros vuelos.

## F6 -- `check-contract-full-read` y `check-model-id-crystallization` bloquean commits

- **`check-contract-full-read` (normalizacion de formato, WOT-2026-104l,
  resuelto):** el cableado existe y siempre existio: `.claude/settings.json`
  dispara `native_post_tool_hook.py` para Read events. El gap real era la
  normalizacion de formato de ruta entre plataformas en el lector:
  sesiones Kilo/nan emiten ruta RELATIVA (`"scripts/x.py, 656 lines"`),
  mientras que Claude Code/T3 emiten ruta ABSOLUTA REDACTADA
  (`"Read file C:\Users\***REDACTED***\...\prompts\x.md, 126 lines"`). El
  lector (`check_contract_full_read.py`) solo resolvio absolutas y exactas,
  no relativas. Corregido con WOT-2026-104l: se aporto una 4ta rama de
  matching que resuelve relativas contra `motor_root`, mas `os.path.normcase`
  para normalizar separadores en Windows. El fix incluye evidencia de
  telemetria en el output FAIL (F2) y tests que reproducen el gap medido.
  Limitacion declarada: sin `--session-id`, el lector carga TODAS las sesiones;
  una sesion puede sellar PASS con telemetria de otra (falso-verde por
  contaminacion cruzada) -- no cerrado aqui.
- **`check-model-id-crystallization` (por diseno, no es un bug):** rechaza
  CUALQUIER trailer `Co-Authored-By` que nombre un modelo concreto con
  version (p.ej. "Claude Sonnet 5") + auto-firma `noreply@`, sin importar que
  sesion/modelo lo emita (`orchestrator_pipeline_codeonly.md:196`). Remedio:
  omitir el trailer, o firmar solo con el proveedor sin version
  (`Claude <noreply@anthropic.com>`). Afecta a CUALQUIER commit hecho por un
  agente Claude en este arbol (motor o destino), no solo a sesiones 4 capas.

## F7 -- `check-contract-full-read` trata una mencion en PROSA ("`.git`") como cita de ruta a auditar, y solo mira 2 lineas hacia atras

**Sintoma medido (hija, al commitear WOT-2026-104k via el workaround de F6):**
el gate marco el `.git` real del worktree como "no leido" porque el veredicto
del Revisor-nan citado en el bundle usa `` `.git` `` como texto descriptivo
dentro de una frase ("el `.git` no es legible"), no como una ruta que haya
que auditar lectura completa. Resuelto con 6 declaraciones de muestreo
inline (una por cada mencion); en el proceso se confirmo que el gate solo
examina las 2 LINEAS PREVIAS a una cita para decidir si es descriptiva o
una ruta a verificar, nunca las lineas posteriores -- una mencion en prosa
seguida de contexto aclaratorio (en vez de precedida) no se reconoce como
tal.

**Relacion con F6:** mismo mecanismo de workaround (muestreo declarado), pero
causa DISTINTA: F6 es un gap de instrumentacion (no hay telemetria que leer);
F7 es un falso positivo del propio HEURISTICO de deteccion de citas (hay
telemetria, pero el gate decide mal que ESTE token concreto necesita
evidencia de lectura).

**Sin ticket propio todavia:** un solo caso, dentro del mismo commit que ya
disparaba F6 por otra via -- no hay evidencia suficiente de que esto bloquee
commits fuera de esta combinacion rara (cita de `.git` en prosa dentro de un
veredicto citado). Se registra para que la proxima vez que aparezca no haya
que re-diagnosticar desde cero; si se repite, candidato a ampliar el DoD de
WOT-2026-104l (mismo script, `check_contract_full_read.py`) con el caso de
falso-positivo de prosa, no solo el gap de instrumentacion.

## Resumen de tickets fichados a partir de este vuelo

| Ticket | Que | Estado al cierre de este documento |
|---|---|---|
| WOT-2026-104j | `check_contract_full_read.py` union de rangos offset-aware | CERRADO, integrado |
| WOT-2026-104h | Verificacion B worktree enlazado (destino) | CERRADO, integrado |
| WOT-2026-104k | Suite completa solo-Manager en despacho trio | Validado por loop adversarial, commit pendiente (bloqueado por F6) |
| WOT-2026-104l | Gap de instrumentacion T3/Claude-Code para `check-contract-full-read` | pending |
| WOT-2026-104m | Metodo canonico de liveness de invocaciones Kilo en `builder_invocation_contract.md` | pending |
