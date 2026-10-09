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

## 2. Cuando el prompt de arranque de un Builder debe citar ESTE contrato

Cualquier prompt que vaya a lanzarse a un Builder real via Kilo/CLI-de-agente (no un bucle de ensemble)
debe citar `prompts/builder_invocation_contract.md` en su cabecera o en su seccion de "como lanzar",
igual que los prompts de gobierno citan `ensemble_loop.md`. Un prompt que solo describe QUE hacer, sin
decir COMO se invoca, deja a la sesion que lo recibe sin saber si debe usar `ensemble_dispatch.py` o el
CLI directo -- ese fue exactamente el fallo que origina este contrato.

## 3. Relacion con `AGENTS.md`

El vocabulario canonico de roles (`AGENTS.md`, seccion "Backends y roles") define que es un backend IA
y un rol; este contrato no lo redefine. `AGENTS.md` enlaza aqui para el PROCEDIMIENTO operativo de
invocacion de un Builder real, de la misma forma que enlaza a `ensemble_loop.md` para el procedimiento
de un bucle de ensemble.

El ADAPTADOR del motor al nucleo portable del proceso Manager-Builder (`prompts/manager_orchestrator_loop_adapter_motor.md`) traduce cada capacidad de ese nucleo a los comandos reales de este repositorio; la invocacion de un Builder real descrita en la seccion 1 cubre ahi la capacidad LECTOR_FS.
