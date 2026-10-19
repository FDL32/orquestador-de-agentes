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

## 1.5. Provider explicito obligatorio cuando el modelo existe en mas de un proveedor (WOT-2026-103d)

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

## 4. Relacion con `AGENTS.md`

El vocabulario canonico de roles (`AGENTS.md`, seccion "Backends y roles") define que es un backend IA
y un rol; este contrato no lo redefine. `AGENTS.md` enlaza aqui para el PROCEDIMIENTO operativo de
invocacion de un Builder real, de la misma forma que enlaza a `ensemble_loop.md` para el procedimiento
de un bucle de ensemble.

El ADAPTADOR del motor al nucleo portable del proceso Manager-Builder (`prompts/manager_orchestrator_loop_adapter_motor.md`) traduce cada capacidad de ese nucleo a los comandos reales de este repositorio; la invocacion de un Builder real descrita en la seccion 1 cubre ahi la capacidad LECTOR_FS.
