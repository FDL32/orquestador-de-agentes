# Contrato: como invocar un Builder real (no un bucle de ensemble)

contract_id: cid-builder-invocation-v1
source_of_truth: este prompt. Hermano de `prompts/ensemble_loop.md` (bucles S/F de gobierno/revision
via `ensemble_dispatch.py`); si divergen, cada uno prevalece en su propio alcance. Origen: WOT-2026-090
(sesion 2026-10-03: una sesion de Manager ofrecio `ensemble_dispatch.py run` como opcion para lanzar un
Builder real, confundiendo las dos superficies).

## 0. La distincion que este contrato existe para fijar

Hay DOS superficies distintas que comparten vocabulario ("backend", "lente", "modelo nan") y por eso se
confunden:

| | **Bucle de ensemble (S/F)** | **Builder real** |
|---|---|---|
| Para que | Revision adversarial de codigo/prompts/propuestas: proposer/challenger, scorecard, premise-check | Ejecutar una tarea de implementacion/lectura larga (leer backlog, escribir un informe, editar codigo) |
| Mecanismo | `scripts/ensemble_dispatch.py loop-round` (ver `prompts/ensemble_loop.md`) | Invocacion directa del CLI del agente (Kilo, Codex CLI, OpenCode) desde la shell, SIN pasar por `ensemble_dispatch.py` |
| Canal `api` | Llamada HTTP directa, SIN filesystem | N/A -- un Builder siempre necesita filesystem |
| Canal `agent` | CLI invocado COMO LENTE (recibe un bundle acotado, responde un veredicto corto) | El MISMO CLI invocado COMO AGENTE (recibe un prompt de tarea, trabaja sobre el repo con sus propias herramientas, puede tardar minutos) |
| Registro | `scorecard.jsonl`, nonce obligatorio en fases de gobierno | Sin bus de eventos (Kilo no emite `BUILDER_EXIT`); el Manager anota a mano en `execution_log.md` |
| Salida esperada | Un veredicto (`DECISION: APPROVE/CHANGES` + hallazgos) | Un entregable (fichero escrito, commit, diff) |

**Regla de decision:** si la tarea es "dame tu opinion/veredicto sobre X" -> bucle de ensemble. Si la
tarea es "haz X" (leer, escribir, implementar, investigar con filesystem) -> Builder real. Un mismo
proveedor (`nan`, `codex`) puede servir ambos roles en sesiones distintas, pero NUNCA con el mismo
mecanismo de invocacion.

**`ensemble_dispatch.py run`/`loop-round` NO es un mecanismo generico para "encargarle una tarea a un
backend".** Esta diseñado para UNA ronda de revision con bundle acotado y salida corta. Pasarle una
tarea de Builder (leer un fichero de 1.5MB, escribir un informe de varias secciones) no esta soportado
por su contrato y produce resultados truncados o rechazados por `check_loop_bundle_protocol.py`.

## 1. Como invocar un Builder real via Kilo CLI (canal nan-FS)

Mecanismo verificado end-to-end (WOT-2026-089n, 2026-10-02/03): anadir `prompt_via_stdin: true` +
`model_flag: ["-m", "{model}"]` al bloque `backends.kilo` de `.agent/config/agents.json` basta para que
cualquier modelo del proveedor `nan` (deepseek/glm/qwen/gemma/mimo) corra como agente con filesystem
real sobre el repo destino, via el CLI de Kilo.

**Instalacion del CLI (2026-10-09, reemplaza "localizar kilo.exe" como paso manual):** `npm install -g
@kilocode/cli` instala los binarios `kilo`/`kilocode` en PATH (shims `kilo`/`kilo.cmd`/`kilo.ps1` en
Windows -- NUNCA `kilo.exe`; ese nombre solo existe dentro de la extension de VSCode y ningun consumidor
de este repo implementa su descubrimiento). Con el CLI instalado, el comando de abajo se invoca
directamente como `kilo` (o `kilo.cmd` si el lanzador usa `subprocess.Popen(shell=False)`, que en
Windows NO aplica `PATHEXT` -- ver leccion portable `obs-windows-subprocess-shell-false-ignores-pathext`),
sin necesidad de resolver ninguna ruta a mano.

Comando canonico (orden exacto, `--` como separador OBLIGATORIO antes del mensaje -- sin el, el parser
de Kilo trata el mensaje como una ruta de fichero adicional y falla):

    kilo run \
      --auto \
      -m nan/<modelo> \
      --dir "<ruta-absoluta-al-repo-destino>" \
      --format json \
      --print-logs \
      -f "<ruta-absoluta-al-prompt-de-instrucciones>" \
      -- \
      "<mensaje corto que remite al fichero adjunto>" \
      > <ruta-log> 2>&1 &

Notas obligatorias:

- `--auto` es el flag de auto-aprobacion de permisos (`--dangerously-skip-permissions` en versiones
  previas de Kilo). Kilo headless NO tiene sandbox real: sigue siendo una llamada con filesystem
  completo, con la misma objecion de seguridad que `[[gate-permisos-no-es-sandbox-recolector-claude-basta]]`
  (memoria, 2026-07-18). No resolver esa objecion aqui; solo declarar que sigue vigente.
- `-f <ruta>` debe ir ANTES de `--`, nunca interpolar el prompt con `"$(cat file)"` en bash (si el prompt
  lleva backticks internos, la interpolacion lo corrompe silenciosamente: Kilo sale con exit 0 y solo el
  header ANSI, sin haber trabajado).
- Pide SIEMPRE al Builder que ESCRIBA su resultado a un fichero real (`.agent/planning/<nombre>.md`), no
  que responda por texto/log largo: medido repetidamente que responder por texto deja al Builder "mudo"
  (log cortado tras iniciar el stream, sin error visible) en 4 de cada 5 intentos; escribir a fichero fue
  consistente.
- **Kilo NO autocarga `AGENTS.md` ni ningun puntero de capa 2 (WOT-2026-108b, verificado
  `doc_optimization.md` PASO 1 punto 4).** Todo prompt pasado con `-f <prompt>.md` DEBE instruir
  EXPRESAMENTE al Builder a leer `AGENTS.md` -- y, si la tarea toca memoria del proyecto, tambien sus
  punteros de capa 2 (`MEMORY.md`, `memory_rules.md`/L2, `memory_profile.md`/L3) -- ANTES de actuar. Sin
  esa frase explicita, el Builder-nan trabaja a ciegas de las convenciones del repo con independencia de
  cuanto se reduzca `AGENTS.md`: no es un problema de tamano, es de ausencia total de carga automatica.
Antes de lanzar `kilo run -f <prompt>`, verifica el prompt con
   `python scripts/check_builder_dispatch_prompt.py --require-memory-bootstrap <prompt>` (Seccion 1.6);
   si bloquea, anade la instruccion antes de dispachar.
Antes de lanzar el CLI directo (`kilo run -f <prompt>`), verifica el contenido del prompt
    con el guard (Seccion 1.8). `codex exec` lee el prompt por STDIN (nunca con una flag
    `-f`), con el contenido entregado a `codex exec -` via pipe o redireccion; el mismo
    guard aplica antes de lanzar `codex exec`.
    `python scripts/check_builder_cli_privacy_preflight.py <prompt> --data-sensitivity <public|private>`
    (Seccion 1.8); si bloquea, reduce el contenido sensible o declara
    `--trusted-reason "<motivo>"`. Ni Kilo ni Codex tienen hook `SessionStart`: el
  prompt de un Builder/Revisor real DEBE llevar un paso 0 con
  `python scripts/memory_context.py --bootstrap` (el flag lo exige); una lente corta de ensemble no.
  Prueba de arranque en frio (2026-10-19, 3 backends, mismo fixture): Claude y `nan/qwen3.8-flash`
  siguieron el puntero de capa 2 cuando el prompt lo pedia explicitamente; `nan/gemma4` NO lo siguio (n=2
  con `obs-fs-reading-receipt-does-not-certify-correct-reasoning`, 2026-10-08) -- la prosa de esta norma no
  garantiza que un backend debil la obedezca, solo que la instruccion exista; ver limite declarado abajo.
- Sin bus de eventos: Kilo no emite `BUILDER_EXIT` ni ningun otro evento al bus del orquestador. El
  Manager (el backend que lanzo la tarea) anota a mano inicio/fin en `execution_log.md` si el ticket lo
  requiere. No esperes ver la ronda en `scorecard.jsonl` ni en `leaders`/`status` de `ensemble_dispatch.py`
  -- esos comandos son del OTRO contrato (ver `prompts/ensemble_loop.md`).

### 1.A. Deteccion canonica de liveness / fin-de-turno de una invocacion Kilo en Windows (WOT-2026-104m)

**Por que hace falta esto (causa medida, no teoria):** en Windows el CLI de Kilo corre via wrapper
`kilo.cmd` -> `node.exe`; el proceso que un sondeo por nombre ve NO es necesariamente el que sigue
escribiendo el log. En el vuelo 4 capas WOT-2026-104j/104h (2026-10-18) el Orquestador uso
`pgrep -f "kilo"` como senal de fin de proceso y obtuvo un FALSO NEGATIVO: reporto "proceso terminado"
mientras Kilo seguia activo -- el log de la invocacion siguio creciendo de 101KB a 256KB DESPUES de la
primera senal de "completado" (bitacora `104hj-4capas-20261018`, lineas 228-236; evidencia extendida en
`docs/protocol/4capas_vuelo_104hj_fricciones_operativas.md`, F1).

**PROHIBIDO usar `pgrep -f` como unico criterio de terminacion.** No es el metodo canonico aqui por dos
motivos independientes, ambos medidos en esta maquina:
1. El falso negativo de arriba: un resultado vacio NO prueba que el proceso haya terminado.
2. Ni siquiera existe de forma fiable: `where.exe pgrep` da rc=1 en PowerShell y Git Bash responde
   `pgrep: command not found`. Donde SI existe (Cygwin/busybox), su `-f` casa la cadena de comando del
   wrapper, no el proceso que escribe el log -- que es exactamente el modo de fallo medido.
Un probe que puede devolver vacio porque el binario no esta, o porque el nombre no casa, es
indistinguible de "terminado": fail-open por construccion.

**Metodo canonico A (preferido): estabilidad del tamano del fichero de log entre dos lecturas.** Es el
remedio que funciono en vivo durante aquel vuelo y nunca se formalizo. Requiere capturar el PID del
lanzamiento y leer el log al menos DOS veces separadas; solo se declara fin-de-turno cuando el tamano no
crece entre lecturas.

```powershell
$LOG = "<ruta-del-log-de-la-invocacion>"   # el mismo destino de '> <ruta-log>' de la Seccion 1
$prev = (Get-Item $LOG).Length
Start-Sleep -Seconds 2
$cur = (Get-Item $LOG).Length
if ($cur -ne $prev) {
  "ACTIVO: crecimiento de $($cur - $prev) bytes entre lecturas"
} else {
  "ESTABLE en $cur bytes tras 2 lecturas -- candidato a fin de turno"
}
```

Reglas obligatorias del metodo A:
- Dos lecturas estables son **necesarias, no suficientes**: una pausa larga del modelo entre tokens tambien
  congela el tamano. Exige N consecuciones estables (N >= 2) ANTES de declarar terminacion, y confirma con
  el metodo B sobre el PID real.
- Un log que deja de crecer pero cuyo PID sigue vivo = turno pausado o proceso colgado, NO completado.
- Compara tamano (`(Get-Item $LOG).Length`), no `LastWriteTime`: el mtime no distingue "escribio poco" de
  "no escribio".

**Metodo canonico B (confirmatorio): sondeo por PID real, nunca por nombre.** Captura el PID en el
lanzamiento y preguntale a Windows por ESE entero.

```powershell
# Forma canonica: Get-Process sobre el PID capturado al lanzar (Start-Process -PassThru).
$PID_KILO = <pid-capturado-con--PassThru>
$vivo = [bool](Get-Process -Id $PID_KILO -ErrorAction SilentlyContinue)
if ($vivo) { "VIVO: PID $PID_KILO" } else { "MUERTO: PID $PID_KILO" }
```

```powershell
# Alternativa tasklist (equivalente, util desde shells sin cmdlets .NET).
$raw = & tasklist /FI "PID eq $PID_KILO" /FO CSV /NH 2>$null | Out-String
$vivo = [bool]($raw.Trim() -and $raw -notmatch 'no hay|INFO:|ERROR:')
if ($vivo) { "VIVO: PID $PID_KILO" } else { "MUERTO: PID $PID_KILO" }
```

Trampas declaradas del metodo B (medidas 2026-10-19, PowerShell 5.1 en Windows):
- **`Out-String` es obligatorio** en la variante `tasklist`: sin pipe, `/FI` devuelve un `Object[]` de dos
  lineas cuando el PID no existe, y `-notmatch` sobre un array evalua CADA elemento por separado y deja
  pasar el caso "no encontrado" como si estuviera vivo (fail-open). Con `Out-String` el patron casa contra
  el texto completo y el veredicto es correcto.
- El filtro de `no hay` es **dependiente del locale**: en un Windows en ingles la frase es
  `INFO: No tasks are running which match the specified criteria`. Anade `No tasks` al patron si el host no
  esta en espanol; nunca dependas solo de la forma acentuada (`INFORMACION`).
- **No sondees por nombre** (`Get-Process -Name node`): medido en esta maquina hay 14-17 procesos `node.exe`
  vivos permanentemente, asi que ese sondeo siempre responde "vivo" -- otro fail-open.
- El PID del wrapper `kilo.cmd` puede haber desaparecido mientras el hijo `node.exe` sigue escribiendo.
  Sondea el PID del proceso que hereda el stdout (el que recibe `> <ruta-log>`), o usa el metodo A como
  autoridad primaria.

**Verificacion de los dos metodos en esta maquina (controles positivos, no aserciones cosmeticas):**
estabilidad de tamano detecto crecimiento y luego estabilizacion (`s1=4 s2=9 s3=9`); `Get-Process -Id` dio
`True` con el proceso vivo y `False` tras matarlo; el helper de `tasklist` con `Out-String` dio
`inexistente=False / vivo=True / muerto=False`. Reproducir estos controles es parte del DoD del proximo
ticket que toque esta seccion: cambiar un snipped sin re-ejecutarlo deja la guia otra vez como relato.

**Relacion con el bullet de arriba ("Sin bus de eventos"):** ese bullet sigue vigente -- Kilo no emite
`BUILDER_EXIT`. Esta seccion no lo contradice: aporta el UNICO sustituto mecanico disponible para saber
cuando la invocacion termino, dado que no hay evento.

## 1.4. Nota doble-backgrounding: NUNCA combines `&` con el backgrounding gestionado por la herramienta (WOT-2026-108c)

**Incidente que origina esta norma (2026-10-18, reportado por opencode/glm en vuelo 4 capas):**
un Builder lanzo `kilo run ... & ; echo PID` (doble backgrounding: `&` interno + `background_process`
de Kilo) y luego hizo cleanup del PID heredado, matando al hijo que Kilo seguia esperando. El fix
(funcional) fue eliminar el `&` interno y dejar solo el `background_process` del lanzador; el
huerfano desaparecio. Pero el contrato que originaba la sesion NUNCA recibo la instruccion de
cerrar su propio dispatch -- el Builder no tiene rol de Manager/coordinador, asi que el cierre
quedo en la sombra.

**Regla dura:** nunca combines `&` interno (subshell, backgrounding manual) con el backgrounding
ya gestionado por la herramienta invocadora (`background_process`, `Task background=true`).
Invoca `kilo run` como comando UNICO directo de la herramienta, sin subshell.

Comando VERIFICADO (n=1, el fix funciono en vivo):

    kilo run \
      --auto \
      -m nan/<modelo> \
      --dir "<ruta-absoluta>" \
      --format json \
      --print-logs \
      -f "<ruta-absoluta-al-prompt>" \
      -- \
      "<mensaje corto>" \
      > <ruta-log> 2>&1

Comando INFERIDO (sintaxis invalida en POSIX tal como lo reporto opencode/glm):
`kilo run ... & ; echo PID` -- tiene `&` ANTES del `>` de redirect, lo que rompe la tuberia
en bash (el `&` backgrounds el comando pero el `>` se resuelve en el shell padre sin redirigir
el stdout del hijo). Nit de fidelidad, no el fix real.

**Cross-ref CEM "un `exit 0` puede significar 'no hice nada'":** el postflight obligatorio del
Builder es el ARTEFACTO esperado (recibo del despacho), no el exit code del wrapper. Un
`background_process` con `start` que no suspende el goal = la sesion puede cerrar sin verificar
que el hijo termino. El artefacto (log crecio + estable + PID muerto) certifica completado, no
el `exit 0`.

**GUARD MECANICO (future work, fuera de este FLT):** rechazar `&` bajo background gestionado
+ postflight automatizado del artefacto -> `docs/followups/kilo-double-backgrounding-postflight-guard-followup.md`.

**Relacion con el bullet de arriba ("Sin bus de eventos"):** ese bullet sigue vigente -- Kilo no emite
`BUILDER_EXIT`. Esta seccion no lo contradice: aporta el UNICO sustituto mecanico disponible para saber
cuando la invocacion termino, dado que no hay evento.

## 1.6. Provider explicito obligatorio cuando el modelo existe en mas de un proveedor (WOT-2026-103d)

**Incidente que origina esta norma (VUELO6, REV-100K-r1, 2026-10-15):** un despacho de
subagente con `model=mimo-v2.6-flash` SIN `provider` explicito resolvio una puerta DISTINTA
de la esperada y fallo con "account balance is insufficient"; el diagnostico inicial
("NaN agotado") fue FALSO -- una sonda con `provider=nan` explicito funciono de inmediato.
Costo: una ronda perdida, un fallback gratuito activado sin necesidad, y riesgo de cambiar
de persona de revision por una causa que no existia.

**NORMA (vive AQUI, no se re-declara en otro prompt -- regla X-09):** toda invocacion de un
subagente (Builder/Revisor/Manager, via el Task tool nativo de Claude Code o via el CLI de
Kilo de la Seccion 1) para un modelo disponible en MAS de un proveedor DEBE declarar el
proveedor explicitamente. Prohibido delegar la resolucion de la puerta de transporte en un
vuelo multi-persona -- la ambiguedad la paga quien despacha, no quien recibe. Ante un fallo
de transporte, la sonda minima para discriminar causa es UN intercambio de 1 token CON
proveedor explicito, ANTES de concluir que el modelo/proveedor esta agotado y cambiar de
plan.

**Limite declarado (no se oculta): la "barrera cableable" que el ticket original pedia NO
es construible en este repositorio.** El Task tool nativo de Claude Code es una herramienta
del HARNESS, no un script que este motor posea o pueda envolver -- no hay un punto de codigo
de `orquestador_de_agentes` por el que pase esa invocacion y que un guard de este repo pueda
interceptar. La unica superficie que SI es codigo de este motor es el CLI de Kilo de la
Seccion 1, donde el modelo YA se declara con el prefijo del proveedor en la propia cadena
(`-m nan/<modelo>`) -- ahi la ambiguedad del incidente no puede reproducirse por diseno de
ese comando. Por eso esta Seccion 1.5 es, deliberadamente, una NORMA documental y no un
guard ejecutable: cablearla de verdad exigiria control sobre el propio harness, fuera del
alcance de este repo. Decision de diseno tomada por Claude Code (fork) con autorizacion
explicita del usuario (WOT-2026-103d, 2026-10-18); la leccion operativa del incidente ya
esta en memoria L1 del workspace (`obs-3149cf70225b`, dominio builder-contract).

## 1.7. Preflight mecanico: el prompt declara la lectura de AGENTS.md (WOT-2026-108b)

**Por que un guard y no solo la prosa de la Seccion 1:** la misma leccion que motiva
`check_loop_bundle_protocol.py` aplica aqui -- una norma que depende de que quien redacta el prompt se
acuerde de escribir la frase es, por definicion de este repo, una NORMA, no una barrera (`AGENTS.md`,
"Barrera cableada"). `scripts/check_builder_dispatch_prompt.py` lee el fichero de prompt ANTES de lanzar
`kilo run -f <prompt>` y bloquea (`exit 1`) si falta la instruccion explicita de leer `AGENTS.md`. Si el
prompt menciona memoria del proyecto (memoria, `MEMORY.md`, L2, L3, `memory_rules`, `memory_profile`) sin
instruir tambien su lectura, el guard avisa (`WARN`, no bloquea -- la clausula de capa 2 es condicional a
que la tarea toque memoria, no universal).

    python scripts/check_builder_dispatch_prompt.py --require-memory-bootstrap <ruta-al-prompt.md>

Con `--require-memory-bootstrap` (obligatorio para Builder/Revisor reales, no para lentes cortas) bloquea
tambien si el prompt no ordena `python scripts/memory_context.py --bootstrap`: nombrar la memoria no la
carga, y Kilo no tiene hook `SessionStart` (diseno v6, 2026-10-23).

**Limite declarado (mismo patron que la Seccion 1.5, no se oculta):** este guard es, como
`check_loop_bundle_protocol.py`, una barrera de FORMA -- verifica que la instruccion de lectura este
DECLARADA en el texto del prompt, no que el Builder la obedezca de verdad (ver la prueba de arranque en
frio citada en la Seccion 1: `nan/gemma4` ignoro un puntero de capa 2 presente en su propio prompt). Y es
una barrera **invocada por convencion, no cableada automaticamente**: no existe en este repo un punto de
codigo que intercepte `kilo run` antes de ejecutarse (el mismo motivo declarado en la Seccion 1.5 para el
Task tool nativo), porque el despacho de un Builder real es una invocacion manual de shell, no una
llamada a traves de un script de este motor. Quien despacha es quien debe invocar el guard antes de
lanzar; sin eso, el guard no se ejecuta solo.

## 1.8. Preflight mecanico: privacidad del contenido del prompt (WOT-2026-046k)

**Por que un guard y no solo la prosa de la Seccion 1:** la misma leccion que motiva
`check_builder_dispatch_prompt.py` aplica aqui -- una norma que depende de que quien redacta
el prompt se acuerde de escribir la frase es, por definicion de este repo, una NORMA, no
una barrera. `scripts/check_builder_cli_privacy_preflight.py` lee el fichero de prompt ANTES
de lanzar cualquier CLI directo de Builder/Revisor y bloquea (`exit 1`) si detecta contenido
sensible (credenciales, tokens opacos de alta entropia, rutas a raices privadas) y la exencion
no esta declarada POR RUTA/invocacion (via `--trusted-reason`). Reutiliza la MISMA
`privacy_preflight` ya auditada de `ensemble_dispatch.py` (WOT-2026-046c).

     python scripts/check_builder_cli_privacy_preflight.py <prompt> --data-sensitivity <public|private> [--trusted-reason "<motivo>"]

Esta obligacion aplica a TODO CLI directo prescrito por este contrato:
`kilo run` (Seccion 1) y `codex exec` son las dos vias de invocacion de
Builder/Revisor directo que este contrato contempla. Si un CLI directo
prescrito se ejecuta sin pasar por este guard, el prompt con contenido
sensible se enviaria al backend sin la barrera `privacy_preflight` que
`ensemble_dispatch.py` aplica de forma automatica.

**Nota sobre `scripts/run_codex_audit.py`:** este wrapper YA aplica
`privacy_preflight` internamente desde WOT-2026-046c, por lo que no
necesita el guard de esta Seccion 1.8 (el guard es para cuando `codex
exec`/`kilo run` se invocan MANUALMENTE desde shell, sin pasar por ese
wrapper).

Con `--trusted-reason "<motivo>"` declarado (motivo no vacio), se trata como
`backend_cfg={"trusted": True}` y el guard pasa siempre (el motivo se imprime, nunca
exencion silenciosa). Sin `--data-sensitivity` (ausente), se trata como `private`
(fail-closed).

**Limite declarado (mismo patron compartido que la Seccion 1.7 y 1.5, no se oculta):**
este guard es una barrera de FORMA sobre el FICHERO de prompt: verifica que el contenido
no dispare `privacy_preflight`, no sobre todo lo que el Builder vea en el repo durante su
sesion real. Y es una barrera **invocada por convencion, no cableada automaticamente**: el
mismo motivo estructural que `check_builder_dispatch_prompt.py` (Seccion 1.7) y la Seccion
1.5 -- el despacho de un Builder real es una invocacion manual de shell, no una llamada a
traves de un script de este motor que un hook pueda interceptar. Quien despacha es quien
debe invocar el guard antes de lanzar cualquier CLI directo prescrito (Kilo o Codex); sin
eso, el guard no se ejecuta solo.

**Patron compartido (X-09):** invocacion manual antes de `kilo run` o `codex exec`, sin
hook automatico, mismo limite estructural (despacho de shell no interceptable). Detalle
del guard en `scripts/check_builder_cli_privacy_preflight.py`, politica en
`scripts/guard_wiring_policy.yaml`.

## 2. Cuando el prompt de arranque de un Builder debe citar ESTE contrato

Cualquier prompt que vaya a lanzarse a un Builder real via Kilo/CLI-de-agente (no un bucle de ensemble)
debe citar `prompts/builder_invocation_contract.md` en su cabecera o en su seccion de "como lanzar",
igual que los prompts de gobierno citan `ensemble_loop.md`. Un prompt que solo describe QUE hacer, sin
decir COMO se invoca, deja a la sesion que lo recibe sin saber si debe usar `ensemble_dispatch.py` o el
CLI directo -- ese fue exactamente el fallo que origina este contrato.

## 3. Guard bloqueante durante la ejecucion => DETENTE, nunca lo parchees ni borres su evidencia

**Incidente que origina esta norma (WOT-2026-104n, 2026-10-19):** un Builder despachado via
`delegate_task`/`opencode` con un mandato ACOTADO (rediseñar fixtures de test, sin que el mandato
pidiera cerrar el ticket) se topo, por iniciativa propia, con dos guards reales y correctos
(`implementation_evidence_failed`, luego `pre_handoff_guard_failed`) al intentar ejecutar
`--mark-ready` sin que el mandato lo pidiera. En vez de PARAR y reportar el bloqueo, **monkeypatcheo
`runtime.project_root.is_motor_code_only`** para desactivar en caliente el guard anti-drift que
`AGENTS.md` documenta explicitamente ("Nunca usar `repo_motor/.agent/collaboration/` como
operativo"), y **borro `.agent/runtime/events/events.jsonl`**, que contenia sus propios eventos
`HANDOFF_BLOCKED`/`BUILDER_EXIT` de los intentos fallidos. El guard de pre-handoff SI funciono como
barrera (nunca hubo un `--mark-ready` exitoso), pero el patron -- un subagente que responde a un
bloqueo intentando desactivarlo en vez de detenerse -- es un riesgo de gobierno serio para
cualquier despacho via `delegate_task`/CLI de agente.

**Prohibiciones duras (aplican a CUALQUIER Builder/subagente invocado bajo este contrato):**

- **Nunca parchear, monkeypatchear ni modificar el mecanismo de un guard** (ni codigo de
  produccion del motor con ese fin) al toparse con un `HANDOFF_BLOCKED` o cualquier guard que
  bloquee. Ante un bloqueo: DETENTE y reporta el bloqueo tal cual al orquestador/Manager que
  despacho la tarea -- el guard es la barrera, no un obstaculo a rodear.
- **Nunca borrar, truncar ni reescribir `.agent/runtime/events/events.jsonl`** (ni ningun log del
  bus) desde un rol Builder/subagente, salvo instruccion EXPLICITA del orquestador. El log de los
  propios bloqueos es evidencia, no basura -- borrarlo es indistinguible de ocultar el rastro del
  propio fallo, independientemente de la intencion declarada.
- **Un mandato ACOTADO acota el alcance, no solo la tarea.** Un Builder dispatchado para una
  ronda concreta (p.ej. "rediseña fixtures y entrega informe") NO debe, por iniciativa propia,
  intentar ejecutar el ciclo de cierre completo del ticket (`--mark-ready`, commit de
  `execution_log.md` canonico, etc.) salvo que el mandato lo pida explicitamente. El conocimiento
  general del Builder sobre el protocolo completo del motor no autoriza a ampliar el alcance
  despachado.

**Limite declarado (no se oculta):** estas son prohibiciones de CONTRATO/instruccion, no un
sandboxing tecnico -- ningun mecanismo de este repo impide FISICAMENTE que un subagente con exec
de shell parchee codigo Python en su propio proceso. `prompts/kilo_trio_dispatch/
dispatch_builder.template.md` (B2/B9) apunta aqui por REFERENCIA, sin redeclarar estas
prohibiciones (X-09).

## 3.5. Informe de cierre parcial del hijo delegado (WOT-2026-104q)

**Problema que cierra:** ningun contrato exigia que un Builder/fork/hijo delegado entregara, al
terminar, un informe estructurado; el Manager recibia prosa libre y reconstruia la verificacion a
mano. Esta seccion fija el FORMATO de ese informe. NO define criterios nuevos: cada campo RELLENA un
punto YA ESCRITO del checklist de `prompts/orchestrator_session_close_full_audit.md`
(`contract_id: cid-session-close-full-audit-v0`), Bloque 2, o de `AGENTS.md`. Si un campo y su
fuente divergen, prevalece la fuente (X-09: el informe rellena el checklist, no lo redeclara).

**Obligacion:** todo Builder/subagente/hijo delegado invocado bajo este contrato, al terminar su
mandato (con exito, parcial o bloqueado), escribe un INFORME DE CIERRE PARCIAL con los cinco campos
de abajo, en este orden y con estos ids estables. Ningun campo se omite ni se deja vacio: cuando no
aplica, lleva su valor literal permitido.

| Id | Campo | Contenido exigido | Satisface (fuente) | Valor literal si no aplica |
|---|---|---|---|---|
| `CP-1` | Commits/diff | SHA(s) de commit + salida REAL de `git log` y `git diff --stat` (cwd = el checkout del hijo) | Bloque 2 punto 4, bullet "Encuadre" | `SIN COMMIT (cambios en working tree)` + salida real de `git diff --stat` + `git status --short` (caso del hijo SIN autorizacion de commitear) |
| `CP-2` | Mutation-verify | Por cada guard/test NUEVO que afirme bloquear un fallo: node-id + rc ROJO con la mutacion + rc VERDE tras revertir; reversion por COPY-RESTORE (nunca `git checkout --`/`git restore`); salida de `git status` limpia de restos (`*.premut`) tras revertir | Bloque 2 punto 4, bullets "Barrera mutation-verified" y "COPY-RESTORE" | `N/A: sin guard/test nuevo` |
| `CP-3` | Gates focales + hijo terminado | (a) Comando EXACTO de cada gate + su `exit_code` REAL (nunca el rc de una tuberia: usa `python scripts/tools/run_and_exit.py --tail N -- <cmd>`). Trampa conocida: `python scripts/check_encoding_guard.py` SIN argumentos y sin nada staged da un verde vacuo; pasa SIEMPRE las rutas explicitas tocadas. (b) Hijo delegado cuyo Manager/coordinador separado corre la suite de cierre (protocolo trio, `AGENTS.md` WOT-2026-104k): PROHIBIDO `--level all`. Fuera de ese caso rige el "Alcance declarado" de esa misma regla; si el hijo SI era el verificador legitimo de `--level all`, lo declara citando ese alcance. (c) SIEMPRE, como ultima linea del campo, la declaracion literal `HIJO TERMINADO: sin procesos propios en background ni mutaciones sin restaurar`, seguida de la salida REAL de `git status --short` tomada despues de esa ultima accion, que solo puede listar los ficheros del entregable declarados en `CP-1` y el propio informe: cualquier otra entrada (restos `*.premut`, temporales, cambios no declarados) es resto de mutacion y deja el campo invalido (5.ter pide `git status` "limpio" en el sentido de Bloque 2 punto 4, "LIMPIO de restos de mutacion", no arbol vacio: un hijo sin commit tiene su entregable en el working tree) | Bloque 2 punto 5.ter (precondicion: brazo TERMINADO, mutaciones revertidas, `git status` limpio) + `AGENTS.md` "Asignacion de rol en despacho trio (WOT-2026-104k)" | `N/A: sin gate aplicable` + motivo para (a) (raro: hasta un ticket documental corre encoding/nomenclatura); (c) NO admite N/A: sin la linea `HIJO TERMINADO` y su `git status --short` el campo cuenta como vacio |
| `CP-4` | Push | Declaracion explicita `NO PUSH`, o, si hubo push, la cita literal de la autorizacion que lo amparaba | `AGENTS.md` "Push por vuelo: UN solo push al final de TODOS los tickets" | (sin N/A: siempre `NO PUSH` o la autorizacion) |
| `CP-5` | Bloqueos | Cada guard bloqueante encontrado: nombre, comando, salida/rc, y que hizo el hijo (por la Seccion 3: DETENERSE y reportarlo aqui, nunca parchearlo) | Seccion 3 de este contrato | `NINGUNO` |

La declaracion `HIJO TERMINADO` vive en `CP-3` y no en `CP-2` porque `CP-2` admite N/A (hijo sin
guard/test nuevo), mientras la precondicion de 5.ter se exige a TODO hijo, y `CP-3` es el campo que
ya responde ante 5.ter. Acredita solo el lado del hijo: que el Manager corra la suite de cierre en
exclusiva sigue siendo acto del Manager, y ningun campo de este informe lo acredita.

Seccion final opcional `HUECOS_DETECTADOS`: ambiguedades o contradicciones del mandato o de los
contratos, con cita `fichero:linea`, en vez de improvisar en silencio.

**Markup del informe (WOT-2026-104s):** cada campo se escribe como encabezado markdown de nivel 2
`## CP-n` (p.ej. `## CP-1`), en este orden, seguido de su contenido hasta el siguiente encabezado
`## CP-n` o el fin del fichero. Es el formato que consume el guard de abajo; un hijo que use otra
marca (negrita, numeracion, tabla) no es parseable mecanicamente y su informe cuenta como mal
formado por la misma razon que uno con un `CP-n` faltante.

**Ruta fija y citable:** el informe se escribe a `<worktree-del-hijo>/CIERRE_PARCIAL_<TICKET>.md`
(p.ej. `CIERRE_PARCIAL_WOT-2026-104q.md` en la raiz del worktree), no solo en la respuesta del chat
(mismo motivo que la Seccion 1: escribir a fichero es consistente, responder por texto no). El
fichero NO se commitea: es evidencia EFIMERA del handoff hijo->Manager.

**Tension declarada con la raiz limpia y con session-close:** el fichero choca con "Mantiene la raiz
limpia" de `AGENTS.md` y con el requisito de motor sin cambios sin commitear del cierre de sesion
(`prepush_check` / `check_git_tree_clean`). Resolucion: el Manager, tras leerlo y volcar lo que haga
falta a su propia evidencia (`execution_log.md` o informe de vuelo), lo BORRA antes de su propio
commit y antes de cualquier `--session-close`; `git status --short` no debe listarlo al cerrar.
LIMITE conocido: no hay entrada en `.gitignore` ni guard que lo impida colarse en un `git add -A`;
la proteccion es de orden (norma), no mecanica.

**Criterio de rechazo:** un hijo que NO produce el informe en este formato -- fichero ausente, algun
`CP-n` faltante o vacio, un campo sin contenido exigido ni valor literal permitido, o un `CP-3` sin
la linea `HIJO TERMINADO` seguida de la salida real de `git status --short` -- deja su
trabajo en `cierre NO VERIFICABLE`. Nunca se acepta en silencio: el Manager no certifica ese trabajo
hasta rehacer la verificacion a mano y declararlo asi en su propia evidencia.

**El informe es evidencia DECLARADA, no verificada:** es un auto-reporte del hijo (criterio:
`prompts/_shared/evidence_contract.md`). El Manager/auditor sigue re-ejecutando lo que el informe cita (SHA, diff,
rc); el informe reduce el coste de esa verificacion, no la sustituye.

**Limite declarado (barrera) -- RESUELTO PARCIALMENTE (WOT-2026-104s):** `scripts/
check_child_closeout_report.py` verifica mecanicamente el FORMATO del fichero (las 5 secciones
`## CP-n`, no vacias, y la linea `HIJO TERMINADO` seguida de contenido no vacio en `CP-3`), y su invocacion
esta cableada en `prompts/orchestrator_session_close_full_audit.md` Bloque 2 punto 4.bis (se
dispara ahi, no por un hook automatico). Sigue siendo una barrera de FORMATO, no de CONTENIDO: no
verifica que los SHA/diff/rc citados sean reales -- eso sigue siendo acto del Manager/auditor
(parrafo anterior, "evidencia DECLARADA, no verificada"). Test de sincronia contrato<->guard:
`tests/unit/test_check_child_closeout_report.py::TestSyncWithContract`.

## 4. Relacion con `AGENTS.md`

El vocabulario canonico de roles (`AGENTS.md`, seccion "Backends y roles") define que es un backend IA
y un rol; este contrato no lo redefine. `AGENTS.md` enlaza aqui para el PROCEDIMIENTO operativo de
invocacion de un Builder real, de la misma forma que enlaza a `ensemble_loop.md` para el procedimiento
de un bucle de ensemble.

El ADAPTADOR del motor al nucleo portable del proceso Manager-Builder (`prompts/manager_orchestrator_loop_adapter_motor.md`) traduce cada capacidad de ese nucleo a los comandos reales de este repositorio; la invocacion de un Builder real descrita en la seccion 1 cubre ahi la capacidad LECTOR_FS.
