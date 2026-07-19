# DEC-025H-001: Ancla vs narrativa en la superficie distribuida

**Ticket:** WOT-2026-025h
**Fecha:** 2026-07-19
**Estado:** DECIDED
**Autor:** Orchestrator (vuelo code-only, 2a ola)

## Contexto

`MANIFEST.distribute` declara las entradas que expanden al conjunto de ficheros
que VIAJAN a un `repo_destino`. Muchos de esos ficheros citan tickets
`WOT-2026-*` del dogfooding del propio motor.

> **Snapshot fechado de evidencia (2026-07-19), NO criterio de aceptacion**
> (regla `WOT-2026-024t`): el censo mide hoy `manifest_entries=52`,
> `distributed_files_inspected=143`, `files_skipped=0`. El denominador es el que
> publique el censo en cada corrida; ninguna cifra de este DEC es un DoD.

Citar el ticket que motivo un cambio es PROCEDENCIA legitima y buena practica.
Narrar el dogfooding del motor a un lector ajeno es CONTAMINACION: acopla el
contrato que recibe un proyecto destino al caso propio del motor.

`WOT-2026-025h` declaro dos entregables: (a) esta politica escrita y (b) un censo
re-ejecutable que clasifique cada cita. El entregable (b) se cerro en el commit
`faa0684` (`scripts/census_dogfooding_narrative.py` + sus tests). Este DEC cierra
el entregable (a).

## Decision

### 1. Criterio ancla-vs-narrativa

Una cita a ticket en la superficie distribuida se reduce a **REGLA + ANCLA**:

- **ANCLA (se CONSERVA):** el ID `WOT-2026-XXX` como referencia MINIMA rastreable,
  para que ante una duda se pueda buscar el origen. Ejemplo:
  `# ticket_prefix se preserva (WOT-2026-023i)`.
- **NARRATIVA (se PODA):** la prosa que narra el caso, la sesion o la fecha del
  dogfooding. Esa historia vive en `CHANGELOG`/memoria, no en el contrato que
  recibe un destino ajeno. Ejemplo: el parrafo que narra
  `Caso: --session-close dio exit 0 sin cerrar nada... (2026-07-15)` se resume a
  la regla + su ancla.

Aplica a documentacion Y codigo; la doc distribuida (`AGENTS.md`, `PROJECT.md`)
es donde mas narrativa sobra.

### 2. La clasificacion del censo es una SEÑAL DE REVISION, no una orden de borrado

**Esta es la regla operativa que gobierna a todos los consumidores del censo.**

`scripts/census_dogfooding_narrative.py` es un instrumento READ-ONLY de
diagnostico: **clasifica, nunca poda** (NON-GOAL explicito de 025h). Por tanto:

- Que el censo marque una linea como `NARRATIVA` **NO** significa "borrar esta
  linea". Significa "candidata a revision por el dueño de esa superficie".
- Que la marque `ANCLA` **NO** significa "intocable"; significa "por defecto se
  conserva". La discrecion del dueño de la poda es **ASIMETRICA**: puede
  CONSERVAR de mas (dejar intacta una linea marcada `NARRATIVA`), nunca PODAR de
  mas (eliminar una linea marcada `ANCLA`). Quitar un ancla es un cambio
  normativo y exige su propio ticket, no el juicio de un pase de poda.
- El tramo `LOW_CONFIDENCE` aflora candidatos SIN auto-clasificar, por diseño.

**El clasificador es deliberadamente estructural y line-scoped** (marcador cerrado
de alta precision + anchor-guards). No pretende decidir la FUNCION semantica de
una linea. Un clasificador que intentase distinguir "narrativa que fundamenta una
regla" de "narrativa que solo narra" necesitaria un oraculo semantico: eso queda
PROHIBIDO por este DEC (degeneraria a un analizador estatico, patron WOT-2026-024u).

### 3. Quien decide la poda: el dueño de cada superficie

La poda la aplica **cada consumidor en su superficie acotada**, documento a
documento, con su propio bucle de verificacion sobre el censo ANTES de podar cada
tanda:

- `G-AGENTS-SLIM` (`WOT-2026-036f`) sobre `AGENTS.md`.
- `WOT-2026-036i` sobre el resto de la superficie distribuida.

Ese dueño **PUEDE decidir CONSERVAR una linea que el censo marco `NARRATIVA`**
cuando esa prosa es carga pedagogica del artefacto que la contiene. Esa decision
es un juicio del pase de poda, documentado en su propio ticket -- **NO** una
excepcion mecanica dentro del censo. No se añade al censo una allowlist por
linea/id: seria una lista manual que caduca sola (viola el criterio
invariante-vs-medicion de `WOT-2026-024t`) y quedaria sin cablear.

### 4. Caso canonico de referencia

`skills/_shared/ticket-anti-patterns.md:154`
(`Evidencia origen: WOT-2026-015e D4 -- EXCLUDE_PATTERNS creaba una zona ciega...
se corrigio con git rm --cached + un test de regresion`).

- El censo la clasifica `NARRATIVA` y **esa clasificacion es CORRECTA**: por
  estructura es prosa que narra un incidente pasado (verbo `se corrigio` +
  descripcion del caso), no un ancla desnuda.
- La leccion transferible del anti-patron AP-D04 ("acompaña la exclusion con un
  test de regresion que pruebe que el secreto sigue bloqueando") **ya vive
  completa** en su `Señal de deteccion` (:146) y en su `Ejemplo bueno` (:152, con
  comando literal + fixture + `AKIAIOSFODNN7EXAMPLE`). La linea :154 aporta solo
  la procedencia (`WOT-2026-015e`) mas un detalle incidental (`git rm --cached`).
- Por tanto el dueño de la poda (`WOT-2026-036i`) puede: podarla a REGLA+ANCLA
  conservando el ID (`Ver WOT-2026-015e para el caso origen`), o conservarla
  intacta como procedencia. **Ambas son decisiones legitimas de ESE ticket.** Lo
  que este DEC prohibe es alterar el clasificador o sus tests para que la linea
  deje de aparecer como candidata.

## Consecuencias

- El censo (`faa0684`) y sus tests quedan INTACTOS. No se les añade allowlist ni
  anchor-guard semantico.
- `WOT-2026-036i` queda desbloqueado: ya tiene la vara escrita que le faltaba.
- Un `NARRATIVA` en el censo nunca es, por si solo, evidencia de que haya que
  borrar algo. El conteo del censo es un SNAPSHOT FECHADO de evidencia, jamas un
  criterio de aceptacion (`WOT-2026-024t`).

## Deuda declarada (con dueño y criterio de salida)

El censo NO esta cableado a ningun camino que corra solo: `grep -rl
census_dogfooding_narrative` resuelve solo a su propio test (0 hits en
`.pre-commit-config.yaml` y en `.github/workflows/`). Es hoy un diagnostico
manual -- **una norma, no una barrera**, en el sentido exacto que `AGENTS.md`
define. Cablearlo es superficie nueva, fuera del alcance de 025h.

- **Ticket dueño:** `WOT-2026-038f` (fichado en el backlog del workspace en el
  mismo movimiento que este DEC; sin ese ticket esta deuda se evaporaria, que es
  justo la enfermedad que este DEC denuncia).
- **Criterio de salida binario:** `scripts/check_guard_wiring.py` reconoce
  `census_dogfooding_narrative.py` como CABLEADO (invocado por un camino que
  corre solo), o el ticket declara por escrito **por que NO se cablea** (p.ej.
  "es un instrumento de medicion bajo demanda, no un gate") y lo registra como
  excepcion declarada con dueño.

Hasta entonces, este DEC se declara a si mismo lo que es: **una politica escrita
sin mecanismo automatico**. No se presenta como barrera.
