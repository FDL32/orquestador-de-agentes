# DEC-079A-001: lectura compartida del scorecard rotado (activo+archivados), enmendada por alcance de lectores

**Ticket:** WOT-2026-079a
**Fecha:** 2026-09-29 (decision original); enmendada 2026-10-02.
**Estado:** **DECIDED**
**Decidido por:** Usuario (decision original adoptada al redactar `T-079A-001`, 2026-09-29; enmienda
aprobada en chat, 2026-10-02, tras bucle real de 5 lentes sobre la propuesta v2).
**Origen de la decision original:** `T-079A-001` (`<MOTOR>/.agent/planning/ticket_contracts.md`),
seccion "Decisiones: TOMADAS".
**Origen de la enmienda:** `<DESTINO>/.agent/planning/PROPUESTA_079a_alcance_y_lectores_2026-10-01.md`
(bucle adversarial real, forma `DBL-5`: codex BA05 + nan BA11/BA13/BA25/BA10, 2026-10-01).

---

## DECISION 1 (original, T-079A-001): funcion de union COMPARTIDA, opcion (b)

Se ADOPTA la opcion (b): una funcion de union activo+archivados COMPARTIDA entre
`ensemble_dispatch.py` y `phase_value_report.py`. Se RECHAZA que cada uno implemente su propia
lectura duplicada (opcion a). El Forbidden Surface de `WOT-2026-055o` (el dashboard) se amplia
UNICAMENTE para permitir importar esa funcion compartida; el resto de `ensemble_dispatch.py` sigue
prohibido para ese modulo.

La funcion vive en `ensemble_dispatch.py` con nombre y firma FIJADOS:
`read_scorecard_unified(project_root: Path) -> Iterator[dict]` (D7 de `T-079A-001`).

## DECISION 2 (enmienda 2026-10-02): alcance ampliado a los lectores fuera del contrato original

**Hallazgo que motiva la enmienda:** `T-079A-001` (frozen) no menciona `check_loop_execution.py` ni
`pool_permanence_metric.py`, pero ambos importan `_read_scorecard` (lectura activo-solo). Tras la
PRIMERA rotacion, estos dos lectores verian 0 filas para rondas ya archivadas: el guard de gobierno
(`check_loop_execution`) daria FALSO ROJO ("0 rondas") sobre commits legitimamente gobernados.

Se ADOPTA la **opcion C** de la propuesta v2 (4 de 5 lentes: ADOPTAR CON CAMBIOS; 1 lente RECHAZAR
con dos bloqueos refutados por medicion, ver seccion 6 de la propuesta): rotar SOLO
`scorecard.jsonl` y reescribir `_read_scorecard` sobre la lectura unificada, en vez de (A) unificar
los 4 ficheros JSONL o (B) aplazar el ticket.

Enmiendas concretas al contrato `T-079A-001` (detalle completo en la propuesta v2, secciones 3 y 6;
este DEC fija la decision de producto, no repite el detalle tecnico):

1. **Alcance de rotacion (D1):** solo `scorecard.jsonl` rota; umbral en BYTES (`10 * 1024 * 1024`),
   no "10 MB" ambiguo. `emitted_nonces.jsonl`, `fallback_events.jsonl` y
   `adversarial_findings_raw.jsonl` NO rotan; si superan el mismo umbral, `ensemble_dispatch.py
   status` emite un WARN por stderr nombrando el fichero y el ticket dueno, sin cambiar exit code.
2. **Lector unificado (D5/D7):** `read_scorecard_unified` se extiende con una politica por tipo de
   fichero: el ACTIVO mantiene semantica estricta (lanza ante linea invalida, como hoy); los
   ARCHIVADOS (inmutables) son SIEMPRE tolerantes (cuentan y saltan lineas invalidas con WARN
   nombrado) porque no se pueden reparar y un lector estricto ahi rompería el guard para siempre
   ante un archivado con una linea truncada por un crash previo.
3. **`sha` (nuevo D10):** sin archivados, `sha == sha256(bytes del activo)` (identico a hoy, sin
   cambio de comportamiento). Con archivados, se combina por orden lexicografico de nombre (NUNCA
   por `mtime` ni orden de directorio), activo al final.
4. **Lectura consistente (nuevo D11):** protocolo de lectura con relistado y reintento (hasta 3,
   50/100/200 ms) ante una rotacion concurrente; si no estabiliza, lanza
   `ScorecardRotationRaceError` (nunca un exit code nuevo del guard).
5. **Prueba por la ruta de produccion (nuevo D12):** fixture con repo temporal propio, rotacion
   forzada de un umbral bajo, y verificacion de que `check_loop_execution.py`, antes y despues de
   rotar, da el MISMO veredicto sobre el mismo commit. Mutacion: revertir a lectura activo-solo debe
   poner esa verificacion en rojo.
6. **Medicion de coste (nuevo D13):** se publica el tiempo de `check_loop_execution` con ~10 MiB
   archivados + ~5 MiB activo en `execution_log.md`; no se fija umbral de rendimiento en este
   ticket.
7. **FLT sin cambio de lista, aclarado:** `scripts/ensemble_dispatch.py` y
   `scripts/phase_value_report.py` (y sus tests) ya estaban en el FLT original; ambos se EDITAN.
   `check_loop_execution.py` y `pool_permanence_metric.py` pasan a "Read/inspect only" (consumidores
   a NO romper, no a modificar).
8. **Forbidden Surfaces ampliadas:** se prohibe ademas cambiar el formato de las filas y el nombre
   canonico `scorecard.jsonl`.

**Rechazado, con medicion** (seccion 6 de la propuesta v2; no se repiten aqui los detalles, constan
en el documento): la objecion de que el `sha` rompe correlacion con nonces (la correlacion es por
`commit_sha`/`loop_id`, no por hash); la objecion de que "strict es incompatible con rotacion"
(las lineas invalidas vienen de un escritor bajo lock, no del rename); la propuesta de rotar tambien
`emitted_nonces.jsonl` (285 KB, es el ledger que ata el guard, no se toca).

---

## Impacto en el contrato formal T-079A-001

Esta decision ENMIENDA (no sustituye) `T-079A-001`: las Decisiones TOMADAS originales (funcion
compartida, nombre/firma de `read_scorecard_unified`) se mantienen; se amplia el DoD con D10-D13 de
la propuesta v2, se actualiza D1 a unidades en bytes y alcance acotado al scorecard, se actualiza
D5/D7 con la politica activo-estricto/archivados-tolerante, y se mueven `check_loop_execution.py` y
`pool_permanence_metric.py` de "fuera de alcance" a "Read/inspect only" (sin editarlos). El contrato
se re-congela con estas enmiendas antes de activar el ticket (ver work_plan derivado).
