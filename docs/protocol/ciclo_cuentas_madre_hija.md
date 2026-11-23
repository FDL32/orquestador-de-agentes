# Ciclo de cuentas madre/hija

Contrato de WOT-2026-205a. `account_cycle.py` decide; los hilos ejecutan los
movimientos mediante MCP. El guard no llama a `t3_thread_configure`.

## Fases del ciclo

| Fase del ciclo | Flags principales |
| --- | --- |
| FASE A | madre e hija en alvarovans: `madre_en_refugio=false`, `hija_en_refugio=false` |
| FASE B | madre en refugio/brabander, hija consumiendo alvarovans: `madre_en_refugio=true`, `hija_en_refugio=false` |
| FASE C | ambas en brabander hasta reset+1: `hija_en_refugio=true`, `agotada` y `despertar_en` fijados |
| FASE D | retorno al despertar: `secuencia_retorno` 1 -> 2 -> evento `madre_en_preferida`, vuelve a FASE A |

Estas fases A-D del CICLO no son las fases A-D de cada movimiento de un hilo del PROCEDIMIENTO_CAMBIO_CUENTA_CICLICO_v3 (homonimos en contextos distintos).

La MADRE es la supervisora y la HIJA la coordinadora. La HIJA mueve a la
MADRE; la MADRE mueve a la HIJA.

## Registro de la sesion revisora IM (WOT-2026-221d)

El estado conserva estas cinco claves hermanas de `madre_en_refugio` y
`hija_en_refugio`: `revisor_im_en_refugio=false`,
`revisor_im_cuenta=null`, `revisor_im_fase=null`,
`revisor_im_relevo=null` y `revisor_im_retorno=null`. Un estado persistido
anterior sin ellas se completa con estos defaults al leerse; no es un error.

Los eventos cerrados `revisor_im_en_refugio`, `revisor_im_en_preferida`,
`revisor_im_fase_a`, `revisor_im_fase_b`, `revisor_im_fase_c` y
`revisor_im_fase_d` solo registran la observacion: actualizan cuenta, refugio,
fase y el timestamp ISO de relevo o retorno, pero no ejecutan movimiento ni
añaden acciones `MOVE_*`.

La restriccion de FASE B se aplica a las tres entidades (madre, hija y
`revisor_im`, que no son cuentas): los subagentes largos Claude están
prohibidos en FASE B, con `alvarovans` o `brabander`. La funcion pura
`subagentes_largos_claude_permitidos` solo permite A, C y D y falla cerrado
para B, valores ausentes o desconocidos. La cuenta registrada por
`revisor_im_cuenta` debe ser siempre la preferida `alvarovans` o el refugio
`brabander`, según la disponibilidad declarada por este ciclo.

## Reglas de la hija

En la FASE B la HIJA lanza sus lentes y subagentes con CODEX y NUNCA con claude alvarovans (moririan a medias al agotarse); los lentes claude solo con cuenta brabander explicita, permitidos en la FASE C.

## Acciones

| Acción | Ejecutor |
| --- | --- |
| `MOVE_MADRE_REFUGE` | hija |
| `MOVE_HIJA_REFUGE_Y_PROGRAMAR_DESPERTAR` | madre |
| `REINTENTAR_DESPERTAR` | madre |
| `MOVE_HIJA_PREFERIDA` | madre |
| `MOVE_MADRE_PREFERIDA` | hija |
| `AVISAR_RESET_NO_OBSERVADO` | madre |
| `ESPERAR`, `NONE` | ninguno |

El flujo de retorno es `MOVE_HIJA_PREFERIDA` y después
`MOVE_MADRE_PREFERIDA`. Si la cuota semanal restante es menor que 5 %, no se
permite el retorno antes de `weekly_resets`. Un límite sin reset observado
produce `AVISAR_RESET_NO_OBSERVADO`.

## Eventos y comandos

Los hilos invocan la CLI; cada evento se guarda con `--guardar`:

```text
python scripts/flight/account_cycle.py --cache CACHE --estado ESTADO --roster-path ROSTER --evento limite --guardar
python scripts/flight/account_cycle.py --cache CACHE --estado ESTADO --roster-path ROSTER --evento limite_semanal --guardar
python scripts/flight/account_cycle.py --cache CACHE --estado ESTADO --roster-path ROSTER --evento madre_en_refugio --guardar
python scripts/flight/account_cycle.py --cache CACHE --estado ESTADO --roster-path ROSTER --evento hija_en_refugio --guardar
python scripts/flight/account_cycle.py --cache CACHE --estado ESTADO --roster-path ROSTER --evento madre_en_preferida --guardar
```

Los eventos se aplican antes de decidir y solo persisten con `--guardar`.
La regla de oro es guardar únicamente después de ejecutar el movimiento
solicitado. Una ejecución sin `--guardar` es una simulación y no escribe.

Al iniciar con roster se guardan `cycle_id` y `roster_sha12`; un cambio de
roster aborta el ciclo antes de mover.

## Estados terminales y dwell

| Estado terminal | Accion | Ejecutor |
| --- | --- | --- |
| `MADRE_AGOTADA_EN_REFUGIO` | avisar, sin movimiento | madre |
| `AMBAS_AGOTADAS` | suspender despacho y avisar al usuario | madre |
| `DESPERTAR_NO_EJECUTADO` | avisar tras `wake_at + 10 min` | madre |
| `RESET_NO_OBSERVADO` | `AVISAR_RESET_NO_OBSERVADO` tras 5 reintentos | madre |
| `ABORTAR_CICLO_Y_AVISAR` | abortar ciclo, sin movimiento | madre |

NOTA OPERATIVA: el dwell es de 45 minutos por hilo desde su ultimo movimiento.
E3 (agotamiento) y E4 (retorno) son exentos; movimientos de hilos distintos no
violan el dwell. Lo cuentan los hilos y lo verifica la coordinadora;
`account_cycle.py` NO lo implementa en este ticket.

La proyeccion acepta la ultima pareja adyacente valida: `checked_at` distinto
y creciente, al menos 60 segundos, misma ventana y reset cuando ambos existen,
y porcentajes finitos. Sin pareja valida usa el suelo conservador de 1
punto/min y persiste la razon en `tasa_razon`.

`AGOTAR` aparece solo en la linea de texto; el JSON v2 y sus claves estan
congelados. `estado_operativo` puede ser `CAMBIO` en una cuenta mientras el rc
global es 0: es intencionado. Un evento `limite` debe identificar el limite del
run y de la cuenta actuales; un failed generico no basta. El 98-99 sin evento
es casi agotada y no produce movimiento.

Un despertar tardio, de mas de 10 minutos, no bloquea el retorno cuando quota
es menor que 85 y no hay latch: se ordena `MOVE_HIJA_PREFERIDA` con motivo
`retorno-tardio`. `DESPERTAR_NO_EJECUTADO` solo se emite cuando concurren las
condiciones de bloqueo y se resuelve cuando dejan de cumplirse.

Si la hija agotada no responde a la fase A, la madre verifica que el hilo no
esta running y no tiene cola, inventaria y desactiva sus tareas, y conserva su
ultima entrada de OPERACION: es `A_DEGRADADA`.

El cierre es un MECANISMO. El cableado de roster, latidos y vigilancia sin LLM
lo hace y lo verifica la coordinadora; no se declara implantado hasta medirlo.

## Contrato del cache

Cada cuenta puede llevar `{pct, weekly_pct, resets, weekly_resets, windows,
checked_at}`; cada `windows` contiene `id`, `label`, `pct` y `resets`.
`checked_at` acepta segundos epoch o ISO con offset explicito. El BOM UTF-8 se
tolera mediante `utf-8-sig`; ISO sin zona devuelve rc 9. Epoch en milisegundos
tambien devuelve rc 9.

MOVE_MADRE_REFUGE puede ordenarse con la hija ya agotada, pero la hija en ese
estado no puede ejecutarlo; es el caso A_DEGRADADA de la nota existente y lo
resuelve la madre.

## Seguridad operacional

Contrato de guardado: un tick con accion `NONE` o `ESPERAR` se guarda siempre
para acumular lecturas; cualquier otra accion se guarda solo despues de
ejecutar el movimiento. `ABORTAR_CICLO_Y_AVISAR` no tiene salida automatica:
la supervisora entrante mide cada hilo y reinicia el estado a mano con nuevo
`cycle_id` y `roster_sha12`.

Todo tick debe pasar `--roster-path` o `FLIGHT_ROSTER_PATH`; sin ello aborta
con ciclo iniciado. Solo un escritor del estado opera a la vez; no hay lock.
Rc 2 de argparse sale sin JSON. El latido despacha por accion y ejecutor, no
por rc.

La CLI usa `--cache` o `CC_USAGE_CACHE`, `--estado` o `ACCOUNT_CYCLE_STATE`,
y `--roster-path`, con precedencia `FLIGHT_ROSTER_PATH` > `FLIGHT_ROSTER`.
Una cache ausente, ilegible, vieja o futura, una lectura no numérica, o un
estado no resoluble al guardar es fail-closed: rc 9, acción `NONE`, y ningún
movimiento. `ESPERAR` y `NONE` devuelven rc 0; una acción requerida devuelve
rc 10; un evento desconocido devuelve rc 2. La escritura con `--guardar` es
atómica.

Excepción acotada WOT-2026-205c: si el estado está en FASE C completa
(`madre_en_refugio=true`, `hija_en_refugio=true`, `agotada="semanal"` y
`despertar_en` numérico y futuro), la caché de `alvarovans` puede conservar
`resets` o `weekly_resets` no numéricos y `checked_at` viejo. La decisión de
espera usa exclusivamente `estado.despertar_en`; la excepción no se extiende
al resto de la validación de la caché. En esa rama también se omite la
comprobación del rango de los resets numéricos de la cuenta preferida (no se
evalúa la ventana `checked_at - 1 día .. checked_at + 8 días`); fuera de FASE C
ese rango sigue siendo obligatorio. Esto solo documenta el comportamiento
vigente y no cambia el código. En esa rama `brabander`, la cuenta refugio decisora, debe seguir teniendo
datos válidos y un `checked_at` fresco (<= 1200 s); si falta o está vieja el
guard sigue devolviendo rc 9. Fuera de esos cuatro predicados, la regla
general de caché vieja o futura = rc 9 permanece intacta.
