# PLAN DE INSTRUMENTACION -- cierre de la sesion de analisis de suite

Fecha: 2026-09-17. Motor `_dev` HEAD `5c2eefc`.
Estado: PLAN ADOPTADO tras 4 rondas de bucle adversarial (13 lentes).

**AVISO DE NOMENCLATURA (GLM5.2-H6): `P-B` != `Pieza B`.**
- `Pieza B` = `_reconcile_dead_run()` de WOT-2026-062e (el reconciliador que NO escribe forense).
- `P-B` = la propuesta de escritura incremental del log. Aqui se RENOMBRA a **`INSTR-LOG`**
  para eliminar la colision antes de que llegue a un Builder.

---

## 0. POR QUE SE PARA (motivo CORREGIDO por el bucle)

La recomendacion original decia: *"tres rondas fallidas => no hay dato suficiente"*.
**Las dos lentes finales (GLM5.3-H1 y GLM5.2-H1, independientes) lo refutaron:** las tres
rondas fallaron por errores de INFERENCIA DEL AUTOR, no por escasez de datos. Una lente lo
nombro: *"ha aprendido a HABLAR como un documento auditado, pero no a PENSAR como uno."*

**El motivo VALIDO, que existia y no se uso:** los datos en disco estan AGOTADOS para
discriminar causa -- el forense refuto 4 hipotesis con lo que ya habia, y la observabilidad
esta ROTA y confirmada en vivo. Eso autoriza a INSTRUMENTAR, no a dejar de mirar.

**Se para la guerra de versiones. NO se para la mirada.**

---

## 1. LO QUE SE MIDIO EN ESTE CIERRE (3 probes, todos ejecutados)

### 1.1 Artefactos OS -- el paso de coste cero que el plan omitia (GLM5.2-H1)
```
Get-WinEvent Application 2026-09-17 06:00..18:00, Provider ~ 'Error Reporting|Application Error|Hang'
-> SIN eventos
```
**Lectura:** ausencia informativa, no vacia. Un crash nativo (SIGSEGV, heap corruption)
**habria dejado entrada WER**. Su ausencia es coherente con terminacion externa limpia y
descarta la familia "el interprete revento".

### 1.2 Decodificacion de los 48 exit codes anomalos (GLM5.3-H4) -- HALLAZGO NUEVO
| exit_code | n | decodificado |
|---|---|---|
| 1 | 31 | generico |
| 2 | 6 | generico |
| 4 | 5 | generico |
| **1073807364 = `0x40010004`** | **3** | **`DBG_TERMINATE_PROCESS`: terminado por un DEPURADOR** |
| 4294967295 = `0xFFFFFFFF` | 2 | -1 con signo: salida voluntaria |
| 0 | 1 | con `passed: None` |

Las 3 de `0x40010004` son `level=all`: 2026-08-27, 2026-09-03, 2026-09-06.
**El forense analizo `0xFFFFFFFF` en detalle y NUNCA vio `0x40010004`** (grep sobre sus 250
lineas: 0 hits). Es lo mas cerca de un AUTOR que se ha estado.
**NO es conclusion:** falta identificar que proceso se adjuntaba. Pista viva, no causa.
Contexto declarado: el operador cambio de Cursor a VS Code durante esta misma sesion.

### 1.3 El conteo de muertes NO es verificable (GLM5.2-H4)
Las 9 filas `aborted` carecen de `lock_pid`, `assumed_dead` y `reconciled_reason`.
**Sin esos campos es imposible re-derivar cuales fueron muertes REALES.** Y hay un FANTASMA
PROBADO: la fila de 15:18:35 describe como muerta una corrida cuyo pid 45232 siguio vivo
~90 min. El defecto de Pieza B no solo deja sin forense: **contamina el censo de muertes**.

---

## 2. LO QUE SE FICHA (un ticket, tres piezas -- las lentes rechazaron "solo una")

Ambas lentes finales coincidieron: P-B como eleccion PRIMARIA si, EXCLUSIVA no. El
reconciliador y el chequeo de PID abren canales complementarios por coste menor o igual.

### INSTR-LOG (ex P-B) -- escritura incremental del log
DoD **corregido por GLM5.2-H5** (el original no mordia):
- (a) registrar el **INICIO** de cada test, no solo el final. *Un log que solo escriba finales
  PASA el DoD original y aun asi pierde al culpable: el test que empezo y nunca termino.*
- (b) **marcador de coleccion/startup**: una muerte en fase de coleccion deja el log vacio.
- (c) **path por corrida (sufijo PID)**: con el hecho 3 sin arreglar, la concurrencia es el
  modo OPERATIVO esperado, no un borde. Dos corridas vivas dejan cada una su log integro.
- (d) mutation-verify: matar una corrida viva y comprobar (a). **Hoy FALLA, verificado.**

### INSTR-FORENSE -- que Pieza B escriba sus 4 campos
`reconciled_at`, `reconciled_reason`, `lock_pid`, `assumed_dead`: existen en codigo y no se
pueblan (0 de 9 filas). Abre el canal del **PORQUE**, y ademas **permite re-derivar el conteo
real de muertes** (§1.3). Los campos ya estan escritos: huele a bug pequeno.

### INSTR-LOCK -- `--force-unlock` no vence a un PID vivo
Coste: un check de liveness. **No es una propuesta competidora: es higiene de la evidencia**
que INSTR-LOG debe capturar (GLM5.3-H3). Sin el, el plan despliega un instrumento nuevo y
deja armado el mecanismo confirmado que lo contamina.
Insuficiente por si solo: hay carrera TOCTOU y reciclaje de PID; necesita PID + CreationTime.

---

## 3. LO QUE NO SE IMPLEMENTA (diagnostico, no accion)
- **P-A** (sacar `tempfile.tempdir` del arbol): el censo por grep ACOTA (3 ficheros), no
  cierra -- un grep no ve accesos indirectos. Cerrarlo exige mover el tempdir y ver que rompe:
  un experimento, no un analisis. Ademas requiere decision de producto (perder la inspeccion
  in-situ del sandbox), que es humana.
- **`pytest-timeout`**: dependencia nueva -> requiere aprobacion por regla del repo.
- **Optimizar tests concretos / xdist / umbral de RAM**: refutados o con dueno ajeno.

## 4. TRIPWIRE Y DUENO (GLM5.3-H7)
Un diagnostico sin dueno es letra muerta. **Disparador: la proxima fila `aborted` o
`status: died`.** Accion: leer el log incremental (INSTR-LOG) + los 4 campos (INSTR-FORENSE)
ANTES de relanzar nada. Dueno: el operador de la sesion en que ocurra.

## 5. HIGIENE DOCUMENTAL (GLM5.2-H8)
`analisis_degradacion_suite_20260917.md` contiene v1-v3, **las tres rechazadas por el bucle**,
y su §2 conserva un percentil invalido (calculado sobre 107 denominadores distintos, 5678-6631).
Queda marcado en su cabecera como **RECHAZADO / NO CITAR COMO EVIDENCIA**; se conserva por su
§4 (defectos de mecanismo) y por el historial de auditoria.

## 6. LO QUE SIGUE ABIERTO
- **La causa de las muertes.** Sin determinar. La pista `0x40010004` es nueva y sin verificar.
- **El conteo real de muertes.** No re-derivable hasta INSTR-FORENSE.
- **La degradacion de duracion.** Sin test valido: el de v3 comparaba poblaciones distintas.
