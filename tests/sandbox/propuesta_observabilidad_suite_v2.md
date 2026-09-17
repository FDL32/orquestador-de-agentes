# PROPUESTA v2: observabilidad de la suite -- 6 canales

Fecha: 2026-09-17. Motor `_dev` HEAD `5c2eefc`. Estado: PROPUESTA con probes ejecutados.
Auditada por bucle L1106 (nonce `7f97fb78...`): **3 lentes validas (BA05 codex, BA11 qwen3.6,
BA12 mimo), las 3 con BLOCKER convergente**. `check_loop_execution` OK.

**Nomenclatura: `P-B` -> `C1-HEARTBEAT`.** Colisionaba con `Pieza B` (`_reconcile_dead_run`).

---

## 0. QUE CAMBIA RESPECTO A LA v1

| # | Cambio | Lente |
|---|---|---|
| 1 | **Canal C6 NUEVO: monitor externo del ciclo de vida.** BLOCKER unanime: ningun canal identificaba al AGENTE | BA05, BA11, BA12 |
| 2 | **Semantica de `end` definida por FASE**, no por test | BA11 (BLOCKER) |
| 3 | **DoD de integridad del artefacto**: `flush()` != persistencia | BA05 (ALTA) |
| 4 | **Hooks fail-open obligatorio**: pueden ser una nueva causa de muerte | BA05, BA12 |
| 5 | **Orden reordenado**: C5 y C6 suben; C3 baja | las 3 |
| 6 | Identidad de proceso = **PID + hora de creacion**, nunca PID solo | BA05 |

---

## 1. EL DEFECTO RAIZ (medido)

Todo lo que la suite sabe de si misma se escribe **al final**, y las corridas que interesan
**no llegan al final**.

- `last-run.log`: UNA `write_text` en un `finally` (`stream_pytest:975`). Tras matar dos
  corridas de ~19 min de CPU: **intacto, 1372 bytes de un focal anterior**.
- `conftest.py`: su unico hook de sesion es `pytest_sessionfinish` (`:296`).
- Las 9 filas `aborted`: `top_slowest: []`, `passed: None`. **Cero nodeids.**
- `finally` y `atexit` **no corren ante TerminateProcess**.

Y con `-q` cada test es un punto SIN NOMBRE; con `-v` el nodeid se emite al TERMINAR.
Por eso hay que registrar el **INICIO**, y por fase.

---

## 2. LOS 6 CANALES, EN ORDEN CORREGIDO POR EL BUCLE

### C5-EXITCODE CRUDO -- coste cero, ya dio fruto [PRIMERO]

No normalizar el exit code a 0..5. Decodificando los 48 anomalos aparecio
**`0x40010004` = `DBG_TERMINATE_PROCESS`** (terminado por un DEPURADOR) en 3 corridas `all`
(27-ago, 3-sep, 6-sep). **El forense analizo `0xFFFFFFFF` y NUNCA vio este** (0 hits en sus
250 lineas). Si el runner lo hubiera normalizado, la pista se habria perdido.

**Limite (BA05):** es una PISTA del tipo de agente, no su identidad. Guardar ademas comando,
padre, entorno y relacion temporal con la muerte.

### C6-CICLO DE VIDA EXTERNO -- el canal que FALTABA [NUEVO, PROBADO]

Monitor **fuera** de pytest que registra por corrida: PID, PPID, **hora de creacion**, estado,
arbol de procesos, `IsProcessInJob`, exit code crudo via `GetExitCodeProcess`, e instante en
que el padre detecta la muerte.

**PROBES EJECUTADOS:**

- PPID + `CreationDate` legibles via `Get-CimInstance Win32_Process`.
- `IsProcessInJob` (ctypes/kernel32) -> `rc=0 in_job=False`. **Si un proceso esta en un Job
  Object, cerrar el job MATA el arbol entero sin aviso** -- mecanismo compatible con "no
  desenrolla la pila" y NO explorado por el forense.
- Auditoria 4688/4689 de Windows: **requiere admin**, no disponible.
- **Sensor de depurador (BA16, probado):** `CheckRemoteDebuggerPresent` e `IsDebuggerPresent`
  (kernel32 via ctypes) -> `rc=0 debugger_adjunto=False` en un proceso limpio. **Responde
  DIRECTAMENTE a la pista que abre C5:** si `0x40010004` dice que un depurador mato 3
  corridas, este sensor lo detecta **en vivo**, muestreado durante la corrida. Coste: dos
  llamadas ctypes. **La v1 dejaba esa pista tirada.**

**EVIDENCIA DIRECTA DEL RIESGO DE PID RECICLADO (medida al probar):** el `ppid 27612` de una
corrida de las **17:18** aparece ahora como `bash.exe` creado a las **22:43**. Es un PID
**reciclado**. Atribuir paternidad por PID solo habria acusado al proceso equivocado.
**Por eso la identidad es PID + hora de creacion.**

### C1-HEARTBEAT -- hooks de protocolo, POR FASE [PROBADO, corregido]

`pytest_runtest_logstart` + `pytest_runtest_logreport` (por fase) + `pytest_collection_finish`.
NDJSON append-only, `flush()`, **fail-open**.

**BLOCKER de la v1 (BA11): C1 era ciego a crashes en setup/teardown.** `logreport` corre por
FASE (`setup`/`call`/`teardown`); un DoD de "start sin end" no distingue en cual murio.

**PROBE con la correccion:**

    {"ev":"start","nodeid":"...::test_muere_en_call"}
    {"ev":"phase","nodeid":"...::test_muere_en_call","when":"setup","outcome":"passed"}

`setup` completado y **sin `call`** -> murio EN LA LLAMADA. Punto exacto, sin ambiguedad.

**Semantica definida:** un test esta COMPLETO solo con sus 3 fases. El punto de muerte es
`(ultimo nodeid, ultima fase registrada)`.

### C4-FORENSE -- que Pieza B escriba sus 4 campos

`reconciled_at`, `reconciled_reason`, `lock_pid`, `assumed_dead`: existen en codigo y **no se
pueblan (0 de 9 filas)**. Consecuencia: **el conteo de muertes NO es re-derivable**, y hay un
FANTASMA PROBADO (la fila de 15:18:35 declara muerta una corrida cuyo pid siguio vivo ~90 min).

**BA05:** no basta poblar 4 campos -- la reconciliacion debe usar PID + hora de creacion y
distinguir `alive` / `exited` / `unknown` / `pid_reused`.

### C2-FAULTHANDLER -- volcado de stack ante cuelgue [PROBADO]

`faulthandler.dump_traceback_later(N, repeat, file)`. Stdlib: **no requiere la aprobacion de
dependencia que si exigiria `pytest-timeout`**.

**PROBE:** funcion durmiendo 10 s con watchdog a 2 s ->
`Timeout (0:00:02)! Thread 0x229c: File "probe.py", line 5 in funcion_que_cuelga`.

**CORRECCION CRITICA (BA16-A2, verificada con probe propio): `dump_traceback_later` NO detecta
"no avanza" -- es un temporizador de tiempo ABSOLUTO.** Probe: proceso haciendo trabajo
continuo durante 4 s con watchdog a 2 s -> **volco igual**. Sobre una suite de 15 min con un
umbral razonable, dispararia SIEMPRE: falso positivo garantizado. Mi descripcion original del
mecanismo era FALSA.
**ARREGLO (probado): rearmarlo por test.** `cancel_dump_traceback_later()` +
`dump_traceback_later(N)` desde `logreport`, de modo que N mida la duracion de UN test y no
la de la sesion. Probe de 3 tests (0.1 s, 0.1 s, 3 s) con N=1 s -> **1 solo volcado**, el del
test lento. Sin el rearme, C2 es ruido.

**Alcance ACOTADO (BA05):** cubre solo "proceso vivo y sin progreso". No ayuda si el proceso
muere antes del disparo ni si el bloqueo es nativo sin pila Python explicativa.
**Limite medido:** `faulthandler.register()` **no existe en Windows**.
**Eleccion de N (BA12):** percentil 99 de duracion de tests + margen, salido de un barrido --
no a ojo. Hay un test documentado de **162 s** que impide elegir N ingenuamente. Si sale
meseta, declarar que la cota superior queda abierta.

### C3-ENTORNO -- muestreo periodico [EL MAS ESPECULATIVO, NO PROBADO]

Hoy `environment_at_start` es **una foto unica al arrancar** (22 de 500 filas): no muestra
TENDENCIA. **BA12 avisa: "barato no es sinonimo de informativo"** -- sin un escenario donde la
tendencia prediga la muerte, es complejidad sin senal. **BA05:** el hilo demonio muere con el
proceso; la escritura final debe hacerla el supervisor (C6), no el hilo.

---

## 3. VISUALIZACION EN CHAT [PROTOTIPO, NO codigo del repo]

Render del NDJSON a markdown: barra, contadores, top-lentos, fallos y **el test en vuelo**.
Salida REAL de una corrida matada a los 3 s:

    barra 66.7%   4/6 tests
    passed 3 | failed 1 | skipped 0 | 1s
    fallos: tests/test_demo.py::test_e
    > EN VUELO / ULTIMO ANTES DE MORIR: tests/test_demo.py::test_f

Consultable durante la corrida y post-mortem, desde cualquier sesion, porque vive en disco.
**Falta decidir donde vive y si se cablea como skill.**

---

## 4. DoD (invariantes, ampliados por el bucle)

1. Matar una corrida viva -> el heartbeat da `(nodeid, fase)` del punto de muerte.
2. Matar durante la coleccion -> existe el marcador de coleccion. **BA16-A1: con
   `collection_finish` este DoD es INPASABLE** (solo corre al ACABAR de recolectar); hay que
   emitir tambien un marcador de arranque en `pytest_collection` o al importar el conftest.
3. **Integridad del artefacto (BA05):** tras matar, el NDJSON es parseable linea a linea, sin
   truncado, y termina en newline. **PROBADO: 566 bytes, 6/6 lineas parseables, 0 truncadas.**
4. Dos corridas vivas -> cada una deja su fichero integro (path por PID), sin entrelazar.
5. Colgar un test mas de N s -> volcado de stack con la linea exacta.
6. El exit code crudo queda registrado sin normalizar.
7. **Fail-open (BA05, BA12):** una escritura fallida del hook (disco lleno, permisos, ruta
   mala) **no cambia el resultado de pytest**. Probar con disco/permisos forzados.
8. Delta de duracion sobre la suite completa medido y declarado antes de adoptar.

## 5. RIESGOS DECLARADOS

- **Los hooks pueden ser una NUEVA causa de muerte** (BA12: heisenbugs). Van en try/except
  propio que nunca propaga. Es el riesgo mas serio: instrumentar una suite que ya muere sola.
- **I/O**: 4 escrituras pequenas x 6495 tests. `fsync()` solo en `collection_finish` y cada N;
  un `fsync` por test debe barrerse contra la mediana de **704 s** ANTES de adoptar.
- **C6 no cierra la atribucion**: sin auditoria 4688/4689 (admin) no se nombra siempre al autor
  de un `TerminateProcess` externo. **Reduce el espacio causal, no lo cierra.**
- Ninguno sustituye a `last-run.log`: son canales nuevos, append-only.

## 6. LO QUE NO SE PROPONE

WER/Event Viewer (ya consultado: **0 eventos** en la ventana de las muertes -- ausencia
informativa, no canal). `pytest-timeout` (dependencia nueva; C2 cubre el caso sin ella).
Optimizar tests concretos, xdist, umbral de RAM: refutados o con dueno ajeno.
**Ninguna de las 4 hipotesis prohibidas se repropone** (confirmado por las 3 lentes).
