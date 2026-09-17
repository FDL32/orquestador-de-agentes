> # ⚠ DOCUMENTO RECHAZADO -- NO CITAR COMO EVIDENCIA
>
> Sus versiones v1, v2 y v3 fueron **las tres rechazadas** por bucle adversarial (11 lentes,
> 3 rondas). Defectos NO corregidos que sobreviven en el texto:
> - **§0/§2 contienen un percentil INVALIDO**: calculado sobre 157 corridas con **107
>   denominadores distintos (5678-6631 passed)**. Compara duracion bruta de corridas que
>   ejecutan hasta 953 tests distintos.
> - La serie ms/test normaliza por un denominador que depende del estado del arbol.
>
> **Se conserva por dos motivos, no como conclusion:** (1) su §4 (defectos de mecanismo) SI
> sobrevivio a las 3 rondas y 3 de sus items estan confirmados por experimento; (2) el
> historial de auditoria es util.
>
> **El documento vigente es `plan_instrumentacion_suite_20260917.md`.**

# ANALISIS v3: degradacion de la suite -- tras DOS rondas de bucle adversarial

Fecha: 2026-09-17. Motor `_dev` HEAD `5c2eefc`. Autor: Manager (review de WOT-2026-070e).
Estado: **DIAGNOSTICO solido + PROPUESTAS aun NO adoptables.** Ningun commit de codigo productivo.

Historial de auditoria:
- **v1** -> L1102 (nonce `88e6a0c9...`), 4 lentes. **RECHAZADA por unanimidad**: correlacion
  vendida como causa.
- **v2** -> L1103 (nonce `72e5d8be...`), 3 lentes validas (BA05 codex, BA11 qwen3.6, BA12 mimo;
  BA06 **MUDA**, 2 bytes). **2 de 3: NO adoptable.** `check_loop_execution` OK 4/4.
- **v3** (esta) cierra los 3 puntos abiertos y anade la medicion que los decide (§0).

---

## 0. LA MEDICION QUE CAMBIA EL VEREDICTO (nueva en v3)

La corrida limpia de hoy tardo **909.29 s**. Contra las 157 corridas completas del historico:

| | valor |
|---|---|
| mediana historica | **704 s** |
| p25 / p75 | 565 s / 1111 s |
| corrida limpia (arbol a 28 450 entradas) | **909 s = percentil 64** |

**La limpieza NO acelero la suite.** Se vaciaron 106 690 entradas (76% del arbol) y la corrida
quedo POR ENCIMA de la mediana historica.

La prediccion natural de la hipotesis del sandbox era que un arbol 9.6x mas barato de enumerar
diera una corrida rapida. **No ocurrio.**

**PERO ESTA COMPARACION NO ES VALIDA, y la ronda 3 la tumbo (BA05-H1 y BA12-H1, unanime).**
Medido al verificar el hallazgo: las 157 corridas del historico tienen **107 denominadores
DISTINTOS**, de **5678 a 6631 passed** -- 953 tests de diferencia. Comparar `duration_s` bruta
entre corridas que ejecutan hasta 953 tests distintos es **peras con manzanas**, y es el MISMO
vicio que §1.3 denuncia. A eso se suma que no se controla maquina, carga ni configuracion.

**CONSECUENCIA: §0 se RETIRA como argumento.** El dato (909 s) queda como **registro fechado de
una corrida**, no como test de la hipotesis. La hipotesis del sandbox NO se degrada por esta via:
vuelve a **NO DEMOSTRADA, sin test valido todavia**. Disenar ese test es P-0, y su criterio
actual (p25 historico) hereda el mismo vicio -- ver P-0.

Documento hermano (NO repetir su trabajo): `debug_forense_suites_20260917.md` cierra la CLASE
de muerte y refuta 4 hipotesis, que siguen PROHIBIDAS.

---

## 1. LO QUE SE MIDIO HOY, Y ES NUEVO

### 1.1 Dos suites `--level all` VIVAS a la vez (capturado antes de matarlas)
Evidencia completa en `tests/sandbox/evidencia_dos_suites_20260917.md`.

| | Cadena A | Cadena B |
|---|---|---|
| wrapper | 19524 (`--level all --force-unlock`) | 27592 (`--level all`) |
| worker | 40868 (1112 s CPU) | 45232 (1115 s CPU) |
| arranco | 17:19:55 | 17:18:34 |
| `run_history` decia | `status: started` | **`aborted` (fila de 15:18:35)** |
| realidad medida | viva | **VIVA, ~90 min ejecutandose** |

`--force-unlock` (`acquire_lock:672-684`) borra el lock **aunque `is_pid_running` sea True**.
**LIMITE (BA06-H1):** que A pisara el lock de B esta MEDIDO; que eso CAUSARA la fila `aborted`
de B es INFERENCIA -- el escritor de esa fila no es el camino instrumentado de Pieza B (no
lleva sus 4 campos), asi que **el autor de la fila queda NO IDENTIFICADO**.

### 1.2 Mutation-verify involuntaria al matarlas: 3 defectos CONFIRMADOS en vivo
`Stop-Process -Force` sobre las 6 cadenas. Resultado medido:
- `last-run.log`: **intacto, 1372 bytes, mtime 17:05** (un focal de 15 tests) tras ~19 min de
  CPU por corrida. El `finally` de `stream_pytest:975` **no corrio**. Cero lineas de que test
  se ejecutaba.
- Pieza B escribio la fila `aborted` de la corrida muerta **sin `reconciled_at`,
  `reconciled_reason`, `lock_pid` ni `assumed_dead`**. Predicho por el censo 8/0 y cumplido.
- `pytest.lock` sobrevivio huerfano a su dueno muerto.

Esto ya NO es lectura de codigo: es un experimento con resultado predicho.

### 1.3 La limpieza del arbol, medida
| | antes | despues |
|---|---|---|
| `tests/sandbox` | 106 690 entradas / 162 MB | **21 / 176 KB** |
| `PROJECT_ROOT` | 120 516 entradas | **28 450** |
| enumerar `PROJECT_ROOT` | 3.45 s | **0.36 s** (x9.6) |

### 1.4 La corrida limpia: VERDE
`exit_code 0`, **6445 passed, 50 skipped, 909.29 s**, `level=all`, `args_mode=default_discovery`,
`tested_commit_sha == HEAD (5c2eefc)`. Sandbox autolimpiado al terminar (0 sesiones).

**Y su denominador RESUELVE una anomalia:** `pytest --collect-only` da **6495 = 6445 + 50**.
Consistente. Las corridas anteriores del dia daban **6631** porque el arbol estaba CONTAMINADO:
hay tests parametrizados sobre ficheros del arbol, asi que la basura **INFLABA el denominador**.
Predicho por `obs-suite-delta-needs-collect-only-not-def-test-count`.
**Corolario duro:** comparar `passed` -- o cualquier metrica normalizada por el, como ms/test --
entre corridas con arboles distintos NO es valido. La serie de v1/v2 arrastra ese sesgo.

### 1.4 La acumulacion de huerfanos es un fenomeno de JUNIO, no de hoy
`conftest.py:156-178` (docstring de `_purge_orphan_session_dirs`), literal: *"566 observed at
013d baseline, 575 at 013i"*. La acumulacion esta documentada desde **WOT-2026-013d (junio
2026)**, tres meses ANTES de las corridas concurrentes de hoy. **Esto cierra por anterioridad la
hipotesis de v1** (no-purga mutua): el fenomeno precede a su supuesta causa y ya tiene dueno
historico.

---

## 2. LA SERIE TEMPORAL -- corregida

La v1 mostro 12 dias (n=73) declarando un pool de 158: **omitio el 54% sin decirlo** (BA06-H2).
Pool real: **157 corridas completas en 32 dias**.

Nota de metodo (hallazgo nuevo): **137 de 157 filas NO tienen `started_at`**, solo
`finished_at`. El campo se anadio el **2026-09-14T23:23** (`git log -S`: `d8fd3f9` /
WOT-2026-069g). Cualquier agregacion por dia DEBE usar fallback a `finished_at` o pierde el 87%.

Picos de ms/test sobre los 32 dias:

| dia | n | ms/test | max dur |
|---|---|---|---|
| 2026-08-19 | 2 | **78.5** (minimo) | 490 s |
| 2026-08-31 | 3 | **487.5** | 3068 s |
| 2026-09-07 | 15 | 93.3 | 991 s |
| 2026-09-14 | 5 | **554.7** | 3980 s |
| 2026-09-16 | 5 | 165.1 | 4643 s |
| 2026-09-17 | 5 | 137.9 | 1330 s |

**CORRECCION CLAVE (BA06-H3):** la v1 afirmo "suelo estable de agosto ~78-93" y un "escalon el
14-sep". **FALSO.** El **2026-08-31 ya dio 487.5 ms/test** -- x5.2 sobre el minimo y ANTES de
toda la telemetria de septiembre. Hay al menos DOS picos comparables (31-ago, 14-sep) separados
por una recuperacion. El 14-sep no es un escalon: es el segundo pico de un patron INTERMITENTE.

**Lo que la serie sostiene:** duracion muy variable (rango 406-4643 s), intermitente, con picos
recurrentes y recuperaciones. **Lo que NO sostiene:** una fecha de inicio de la degradacion, ni
una tendencia monotona, ni atribucion a un cambio concreto.

**ADVERTENCIA QUE INVALIDA PARCIALMENTE ESTA TABLA (v3):** ms/test normaliza por `passed`, y §1.4
establece que `passed` **depende del estado del arbol**. Las corridas de arbol sucio tienen el
denominador INFLADO, lo que **deprime artificialmente su ms/test**. **La ronda 3 (BA12-H2) senalo que conservar una tabla
declarada invalida y seguir extrayendo de ella la conclusion "la duracion es variable" es querer
las dos cosas.** Aceptado: la tabla queda como **REGISTRO HISTORICO, no como evidencia**. La
variabilidad de la duracion se sostiene por el rango bruto de `duration_s` (406-4643 s), que NO
depende del denominador, no por esta tabla.

### 2.1 No es el codigo (esto SI se sostiene)
Mismo `tested_commit_sha`, duraciones distintas: `048d400` 711..1420 s (**x2.00**), `0a125d6`
626..1145 s, `bda821e` 604..947 s. Con el codigo constante por construccion, la varianza es
ENTORNO. **Matiz (BA05):** esto prueba que el entorno contribuye, NO que el codigo sea
irrelevante -- un cambio de codigo puede alterar la SENSIBILIDAD al entorno.

Censo de commits sobre infraestructura de test (2026-08-14 en adelante): `3e3387d`, `d8fd3f9`,
`e2d10b5` (telemetria y metadatos), `34eb70c`, `38aa857`. **Ninguno anade carga por test que
explique los picos.** Limite (BA05): el censo cubre 4 ficheros; no descarta dependencias, SO,
datos ni procesos externos.

---

## 3. ESTADO DE LA HIPOTESIS DEL SANDBOX

La v1 titulaba esta seccion "el arbol contaminado (cadena causal cerrada)". Las 4 lentes lo
marcaron BLOCKER: contradecia la propia seccion de limites de la v1 y la autoridad del forense
(*"LA CAUSA SIGUE SIN DETERMINAR"*). **Se degrada a HIPOTESIS.**

### 3.1 Lo que esta MEDIDO
- `tests/sandbox` llego a 92 049-106 690 entradas = **76% del arbol** del repo.
- Enumerarlo costaba 3.15 s; tras limpiar, 0.36 s el arbol entero.
- `conftest.py:210-212` redirige `tempfile.tempdir` y `TMPDIR` **dentro del arbol del repo**.
- `conftest.py:186` declara *"never purge a living process's sandbox"* (WOT-2026-020p).
- El denominador de tests **depende del contenido del arbol** (6631 sucio vs 6495 limpio).

### 3.2 Lo que esta REFUTADO -- de mi propia hipotesis de la v1
La v1 sostuvo que el mecanismo era la **no-purga mutua entre dos corridas vivas**.
**MEDICION QUE LO REFUTA:** la corrida limpia, corriendo SOLA, genero **1319 factories en 2
minutos**. La acumulacion es el RITMO NORMAL de la suite, no un efecto de la concurrencia
(BA06-H6 lo predijo por aritmetica: el mecanismo explicaria ~7k entradas, no 92 049).

**Y la segunda pata tambien cae:** al terminar limpiamente, el sandbox queda a **0 sesiones**.
El teardown SI limpia. Luego las 106 690 entradas son **COMPATIBLES CON** basura de corridas
**MUERTAS** que nunca ejecutaron su teardown -- atribucion PROVISIONAL, no demostrada: no se
identifico el origen de cada entrada del arbol historico (BA05 ronda 2).

**Reformulacion (la unica que los datos permiten):** las muertes dejan basura; la basura encarece
el arbol y falsea el denominador; un arbol mas caro puede favorecer mas muertes. Es un bucle
PLAUSIBLE y NO DEMOSTRADO -- no se sabe que lo inicia, y la causa de la muerte sigue abierta.

### 3.3 La prediccion falsable, y su primer test (reescrita en v3)
BA11-H5 senalo que la v2 trataba la hipotesis como si ya tuviera consecuencias establecidas.
Reformulada como prediccion que puede FALLAR:

> **SI** el coste del arbol fuera un driver material de la duracion, **ENTONCES** una corrida
> sobre un arbol 9.6x mas barato de enumerar deberia (a) caer por debajo de la mediana historica
> y (b) reducir la DISPERSION entre corridas.

**Primer resultado (n=1): (a) FALLA** -- 909 s = percentil 64, por encima de la mediana de 704 s.
**(b) no es medible con n=1.** Una prediccion incumplida con un solo punto no refuta, pero
retira a la hipotesis el rango de explicacion preferente.

**Contradiccion de v1 ya resuelta:** la varianza x2.00 se usaba a la vez como SENAL del sandbox y
como RUIDO contra el que discriminar. En v3 es **solo ruido de entorno**; el discriminante es la
prediccion de arriba.

---

## 4. QUE SE METIO, QUE SE QUITO, Y QUE NO FUNCIONA

### 4.1 Metido y NO funcionando
| Pieza | Promete | Hace |
|---|---|---|
| **Pieza B 062e** (`_reconcile_dead_run:555-631`) | abortos con forense | **0 de 8** filas con sus 4 campos. **Re-confirmado hoy en vivo.** Es barrendero RETROSPECTIVO: corre al arrancar la SIGUIENTE (`:1535`) y exige `status=="started"` (`:573`). |
| **`--force-unlock`** (`:672-684`) | limpiar locks huerfanos | borra el lock con el PID **VIVO**. |
| **`status: finished`** | corrida completa | **48 de 475** filas con `passed: None` o exit_code fuera de 0..5. |
| **`last-run.log`** (`:975`) | salida de la corrida | **una sola** `write_text` en el `finally`; muerte sin desenrollar pila = log perdido. **Confirmado hoy.** |
| **`_purge_orphan_sessions`** (`conftest.py:156`) | limpiar huerfanos | funciona al terminar limpio; **no cubre lo que dejan las corridas muertas**. |

### 4.2 Nunca cableado / bloque muerto
- **`pytest-timeout` NO esta instalado.** Ningun timeout sobre `process.wait()` de pytest (`:966`).
- **`[tool.pytest.ini_options]` de `pyproject.toml` es BLOQUE MUERTO**: `pytest.ini` gana, luego
  `--cov=src --cov-report=term-missing` y `asyncio_mode="auto"` **no se aplican**. (Impacto no
  medido -- BA12-H6.)
- **`debug_suite_watchdog.py` existe y NO esta cableado**; su docstring declara *"No nombra al
  asesino"*.
- **xdist:** el campo `xdist` **NO existe en `run_history.jsonl`** (medido: 0 de 500 filas lo
  llevan; solo esta en `last-run.json`). La afirmacion "0 de 177 corridas con
  `xdist.enabled=true`" que traia la v2 **NO es verificable en ese artefacto** y se retira.
  `resolve_xdist` bloquea `level != unit` por diseno, pero el censo historico no existe.

---

## 5. PROPUESTAS v3 -- con su bloqueo REAL

### P-A -- Sacar `tempfile.tempdir` FUERA del arbol del repo [SUSTITUYE A P1]
**Las 4 lentes propusieron esto por unanimidad**, y la v1 no lo vio. Hoy `conftest.py:210-212`
mete todo el trabajo temporal DENTRO del repo, que es la superficie COMUN a tres sintomas
observados (arbol inflado, denominador falseado, conflicto de purga). Que sea su RAIZ
causal NO esta demostrado (BA05 ronda 2: causalidad residual).
**Ventaja sobre P1:** evita el conflicto de purga sin tocar la proteccion `:186`, asi que **no
reintroduce** el crash del hermano xdist (WOT-2026-020p). BA12 la llamo la alternativa correcta y reconocio que **escala a cambio arquitectonico**, no parche.
**NO se adopta el "riesgo cero" que dijo BA11 en la ronda 1:** la ronda 2 (BA05) lo refuto por
contradecir los riesgos que este mismo apartado enumera. P-A es la propuesta MENOS auditada.
**REFUERZO QUE NINGUNA LENTE VIO, y sale del codigo:** `conftest.py:173-178` declara que el crash
del hermano xdist ocurre *porque* el tempdir esta redirigido dentro del arbol -- *"the victim's
`TemporaryDirectory()` (tempdir is redirected to SESSION_RUNTIME_ROOT) crashes with
`FileNotFoundError` (WinError 3)"*. Sacarlo fuera **elimina el acoplamiento que crea el crash**,
no solo lo evita. (BA11-H3 afirmo lo contrario; el docstring lo refuta.)

**CENSO DE EXPOSICION -- EJECUTADO en v3 (era el gate que faltaba):**
- Acoplamiento EXPLICITO a `SESSION_RUNTIME_ROOT`/`TEST_RUNTIME_ROOT`: **3 ficheros**
  (`test_prepush_check.py`, `test_sandbox_git_hermeticity.py`, `test_windows_safe_temp_runtime.py`).
  Los dos ultimos ejercitan los helpers de purga: se ADAPTAN, no bloquean.
- Ficheros que usan `tmp_path`: **1145**, pero `tmp_path` es API de pytest y NO asume ubicacion;
  solo romperian si leyeran `tempfile.tempdir`/`TMPDIR` directamente, y **ninguno lo hace**
  (grep: solo `conftest.py`).

**LIMITE DEL METODO, declarado (BA05 y BA12, ronda 3):** el censo es `grep`, y un grep **no ve**
accesos indirectos -- alias, imports de constantes, rutas construidas dinamicamente, variables
intermedias, subprocesos o fixtures. **Un grep es una primera aproximacion, NO una garantia de
completitud**, y presentarlo como "criterio de desbloqueo" lo confundia con una barrera.
**CRITERIO DE DESBLOQUEO (corregido):** el censo por grep da 3 ficheros y **acota, no cierra**.
Cerrarlo exige ejecutar la suite con el tempdir movido y ver que rompe -- un experimento, no un
grep. Ademas falta la DECISION de producto (¿se acepta perder la inspeccion in-situ?), que es
humana.
**RIESGO REAL, NO CERO:** BA05 anadio permisos, aislamiento, colisiones y limpieza en el destino;
ninguno medido.

### P-B -- Escritura incremental de `last-run.log`
Abrir antes del bucle, escribir+`flush()` por linea; `PYTHONUNBUFFERED=1` en el hijo.
**DoD:** matar una corrida viva y comprobar que el log trae el ultimo nodeid. **Hoy falla: lo
acabo de verificar.**
**Riesgos anadidos por las lentes:** no garantiza linea completa ante terminacion forzada
(BA05); con dos corridas vivas el log por-repo se **entrelaza y corrompe** -- el `write_text`
unico al menos deja un ultimo-ganador coherente (BA06-H12). **Mitigacion obligatoria: log por
corrida (sufijo PID), no por repo.** Esto ademas sirve a la investigacion de muertes.

### P-C -- `finished` fail-closed
Si `exit_code not in 0..5` o `passed is None` -> `status: "died"`.
**BLOQUEADO hasta censar consumidores** (BA05, BA11, BA12 coinciden): `pre_handoff_guard`, paso
3.6 del cierre, `collect_system_health`. Cambiar un estado es cambio de contrato de datos.
**CRITERIO DE DESBLOQUEO (exigido por BA05 y BA12 en ronda 2, que senalaron que "BLOQUEADO" a
secas es una ETIQUETA, no un gate):** el censo se considera completo cuando exista un artefacto
`reports/censo_consumidores_status.md` que liste, por cada hit de `grep -rn 'status.*finished'`
sobre `scripts/`, `bus/` y `runtime/`, si compara por igualdad y que hace si el valor cambia.
Mientras ese fichero no exista, P-C no se implementa. **No esta cableado: es una NORMA de este
documento, y como tal depende de que alguien la invoque.**

### P-D -- `--force-unlock` no vence a un PID vivo
**Insuficiente tal cual (BA05, BA13-H13):** la viveza sola no basta -- hay carrera TOCTOU entre
comprobar y borrar, y **el PID puede reciclarse** (precedente que la v1 citaba en otra seccion y
no aplico aqui). Necesita **PID + CreationTime + nombre de proceso**, y adquisicion atomica.
**BLOQUEADO hasta censar call-sites:** si un camino automatico lo pasa, esto lo rompe.

### P-E -- Corregir `WOT-2026-070h` antes de commitear
La fila (escrita, **SIN commitear**) contiene "rearranque en cadena a 2-8 s" y seis duraciones
(43/15/20/17/33/12 min): es la **hipotesis 3 PROHIBIDA**. Quitarlas, declarar la duracion real de
las muertas como DESCONOCIDA, y anadir la confirmacion en vivo de 1.2.
**BA12-H1 lo califica de defecto de PROCESO, y lo acepto:** que la correccion sea correcta no
borra que la violacion existiera en mi borrador.

### P-0 -- El par A/B, rediseñado
La v1 proponia (a) sucio, (b) limpiar, (c) repetir, 3 repeticiones. Las 4 lentes lo declararon
**sin potencia**:
- **intercalar A,B,A,B** -- el diseño por bloques esta confundido por la deriva temporal que la
  propia serie establece (BA05, BA06-H10a);
- **n=3 no discrimina** un x1.6 contra ruido x2.00; fijar criterio estadistico ANTES (BA06-H10b);
- **medir la DISPERSION, no solo la media** -- es el discriminante de §3.3 (BA06-H9);
- **el instrumento es mortal:** `level=all` murio 6/6; si una corrida del probe muere, su
  `duration_s` se censura (BA06-H10c);
- **la rama "sucia" es inestable:** el propio arranque puede purgar huerfanos y borrar lo que
  pretendia medir (BA06-H10c);
- **riesgo forense (BA06-H11): borrar sandboxes DESTRUYE evidencia** de una investigacion
  abierta. Ya ocurrio hoy; se mitigo capturando `evidencia_dos_suites_20260917.md` antes, pero
  **el paso de snapshot debe ser obligatorio** en el protocolo.

**CRITERIO ESTADISTICO, FIJADO ANTES DE MEDIR (lo exigian BA05 y BA11; v2 no lo tenia):**
metrica primaria = mediana de `duration_s`; **la rama limpia debe caer bajo el p25 historico
(565 s) en >=3 de 4 corridas** para sostener la hipotesis. Secundario: la dispersion
(p75-p25) de la rama limpia debe ser menor que la historica (546 s).
**PRIMER PUNTO YA MEDIDO: n=1 -> 909 s (p64). NO cumple el criterio.**

### Lo que NO propongo
NO optimizar tests concretos (062e lo refuta: un test bajo a 1/4 y el total no cambio). NO xdist
(bloqueado para `level != unit`; el "techo 28%" viene de la ficha WOT-2026-069h y es evidencia
fechada de OTRO documento, no un umbral medido aqui). NO tocar el umbral de RAM de Pieza C sin barrido. NO
matar procesos ajenos automaticamente. **NO re-proponer** las 4 hipotesis prohibidas.

---

## 6. ESTADO EPISTEMICO (lo que se sabe y lo que no)

| Afirmacion | Estatus |
|---|---|
| Causa de las muertes | **ABIERTA.** Solo la clase: no desenrolla la pila. |
| La duracion varia x2 a codigo constante | **MEDIDO** -- pero prueba que el entorno CONTRIBUYE, no que el codigo sea irrelevante (ver §2.1). |
| Los 5 defectos de mecanismo (4.1) | **MIXTO.** 3 re-confirmados EN VIVO hoy (log, Pieza B, lock). `pytest-timeout` AUSENTE y `pyproject` como bloque muerto: medidos por probe propio. El censo historico de xdist: **NO verificable en `run_history`** (el campo no existe alli). |
| El denominador depende del arbol | **MEDIDO** (6631 sucio vs 6495 limpio). |
| El sandbox CAUSA la degradacion | **HIPOTESIS DEBILITADA:** su primera prediccion FALLA (limpiar dio 909 s = p64, sobre la mediana de 704 s). n=1. |
| Exposicion de P-A | **CENSADA: 3 ficheros acoplados.** Falta decision humana. |
| La no-purga mutua explica la acumulacion | **REFUTADA por mi propia medicion** (1319/2 min en solitario). |
| Fecha de inicio de la degradacion | **DESCONOCIDA.** Hay picos en ago y sep con recuperaciones. |
| Autor de la fila `aborted` falsa | **NO IDENTIFICADO** (no lleva la firma de Pieza B). |

## 7. CAMBIOS v2 -> v3 (tras la ronda 2: BA05 y BA11 NO adoptable, BA12 si con condiciones)
1. **Nueva §0:** la corrida limpia dio **909 s = percentil 64**; la limpieza NO acelero. Primera
   evidencia direccional CONTRA la hipotesis del sandbox.
2. §3.3 reescrita como **prediccion falsable** con su primer resultado, no como "consecuencia
   util" (BA11-H5).
3. §2 lleva **advertencia que invalida parcialmente su propia tabla**: ms/test normaliza por un
   denominador que depende del arbol.
4. **§1.4 nueva:** la acumulacion es de **junio** (`566 observed at 013d`), lo que cierra la
   hipotesis de v1 por ANTERIORIDAD.
5. P-A: **censo de exposicion EJECUTADO** (3 ficheros acoplados, 1145 `tmp_path` no afectados);
   retirado el "riesgo cero"; anadido el refuerzo del docstring que refuta BA11-H3.
6. P-C y P-D: artefacto de desbloqueo nombrado, y **declarado que son NORMAS, no mecanismos**
   (norma del repo: una barrera solo cuenta si algo la invoca).
7. P-0: **criterio estadistico FIJADO ANTES** (p25 = 565 s, >=3 de 4) + snapshot forense
   obligatorio. Su primer punto ya incumple.
8. Retirada la cifra "0 de 177 corridas xdist": **no censable** -- el campo no existe en
   `run_history.jsonl` (0 de 500 filas).
9. Causalidad residual eliminada: "es la raiz de" -> "es la superficie COMUN a tres sintomas"
   (BA05 y BA11 la cazaron por separado; la correccion de v2 habia sido cosmetica).
10. **P-B identificada como la UNICA propuesta lista para fichar.**
