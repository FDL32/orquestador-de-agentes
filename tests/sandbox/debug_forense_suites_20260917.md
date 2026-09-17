# Forense: por que morian las suites (2026-09-17)

## 0. RESULTADO

**LA CAUSA SIGUE SIN DETERMINAR.** Lo unico establecido es la CLASE de muerte:
terminacion abrupta que no desenrolla la pila de Python. El AUTOR no esta identificado.

> ### AVISO: la hipotesis del editor/extension quedo REFUTADA (bucle L1020, ronda 1)
>
> La v1 de este informe sostenia que el editor o sus extensiones mataban el arbol de
> procesos. **El cruce de logs de los IDEs con las ventanas de muerte no lo respalda** --
> comprobacion que propuso la lente BA06 y que la v1 no contemplaba:
>
> - **Sesiones de ventana creadas hoy:** VS Code 00:31, 11:18, 11:18, 12:02; Cursor 11:18.
>   **Ninguna** en la franja de muertes (06:52-09:00). El hueco 00:31 -> 11:18 no tiene
>   ningun arranque nuevo: una sola ventana (`window1`) activa de forma continua.
> - **Extension host:** `3-Kilo Agent Manager.log` registra cada ~7 s. En 4390 entradas
>   (2026-09-16 22:36 -> 2026-09-17 09:17 UTC) hay **UN solo hueco >60 s**: 03:37->05:33
>   UTC = **05:37->07:33 local**. Cubre la PRIMERA muerte (06:52) pero **no las otras
>   cinco** (07:56, 08:11, 08:32, 09:00), durante las cuales la extension estaba viva.
>
> **Y la corroboracion del `exit_code` apuntaba al reves.** La v1 afirmaba que
> `4294967295` = `0xFFFFFFFF` era "el codigo que Windows devuelve ante terminacion
> externa". **FALSO, medido en esta maquina:**
>
> | metodo | exit code |
> |---|---|
> | `taskkill /F` | **1** |
> | `Popen.kill()` | **1** |
> | **`sys.exit(-1)` voluntario** | **4294967295** |
>
> Una terminacion externa deja `1`. El `0xFFFFFFFF` es lo que deja una salida
> VOLUNTARIA con codigo -1. La "corroboracion central" del informe apuntaba en direccion
> contraria a la que afirmaba.
>
> **Limite de esa medicion:** `TerminateProcess` devuelve el codigo que le pase el
> asesino, asi que `1` no es universal -- pero `0xFFFFFFFF` NO es la firma que la v1
> decia, y eso basta para retirar el argumento.

**LO QUE SI QUEDA ESTABLECIDO** (y sobrevive a la refutacion de arriba):

1. La muerte **no desenrolla la pila de Python** (seccion 1.1).
2. Hay un **gradiente de exposicion**: las corridas cortas sobreviven, las largas no
   (seccion 1.2).
3. **No es memoria**, no es rafaga de spawns, no es concurrencia entre suites, no es
   Defender, no es Internxt, no es la configuracion del lanzamiento (seccion 2).

**Contexto que sigue siendo relevante aunque no sea la causa:** cinco IDEs, cada uno con
las extensiones de Claude Code y Kilo Code, ambas actuando como Manager y como Builder.
Cualquiera de esas sesiones puede lanzar una suite, y el historial NO registra cual lo
hizo (seccion 4, P2).

## 1. LA EVIDENCIA

### 1.1 La firma es de muerte que NO desenrolla la pila
*(Titulo corregido: la v1 decia "terminacion externa dura", que presupone un autor
externo. Lo que el dato prueba es la CLASE de muerte, no quien la causo.)*
`run_pytest_safe.py:975` tiene un `finally` que escribe `last-run.log` SIEMPRE -- ante
excepcion y ante `KeyboardInterrupt` (que ya se captura en `:696`). En las SEIS muertes
ese `finally` **no corrio**: el `last-run.log` seguia siendo el de una corrida focal
anterior (08:49, 103 passed). Un proceso que muere por OOM o por Ctrl+C SI ejecuta el
`finally`. Lo que no lo ejecuta es `TerminateProcess`.

**CORROBORACION RETIRADA.** La v1 usaba aqui el `exit_code: 4294967295` del checkout
principal como prueba de terminacion externa. Medido: ese codigo lo produce
`sys.exit(-1)` VOLUNTARIO; `taskkill /F` y `Popen.kill()` dejan `1`. El argumento
apuntaba al reves y se retira.

**Vias NO excluidas por las que el `finally` podria no dejar log** (hallazgo de la lente
BA06 leyendo el codigo): un SEGUNDO `KeyboardInterrupt` que aterrice dentro del propio
`finally` antes del `open()`; un crash nativo del interprete; un `os._exit()` en otra
parte del fichero; o que el `finally` SI corra y el `open()` falle por sharing violation.
"Si no corre el finally, fue TerminateProcess" es demasiado fuerte.

**Refuerzo que la v1 no uso** (y que fortalece el argumento restante): si el `finally`
hubiera corrido con cero lineas, `write_text("")` habria dejado el log **vacio**, no con
el contenido integro de las 08:49. El log intacto prueba que el fichero **nunca se abrio**.

### 1.2 El gradiente de exposicion

| level | duracion REGISTRADA (inflada en las muertas) | corridas | resultado |
|---|---|---|---|
| `unit` | 18-118 s (real) | 3 | **3 finished** (92, 11, 103 passed) |
| `all` | ~20 min (NO es la real) | 6 | **6 aborted** |
| `all` | 22 min (real) | 1, desacoplada | **finished, 6631 passed** |

Las cortas sobreviven, las largas no. Compatible con "algo mata el arbol cada cierto
tiempo", pero **no discrimina el autor**.

**AVISO sobre la columna "duracion tipica"**: la de las muertas (~20 min) esta INFLADA --
el `finished_at` de un `aborted` es cuando se lo RECONCILIO, no cuando murio (ver 3.3).
La duracion real de las muertas es DESCONOCIDA. Lo que la tabla sostiene es el contraste
`unit` (segundos, 3/3 vivas) vs `all` (minutos, 6/6 muertas), no los minutos exactos.

### 1.3 La corrida verde: que cambio y que no
La corrida de 09:33 se lanzo desde un proceso en BACKGROUND, desacoplado del editor.

**CORRECCION (L1020): NO fue "el unico factor que cambio".** Cambiaron DOS: el lanzador
**y** Procmon (activo en la verde, ausente en las muertas). Es N=1 con dos variables, no
un discriminante limpio. Lo que si es solido es que las condiciones NO mejoraron:

- `args_mode`, `interpreter_kind`, `runner`, `level`, `command`, `basetemp`: **identicos**
  (verificado campo a campo en `run_history.jsonl`).
- Memoria al arrancar: **1612 MB / 94,9% en uso** -- el PEOR punto de partida del dia. Las
  que murieron arrancaron con 4310 MB y 1089 MB.
- Ademas corrio con Procmon activo, consumiendo 5,2x mas CPU que la propia suite (esto
  es la SEGUNDA variable, no solo un agravante).

Y aun asi: 6631 passed, 50 skipped, 1329,62 s, `exit_code: 0`, lock liberado limpiamente.

## 2. LO QUE QUEDA DESCARTADO (con la medicion que lo descarta)

| Hipotesis | Refutada por |
|---|---|
| **OOM / falta de memoria** | 0 eventos de `Resource-Exhaustion-Detector` en TODO el historial del sistema. Y la corrida verde arranco con 1612 MB, menos que cualquiera de las muertas. |
| **Rafaga de spawns agota asignaciones** | 657 de 659 call-sites son `subprocess.run` BLOQUEANTE; solo 3 son `Popen`. Van en serie: ~2 procesos a la vez, nunca 1318. Coste total en spawns ~31 s sobre 18 min = 3%. |
| **Dos suites concurrentes se matan** | Cruce de historiales de los 11 repos: en la ventana de muertes (06:52-09:00) el motor estaba practicamente SOLO -- una unica corrida ajena (principal, 08:04). |
| **`Stop-ProjectAgentProcesses`** | Leidos sus patrones: `ticket_supervisor.py`, `manager_review_bridge.py`, `kilo.exe run --auto`, `opencode --agent builder`. NINGUNO casa con `run_pytest_safe.py` ni con `-m pytest`. |
| **Windows Defender** | 0 detecciones (`Get-MpThreatDetection` vacio). |
| **Internxt** | Par A/B con probe de 30 s: create +29%, write +9%, delete +15%, spawn +10%, read +6% -- todo sobre decimas de milisegundo. Para contexto, entre corridas el `spawn_ms` llego a x2,3. Ademas el `max` de spawn BAJO con Internxt abierto: ruido, no senal. |
| **Como se lanzaban (flags/config)** | Las 6 muertas y la verde tienen `command`, `args_mode`, `basetemp`, `level` y `runner` IDENTICOS. |

## 3. HIPOTESIS QUE YO MISMO EMITI Y SON FALSAS -- no re-proponer

1. **"Mueren por falta de memoria."** Sostenido durante horas y refutado por la corrida
   verde con 1612 MB. Toda la propuesta de "presupuesto de RAM por roles" (cerrar Brave,
   Devin, sincronizadores) atacaba un problema inexistente.
2. **"15 GB estan en el pagefile / hay swapping intensivo."** Deducido de `46-31`. FALSO:
   el pagefile tenia 3,27 GB en uso. El commit incluye memoria prometida y nunca tocada;
   esa resta no mide swap.
3. **"Intervalos de 2-8 s entre corridas = algo relanza en bucle."** ARTEFACTO:
   `_reconcile_dead_run()` corre al ARRANCAR una corrida nueva y marca la anterior como
   abortada, asi que el `finished_at` de un `aborted` es *cuando se reconcilio*, no cuando
   murio. Las "duraciones" de las muertas estan infladas por ese motivo.
4. **"Procmon frena la creacion del run_dir."** La suite termino 22 min despues y el
   `run_dir` NUNCA se creo. Sigue sin explicacion (seccion 5).

## 4. PROPUESTA

### P1 -- Lanzar las suites largas DESACOPLADAS (precaucion, no remedio)
Coste cero y reversible. Vias: ventana de terminal independiente, `Start-Process`
desacoplado, o tarea en background.

**ESTATUS DEGRADADO tras la refutacion:** la v1 lo presentaba como el remedio derivado de
la causa. Con la causa sin determinar, P1 es una **precaucion barata cuya eficacia no
esta demostrada**: la unica corrida verde fue desacoplada, pero es N=1 con dos variables
(ver 1.3). Se mantiene porque no cuesta nada y no puede empeorar nada, no porque se sepa
que funciona. **Ningun numero respalda la tasa de recargas del editor**: nunca se midio.

### P2 -- El historial NO registra quien lanzo: ese es el hueco que impide cerrar esto
Censo ejecutado sobre las entradas de hoy en `run_history.jsonl`. Campos presentes:
`args_mode, duration_s, environment_at_start, errors, exit_code, failed_count,
finished_at, interpreter_kind, level, passed, skipped, started_at, status,
tested_commit_sha, top_slowest`. **NINGUNO identifica al lanzador.**

Sin ese campo, un forense como este depende de que el operador recuerde como lanzo cada
corrida. Propuesta: registrar la cadena de procesos padre en `environment_at_start`
(`Win32_Process.ParentProcessId` recursivo hasta el primer proceso no-python, con su
nombre). Es la misma superficie que la Pieza A de WOT-2026-062e y no anade dependencias.

Con ese campo, la hipotesis principal de este forense se contrastaria SOLA en la siguiente
muerte, sin par A/B.

### P3 -- RETIRADA como propuesta independiente
La v1 proponia avisar si el padre es un host de editor. Sin causa establecida, ese aviso
no tiene fundamento; y su contenido real (una linea de log y un warning) cabe dentro de
P2. Ambas lentes coincidieron en plegarla.

### P3' -- INSTRUMENTACION QUE DISCRIMINA (lo que de verdad falta)
Las dos lentes convergieron en que lo ausente no es otra hipotesis, sino capacidad de
distinguir entre las que quedan. Tres medidas, todas de coste ~0:

1. **Auditoria de creacion/terminacion de procesos de Windows** (`auditpol`, eventos 4688
   con linea de comando y 4689). Deja registrado cualquier `taskkill`/`Stop-Process`
   **con su propio proceso padre**. Es lo unico que nombraria al asesino si es externo a
   la cadena de padres de la victima -- el hueco que P2 por si sola NO cubre.
2. **WER LocalDumps para `python.exe`** (una clave de registro). La proxima muerte CON
   dump = crash nativo; SIN dump y proceso esfumado = terminacion externa. Discrimina las
   dos explicaciones rivales que quedan vivas.
3. **Heartbeat periodico** en `last-run.json` (la Pieza A de WOT-2026-062e ya escribe ahi
   con `fsync`). Un `last_heartbeat` cada N segundos acota la muerte a una ventana
   estrecha en vez de a un intervalo de 20 minutos, y de paso da la duracion REAL de las
   corridas abortadas, que hoy es desconocida.

### P4 -- El invariante de `finished` (identificado en el bucle L1019)
`status: finished` con `exit_code: 4294967295` y `passed: None` satisface la LETRA del
contrato mientras registra una corrida muerta como completa. Censo: de **475** entradas
`finished` en el historial, **48** tienen `passed: None` o exit_code fuera del rango de
pytest. Regla: `finished` DEBE implicar `exit_code in 0..5` **y** `passed is not None`.

### P5 -- Lo ya fichado, que sigue vigente por otros motivos
`WOT-2026-070d` (el lock es por-repo y no ve a sus hermanos) NO era la causa de estas
muertes -- el cruce de historiales lo descarta. Pero sigue siendo un defecto estructural
real: 11 repos con runtime de suite, 11 locks que se ignoran, y un `%TEMP%\pytest-safe\`
compartido por todos.

## 4.bis SON DOS FENOMENOS, NO UNO (hallazgo de la lente BA06 r1, verificado en r2)

El informe venia tratando las muertes del motor y la del checkout principal como el mismo
suceso. **No lo son**, y el `exit_code` lo demuestra:

| Caso | n | status | exit_code | ¿quien murio? |
|---|---|---|---|---|
| motor | **7** | `aborted` | **`None`** | el runner: no llego a escribir nada |
| principal | **1** | `finished` | **`4294967295`** | solo el HIJO: el runner SOBREVIVIO y escribio el cierre |

Verificado recorriendo las entradas `aborted` de `run_history.jsonl`: **las siete tienen
`exit_code: None`**. El `0xFFFFFFFF` aparecio UNA sola vez y en el otro repo.

**Por que importa:** en el caso del principal el runner vivio lo suficiente para registrar
`finished` con el codigo del hijo. Un suceso que matara el ARBOL se habria llevado al
runner tambien. Son mecanismos distintos, y mezclarlos fue un error de la v1.

**Y ese segundo caso no es de hoy:** el censo de P4 encuentra **48 de 475** entradas
`finished` con `passed: None` o exit_code fuera del rango de pytest. El "hijo que muere
dejando vivo al padre" es un fenomeno CRONICO del historial, no un episodio de esta
manana.

**CORRECCION a una lente:** la lente BA12 afirmo en la ronda 2 que "el exit_code es el
mismo en las seis muertes y distinto en la verde". Es FALSO: las abortadas tienen `None`.
Se deja anotado porque el informe no debe heredar ese error.

## 5. LO QUE SIGUE SIN EXPLICAR

**El `run_dir` que nunca se crea.** La corrida verde declaro
`run-20260917-113341-44044` como `--basetemp`, corrio 22 minutos, paso 6631 tests... y ese
directorio NO existe en disco. Las corridas historicas creaban su primer `tmpdir` en 2-4
segundos, y 242 de 321 ficheros de test usan `tmp_path`.

No tengo explicacion. Es una anomalia real, reproducible y **no impide que la suite pase**,
lo que la hace aun mas extrana. Merece investigacion propia.

## 6. COMO SEGUIR (ordenado por coste, todo antes que un A/B de 80 min)

1. **P3'-1 y P3'-2** (auditoria de procesos + WER dumps): dos comandos, coste ~0, y
   convierten la proxima muerte en dato atribuible. **Es el paso siguiente.**
2. **P2** (registrar el lanzador) y **P3'-3** (heartbeat): capacidad instalada en la misma
   superficie que la Pieza A de WOT-2026-062e.
3. **A/B reducido** (sugerencia de la lente BA06): UN solo brazo -- una corrida
   `--level all` desde el editor, bajo Procmon filtrado a `Process Exit`. ~25 min, un
   cuarto del coste del A/B completo, y probablemente captura el exit code y el arbol en
   el acto.
4. **A/B completo** (~80 min) solo si lo anterior no discrimina.

**LECCION DE METODO DE ESTE FORENSE.** Se emitieron cuatro hipotesis sucesivas (memoria,
rafaga de spawns, suites concurrentes, editor/extension) y **las cuatro se refutaron con
datos que ya estaban en disco**: el historial de corridas, los logs de los IDEs y un probe
de tres lineas sobre exit codes. Ninguna necesito un experimento nuevo. El coste no fue
medir: fue **no haber mirado antes lo que ya estaba escrito**.
