# Avisos de parada del vuelo y barrera cableada del latido (WOT-2026-153h)

Referencia bajo demanda: consultala al editar un latido, al tocar `scripts/flight/` (comms_alert,
flight_stall_check, quota_tick, notify_user.ps1) o cuando el cierre falla en el paso
`latido_alert_wiring`. Todo en ASCII.

## 1. Que es

El vuelo avisa al usuario de una parada (cupo, cola bloqueante, git bloqueado o sucio, disco, hook)
con un aviso de escritorio, sin ventana negra, una vez por causa y ventana. El mecanismo vive en el
motor, en `scripts/flight/`:

- `comms_alert.py`: estado, ledger, `--scan`, `--event`, `--ack`, `--resolve`. Directorio de
  operacion por `--ops-dir` o `FLIGHT_OPS_DIR` (datos: de el nunca se carga codigo).
- `notify_user.ps1`: el toast. `-SimulateToastFailure` es solo para pruebas: un latido que lo pasara
  dejaria al usuario SIN aviso, y el check lo prohibe.
- `flight_stall_check.py`: los detectores (y `--self-check`).
- `quota_tick.py`: la medida del cupo (rc 0, 3, 4, 5, 9).
- `check_latido_alert_wiring.py`: la barrera cableada de este documento.

Las copias antiguas de `tmp_or8` NO son el mecanismo: un latido que las llame esta desviado.

## Regla de Tags del aviso

`tag_for_toast` aplica `redact` a la clave cruda siempre. Su salida no es idempotente:
publicacion y retirada deben derivar el Tag desde la misma clave cruda, y nunca se debe
volver a pasar `tag_for_toast` sobre un Tag ya derivado. Esto mantiene alineados el Tag
que publica `notify` y el que usa `remove_toast`.

## 2. La barrera: `scripts/flight/check_latido_alert_wiring.py`

Lee el FICHERO del latido de cada rol (`coordinadora`, `supervisora`) y comprueba que sus ordenes
(solo las que estan en codigo en linea o en un bloque de codigo; la prosa no cuenta) invocan el
mecanismo del motor:

- el primer token es una RUTA ABSOLUTA del interprete fijado (Python: `--python-exe`, `FLIGHT_PYTHON` o
  `<motor>/.venv`; PowerShell: `%SystemRoot%/System32/WindowsPowerShell/v1.0/powershell.exe`);
- el script NO se busca por coincidencia en toda la linea: para Python es el primer operando tras una
  tabla cerrada de opciones (`-I -B -E -s -S -u -O -OO -q -v -b -d` sin valor, `-W`/`-X` con uno;
  `-c`/`-m` y cualquier otra opcion se rechazan); para PowerShell es el operando inmediato de `-File`
  o el primer posicional. Un valor de opcion (`-W`, `-X`, `-Title`, `-Message`, `--ops-dir`, `--what`)
  nunca puede hacerse pasar por script, incluso si repite su basename;
- el script es absoluto, no UNC, sin `tmp_or8`, resuelve (strict, enlaces incluidos) dentro de
  `<motor>/scripts/flight/`, esta TRACKED, es igual a HEAD y no tiene cambios preparados;
- toda ruta absoluta que no sea uno de los scripts del inventario es una violacion, aunque el
  fichero exista y aunque su basename coincida con uno permitido; tras el script se valida toda
  la cola con una tabla cerrada de flags y aridad derivada de los parsers reales. Se rechazan
  flags desconocidos, `flag=valor` para flags sin valor, valores ausentes o con apariencia de
  flag, posicionales no declarados y `--dry-run` en cualquier orden: ese modo silencia el aviso
  y deja sin cubrir B2. Los marcadores `<x>` solo son valores de una opcion que los consume;
- denylist: `-SimulateToastFailure`, `-EncodedCommand` y sus prefijos, `-Command` antes de
  `-File` y cualquier parametro no declarado despues del script,
  `-ExecutionPolicy Bypass`, `python -c` y `-m`, flags internos `--emit*`, `cmd.exe`;
- sin operadores de shell, salvo UN `> ruta` final en la orden de `quota_tick.py` (ruta absoluta, no
  UNC, con el directorio ya existente);
- inventario obligatorio por rol (cada item lo cubre UNA orden valida):
  - coordinadora: `comms_alert.py --scan`; `comms_alert.py --event`; `flight_stall_check.py` (el tick,
    sin `--self-check`); `flight_stall_check.py --self-check`; `quota_tick.py`; la orden del propio
    check con `--alert`.
  - supervisora: `notify_user.ps1` (PowerShell con `-File`) y `quota_tick.py`.

Codigos de salida: 0 todo correcto; 1 violacion; 2 ILEGIBLE (latido, git o interprete que no se
pueden verificar, roster declarado e ilegible, error de uso); 3 N/A solo si no hay roster
(`--roster-path` o `FLIGHT_ROSTER_PATH`, el mismo que usa el gate de roster). Con roster y sin
latidos es 1. Si hay ilegible y violacion gana 2. La ultima linea de la salida trae la orden exacta
para reproducir y revalidar.

Entrada: `--latido-file ROL=RUTA` (repetible) o `FLIGHT_LATIDO_FILES` (pares separados por `;`; la CLI
gana). Las rutas relativas del CHECK (`--latido-file`, `--roster-path`) se resuelven contra
`--motor-root`, nunca contra el cwd; las rutas de scripts dentro de una orden deben ser absolutas.

## 3. Consumidores

- A (OBLIGATORIO, cierre FINAL): el paso `latido_alert_wiring` de `session_closeout.py` (modulo
  `closeout_steps/gates.py`). dry-run: SKIP; sin roster: SKIP; roster declarado ausente: FAIL
  bloqueante; rc 0: PASS bloqueante; cualquier otro
  rc, timeout de 60 s o script ausente: FAIL bloqueante. El detalle del FAIL dice QUE falla, COMO
  reproducirlo (la orden exacta) y COMO revalidar. Se alimenta con `--latido-file` (repetible) en
  `session_closeout.py` o con `FLIGHT_LATIDO_FILES`, y con el mismo `--roster-path`.
- B2 (OBLIGATORIO durante el vuelo): el latido de la coordinadora ejecuta el check CON `--alert` en
  cada tick. Avisa URGENTE: `latido-desviado` (rc 1) o `latido-check-roto` (rc 2), owner `check`; rc 0
  resuelve ambas claves; rc 3 no emite ni resuelve. Si el aviso falla, el rc final es el mayor entre el
  diagnostico y 2 y la ultima linea lleva `diag_rc=<n> alert=ok` o `alert=fallido`.
  Limite: B2 depende del texto del latido; si alguien QUITA la orden del check, B2 deja de ejecutarse y
  solo lo ve A en el cierre FINAL.
- B1 (sonda en `collect_system_health.py`): NO existe. Medido en 153k: admite una sonda aditiva, pero
  toca pruebas fuera de la ficha y A + B2 cubren el caso. Limite declarado, no olvido.

## 4. Limites declarados

- El check mide el FICHERO del latido, no la copia que T3 ejecuta dentro de la tarea programada:
  comparar el hash citado en la tarea con el del fichero es un paso de la coordinadora al activar.
- Los roles los declara quien invoca el check: dos latidos sinteticos correctos pasan.
- Con `core.autocrlf` una diferencia SOLO de finales de linea del script no cambia el hash que compara
  git: no se detecta.
- No se exige `--ops-dir` en las ordenes del inventario (`FLIGHT_OPS_DIR` lo cubre y comms_alert falla
  en voz alta si falta).
- Resolver una ruta UNC consulta la red: por eso se rechaza ANTES de resolver.
- El denylist usa prefijos para cubrir abreviaturas peligrosas; por eso puede producir falsos FAIL
  en una opcion legitima que empiece por el mismo prefijo. Es una sobreamplitud deliberada del
  guard (nunca un falso PASS): el detalle self-service identifica la opcion que debe corregirse.
- Cada item del inventario debe estar cubierto por una orden valida DISTINTA; una sola orden no
  puede cubrir simultaneamente `comms_alert.py --scan` y `comms_alert.py --event`.
- Censo de roles por posicion: el primer token solo clasifica el interprete; los valores de opciones
  se consumen con su aridad antes de elegir el script; tras el script, los flags solo clasifican la
  orden ya estructurada; la redireccion solo se permite como el operador final de `quota_tick.py`.
  No hay una inferencia valida de "primer basename conocido".

## 5. Si el cierre falla en `latido_alert_wiring`

Es self-service: el detalle del FAIL trae las primeras causas y la orden. Ejecutala tal cual, corrige
el latido (rutas absolutas al motor, interprete fijado, las ordenes obligatorias de su rol) y repitela
hasta rc 0. No se escala al humano por esto. Si el check sale con rc 2, lee la causa: git que no
responde, interprete fijado ausente (`<motor>/.venv`), latido ilegible o roster ilegible.

## 5 bis. Solicitudes GO y límite residual de la cola

Una solicitud GO se produce únicamente con `comms_alert.py --go-id ... --what ... --owner ... --flight-dir ...`.
El `owner` obligatorio tiene la forma `^[A-Z]{2,3}-[0-9]{1,4}$`; el productor escribe
`- [YYYY-MM-DD HH:MM:SS] [OWNER] ABIERTA BLOQUEA | go-<id>: <frase>` usando el reloj local.
`--resolve <go-id> --owner <OWNER> --flight-dir ...` añade el marcador correspondiente
`RESUELTA | go-<id>: ...` (o `RESUELTA-SIN-EFECTO` con `--sin-efecto`).
El latido no debe fabricar manualmente una línea `ABIERTA BLOQUEA` ni usar `--event go-<id>` para
simularla; `check_latido_alert_wiring.py` lo marca como receta GO manual. La cola se comparte con
sesiones que pueden escribir directamente: el productor GO usa un bloqueo del sistema operativo y
append-only, detectando bloqueos huérfanos por la liberación del sistema operativo. Riesgo residual
declarado: un escritor externo que reescriba el fichero completo mediante Edit/Write puede perder
líneas concurrentes; este mecanismo no puede evitar una reescritura ajena y el dueño de esa deuda es
la coordinadora del vuelo.

La migracion de prompts/ARRANQUE y latidos existentes para invocar esta orden nueva queda
pendiente de CO-28; este ticket no modifica el workspace ni esos artefactos.
Toda corrida de `check_latido_alert_wiring.py --alert` fija `FLIGHT_OPS_DIR` a un directorio
temporal y stubbea el notificador (o usa `--dry-run`); nunca se ejecuta contra el ops-dir real.
Migracion pendiente: los prompts, latidos y ARRANQUE del workspace llamaran a `--go-id`; la hace
la coordinadora tras integrar y queda fuera de este ticket. El toast observado alrededor de
08:20–08:25 queda como causa NO DEMOSTRADA; no se dispone de dato fiable de la ultima corrida
`--alert` anterior al toast.

La barrera solo detecta secciones marcadas `GO AL USUARIO` o `ABIERTA BLOQUEA`; una petición GO
redactada con otra prosa queda fuera de alcance declarado (BA254 M2). Cuando sí hay sección GO,
debe existir una orden de solicitud completa con `--go-id`, `--what`, `--flight-dir` y `--owner`;
una orden `--resolve` sola no satisface esa barrera (BA03 m5b).
Limites BA03 H3: una cadena `--event go-...` citada dentro de un `--what` entrecomillado puede
marcarse como receta; `go_section` se activa por esa prosa en cualquier rol; y, mientras dura la
migracion, mencionar `ABIERTA BLOQUEA` en una seccion GO marca receta manual aunque tambien exista
una orden valida.

## 6. Ordenes exactas de un latido migrado

`<MOTOR>` es la raiz del worktree autorizado (donde viven `scripts/flight/` y `.venv`); `<PY>` es
`<MOTOR>/.venv/Scripts/python.exe`; `<OPS>` el directorio de operacion; `<VUELO>` el directorio del
vuelo. Una orden por linea de codigo en linea, rutas ABSOLUTAS (con `/` o con la barra de Windows).
Escribe cada orden completa (tambien las de `--ack` y `--resolve`, no solo `comms_alert.py --ack`) y
nunca `URGENTE` y `AVISO` unidos con una barra vertical sin comillas.

Coordinadora:

```
<PY> <MOTOR>/scripts/flight/comms_alert.py --ops-dir <OPS> --scan
<PY> <MOTOR>/scripts/flight/comms_alert.py --ops-dir <OPS> --event <clave> --level URGENTE --what "<frase>"
<PY> <MOTOR>/scripts/flight/comms_alert.py --ops-dir <OPS> --event <clave> --level AVISO --what "<frase>"
<PY> <MOTOR>/scripts/flight/comms_alert.py --ops-dir <OPS> --ack <clave>
<PY> <MOTOR>/scripts/flight/comms_alert.py --ops-dir <OPS> --resolve <clave>
<PY> <MOTOR>/scripts/flight/flight_stall_check.py --ops-dir <OPS> --flight-dir <VUELO>
<PY> <MOTOR>/scripts/flight/flight_stall_check.py --ops-dir <OPS> --flight-dir <VUELO> --self-check
<PY> <MOTOR>/scripts/flight/quota_tick.py --flight-dir <VUELO> > <OPS>/quota_last.txt
<PY> <MOTOR>/scripts/flight/check_latido_alert_wiring.py --alert --ops-dir <OPS> --flight-dir <VUELO> --roster-path <VUELO>/flight_roster.json --latido-file coordinadora=<LATIDO_COORDINADORA> --latido-file supervisora=<LATIDO_SUPERVISORA>
```

Supervisora:

```
C:/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -File <MOTOR>/scripts/flight/notify_user.ps1 -Title "<titulo>" -Message "<mensaje>"
<PY> <MOTOR>/scripts/flight/quota_tick.py --flight-dir <VUELO>
```

Retirada manual: borrar la clave del estado de `comms_alert` se hace con `--resolve`; un bloqueo del
estado huerfano se degrada solo (tras 5 s se sigue sin bloqueo).

## Gate de cupo por cuenta destino (quota_gate.py)

python scripts/flight/quota_gate.py --target-instance <providerInstanceId> --flight-dir <VUELO>

Opciones: `--supervision-policy strict|deferred` y `--strict-map`.

| rc | lectura por cuenta DESTINO |
|---|---|
| 0 | OK/RESERVA: pct < 92 |
| 3 | AVISO upstream de quota_tick (pct >= 90): no es veredicto del gate; el veredicto sale de la cuenta destino (pct < 92 => 0) |
| 4 | FREEZE: 92 <= pct < 97 |
| 5 | HARD: pct >= 97 (o supervision >= 97) |
| 9 | NO_MEDIDO fail-closed: timeout, rc de subprocess fuera de {0,3,4,5}, salida sin JSON v2 con accounts, cuenta no resoluble, stale/sin medir, block_pct no numerico o mapa estricto |

rc 0 es necesario pero no suficiente: la supervision estricta tambien debe estar medida y por debajo del HARD.

Opciones de supervision: `--supervisor-instance <providerInstanceId|cuenta>`.
En el vuelo-20261026b, `quota.reserve_for_orquestadora` es prosa y solo cuenta si su valor es el nombre exacto de una cuenta del censo; mientras sea prosa hay que pasar `--supervisor-instance`. Cambiar el roster queda fuera de esta ficha.

## Contrato 153t: identidad y acciones

El productor usa `{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe` como `AppId` predeterminado y lo expone en
`-XmlOnly`; `-AppId` solo permite parametrizarlo. Este ticket no registra AppIds ni escribe el
Registro de Windows: queda diferido a un ticket hijo con recibo. Por ello existe una limitación
de suplantación: otro proceso que conozca ese AppId puede presentar avisos con la misma identidad.

`-XmlOnly` no muestra un toast ni modifica el historial. La forma válida contiene únicamente la
acción `Entendido` (`system`, `dismiss`) y, si se solicita `-OpenUri`, `Abrir sesion`
(`protocol`, `t3code://threads/...`). Cerrar no es reconocer: el texto fijo del aviso URGENTE
indica que vuelve a avisar a 30/60/120/240 minutos. `History.Remove`/limpieza solo se intenta para
nuestro Tag/Group y AppId, y si falla el estado canónico se conserva y el fallo se registra.

Los ganchos `-SimulateToastFailure` y `-SimulateNotifierSetting` son solo de prueba y están
prohibidos en las órdenes de latido; nunca deben viajar desde una orden de producción.
El fallo `Setting != Enabled` hace fallar la publicacion; la retirada de un toast durante
`ack`, `resolve` o `reconcile` es fail-soft: el estado canonico se actualiza y un fallo de
limpieza queda en el ledger. El `title` legado de `event` y `--title` del CLI se conservan por
compatibilidad, pero se ignoran: el titulo visible es siempre el codigo de sesion valido o
`Vuelo ?`. El vigilante solo limpia el Group propio cuando no hay causas activas.
La limpieza del Group es condicional: solo se ejecuta cuando no queda ninguna clave `event:` activa; una causa activa de otro productor impide la retirada global.
`-OpenUri` puede llevar query en el productor, pero ningun productor de este ticket lo genera; queda reservado a 153v.
El `--what` de un GO es solo la frase literal completa, escrita por la coordinadora y limitada a 160 caracteres; no lleva detalle adicional.
