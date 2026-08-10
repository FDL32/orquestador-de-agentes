#!/usr/bin/env python3
r"""Barrera de EJECUCION del bucle de gobierno 1->9->2 (WOT-2026-040b).

El problema que cierra (medido DOS veces)
-----------------------------------------
El bucle adversarial `1->9->2` (CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE) vivia SOLO
en un prompt (`orchestrator_autonomous_ticket_batch.md`): texto que el ejecutor
debe ACORDARSE de honrar. Medido 2026-07-23: un ejecutor commiteo DOS tickets sin
correr el bucle y NINGUN gate lo detuvo -- lo cazo el usuario. 2a ocurrencia
2026-07-24, PEOR: el bucle SI corrio pero DEGRADADO -- 8 instancias del MISMO
modelo en vez de 4 perfiles x 2 ramas. Cero rastro verificable. Es el patron que
AGENTS.md llama "barrera cableada vs norma": una norma depende de que alguien se
acuerde; una barrera corre sola.

Que verifica (y que NO)
-----------------------
Por cada `commit_sha` de ticket que se le pasa, este guard exige en el scorecard
`>=N` receipts de EJECUCION (`event=="ronda"`) de ese SHA con `backend_key`
DISTINTO, un `challenge_nonce` que fue EMITIDO FUERA del ejecutor
(`emitted_nonces.jsonl`) ANTES de la ronda, y CONTENIDO en la respuesta. `N` es
proporcional al `deliverable_type` (un typo/doc no exige 9 lentes).

SUSTANCIA, no solo independencia (WOT-2026-043q)
------------------------------------------------
`WOT-2026-040b` cerro la INDEPENDENCIA (N `backend_key` distintos) pero no la
SUSTANCIA: una lente que NO RESPONDE y una que RESPONDE VACIO eran
INDISTINGUIBLES para esta barrera -- ninguna condicion exigia contenido, asi que
N backends devolviendo cero bytes contaban como bucle EJECUTADO y el guard daba
rc=0. Ahora una ronda muda no cuenta como lente (`is_substantive`) y ademas se
NOMBRA en la salida, distinguiendo TRANSPORTE (no hubo llamada) de BACKEND (hubo
llamada y respondio vacio), porque exigen accion distinta.

El caso real que lo origino: un `service_tier` global invalido mataba a codex-cli
SIN emitir veredicto y SIN consumir tokens -- no llegaba a haber llamada-- y el
bucle se contabilizaba igual.

Adjudicado por el propio bucle 1->9->2 sobre esta cuestion de diseño (Codex final,
2026-07-24):
- El vector que MUERDE de verdad es "bucle DEGRADADO" (N llamadas al mismo modelo):
  lo cierra el recuento de `backend_key` DISTINTOS, no el nonce. El nonce es
  SECUNDARIO -- fuerza una ceremonia previa auditable y evita que el scorecard
  parezca evidencia sin challenge emitido.
- La independencia es OPERACIONAL, no criptografica: en dogfooding el mismo agente
  puede emitir y ejecutar. Por eso NO probamos "otro actor"; probamos "paso previo
  separado, no derivable de los receipts". El `issuer_backend_key` del emisor NO
  cuenta como lente ejecutora para satisfacer N, y la emision debe ser ANTERIOR a
  los receipts (`issued_before_ts < receipt.ts`).
- Se EXIGE el join DUAL: nonce emitido fuera Y copiado dentro de cada receipt. Si
  viviera solo fuera, el join por commit probaria que hubo UN nonce, no que cada
  backend respondio a ESE challenge.

NON-GOALS (STOP de degeneracion, WOT-2026-024u/025c honrado en vivo)
--------------------------------------------------------------------
Este guard NO juzga la CALIDAD semantica del review (imposible sin oraculo, es
025f-shaped). NO descubre por su cuenta que commits pertenecen al vuelo ni deriva
N adivinando: recibe `commit_sha` y `min_distinct_backends` como ENTRADAS. NO
tokeniza prosa ni analiza invocaciones. Es un CONTADOR estructural con un join,
nada mas: por eso cabe entero y no degenera en un subsistema.

Rechazos explicitos (fail-closed)
---------------------------------
- Una fila con `event != "ronda"` (p.ej. `adjudicate`) NO cuenta como ejecucion:
  `adjudicate` appendea campos controlados por CLI (`--evidence`,
  `--adjudicator-backend`), es fabricable a mano. Solo `event=="ronda"` -- que
  escribe `_record_round` tras un `send_to_profile` real-- prueba ejecucion.
- Un receipt cuyo `challenge_nonce` no esta en `emitted_nonces.jsonl` (para ese
  commit+loop) se DESCARTA: es un nonce fabricado.
- Un receipt cuyo nonce se emitio DESPUES de la ronda se descarta (la ceremonia
  previa no ocurrio).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(MOTOR_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from ensemble_dispatch import (  # noqa: E402
    _read_scorecard,
    read_emitted_nonces,
)


# N minimo de lentes distintas por deliverable_type. El 1->9->2 canonico son 9
# lentes (4 perfiles x 2 ramas + 1 lector-FS) pero como MUCHO 6 backend_key
# DISTINTOS (BA01,BA05,BA10-13). Exigir 9 backends distintos parte de premisa
# falsa (solo hay 6): el minimo real de INDEPENDENCIA es "no todo el mismo
# modelo". Rigor proporcional: un typo no exige la ceremonia completa.
DEFAULT_MIN_DISTINCT_BACKENDS = {
    "code": 4,
    "mixed": 4,
    "analysis": 3,
    "research": 2,
    "documentation": 2,
}
# Fallback conservador cuando el deliverable_type es desconocido: el mas estricto.
FALLBACK_MIN_DISTINCT = 4


def min_distinct_for(deliverable_type: str | None) -> int:
    """N minimo de backend_key distintos para un deliverable_type.

    Un tipo desconocido cae al fallback ESTRICTO (fail-closed): mejor exigir de
    mas y que el orquestador declare el tipo, que colar un bucle degradado.
    """
    if not deliverable_type:
        return FALLBACK_MIN_DISTINCT
    return DEFAULT_MIN_DISTINCT_BACKENDS.get(
        deliverable_type.strip().lower(), FALLBACK_MIN_DISTINCT
    )


# Marcador que `_record_round` escribe en `evidencia` cuando el backend no
# devolvio texto. Es el observable HISTORICO de una ronda muda: existe en el
# scorecard desde antes de `output_chars`, y por eso el criterio lo acepta como
# senal equivalente en filas antiguas.
EMPTY_EVIDENCIA_MARKER = "(respuesta vacia)"

# Invisibles Unicode que `str.strip()` NO elimina y que, solos, no son una
# aportacion: zero-width space/non-joiner/joiner, BOM/zero-width no-break y el
# espacio ideografico. No es un umbral de longitud (ver `is_substantive`): es la
# misma nocion de "vacio" que ya aplica `_record_round`, extendida a los
# caracteres que su `.strip()` deja pasar.
_INVISIBLE_CHARS = "".join(
    (
        # escapes, no literales: en el fuente son indistinguibles de un espacio
        # normal y ruff los marca como ambiguos (RUF001).
        chr(0x200B),  # zero-width space
        chr(0x200C),  # zero-width non-joiner
        chr(0x200D),  # zero-width joiner
        chr(0xFEFF),  # zero-width no-break space (BOM)
        chr(0x3000),  # ideographic space
        chr(0x00A0),  # no-break space
    )
)


def is_substantive(row: dict) -> bool:
    """True sii la ronda APORTO contenido. Falso sii corrio y callo.

    DESVIACION DECLARADA DEL DoD (b) de WOT-2026-043q. El DoD pedia "umbral =
    constante declarada, justificada con BARRIDO sobre el scorecard REAL,
    publicando AMBOS bordes de la meseta". **Aqui NO hay umbral de longitud, y la
    desviacion es deliberada**: el barrido se hizo y REFUTO la premisa del DoD.
    `evidencia` -- el unico campo de tamano que existia-- se guarda truncada a 500
    caracteres (249 de 472 rondas historicas caen EXACTAMENTE en el tope) y una
    respuesta sustantiva almacenada fuera de linea ocupa ~46 caracteres
    ("raw/router__lectura__dif__qwen3.6.json (2134c)"): cualquier umbral sobre ese
    campo marcaria muda una ronda de 2134 caracteres, un falso positivo POR
    CONSTRUCCION. Por eso se anadio `output_chars` (medida EXACTA) y el criterio
    es `== 0`, que es una MEDICION, no una constante ajustable a ojo.

    LIMITE CONOCIDO de esa decision (declarado, no descubierto luego): una
    respuesta de RUIDO no vacia ("ok", "si") cuenta como sustantiva. Filtrar eso
    es juzgar CALIDAD SEMANTICA, que es competencia del adjudicador
    (`failure_mode`, que este criterio ya respeta) y que en el gate reproduciria
    el muro de WOT-2026-025c. Si algun dia se quiere un `MIN_OUTPUT_CHARS`, ahora
    SI hay con que barrerlo: `output_chars` empieza a acumular datos desde este
    ticket -- antes no existia el dato, asi que el barrido pedido por el DoD era
    literalmente imposible sobre el historico.

    Criterio (fail-OPEN ante ausencia de dato, a proposito):
    - `output_chars == 0` -> muda.
    - `outcome == "no-aportacion"` -> muda (lo deriva `_record_round` desde el
      texto vacio, y tambien lo fija el filtro de lente).
    - `evidencia == "(respuesta vacia)"` -> muda.
    - Sin ninguna de esas senales -> SUSTANTIVA.

    La ultima clausula es el anti-falso-positivo: las filas anteriores a este
    ticket no llevan `output_chars`, y tratar "campo ausente" como muda
    invalidaria RETROACTIVAMENTE bucles ya corridos -- un gate que hace eso es
    inservible y se le rodea (leccion WOT-2026-042x). Medido sobre el scorecard
    real ANTES de endurecer: de 16 commits con fan-out, solo 2 pierden una lente
    (5990486: 5->4, ea02701: 7->6) y NINGUNO cae por debajo de su min_distinct.
    Por eso este ticket NO necesita constante de cutoff: no hay deuda historica
    que grandfatherear.
    """
    if row.get("output_chars") == 0:
        return False
    if row.get("outcome") == "no-aportacion":
        return False
    evidencia = row.get("evidencia") or ""
    if evidencia.strip() == EMPTY_EVIDENCIA_MARKER:
        return False
    # Respuesta INVISIBLE: `_record_round` mide sobre `text.strip()`, que deja
    # fuera espacios y saltos (una respuesta de solo blancos ya llega con
    # output_chars=0), pero `str.strip()` NO quita los invisibles Unicode --
    # un zero-width space sigue midiendo 1. Sin esto, un backend que devuelve un
    # invisible cuenta como lente que aporta.
    #
    # Solo se aplica cuando la fila TIENE texto: una `evidencia` ausente o vacia
    # es una fila legacy sin ese campo, y tratarla como muda invertiria el
    # fail-OPEN de arriba (lo pinea `test_legacy_rows_without_output_chars_stay_substantive`).
    visible = evidencia.strip(_INVISIBLE_CHARS).strip()
    return bool(visible) or not evidencia.strip()


def diagnose_silence(row: dict) -> str:
    """Por que callo esta ronda, y donde NO hay que buscar.

    ALCANCE REAL, medido antes de escribir esto (479 rondas del scorecard,
    `latency_ms is None` en 0): **una ronda muda con fila SIEMPRE es "hubo llamada
    y la respuesta llego vacia"**. El caso "no hubo llamada" NO puede aparecer
    aqui, porque `run_loop_round` calcula `latency_ms` DESPUES de que
    `send_to_profile` retorne y no captura excepciones: si el transporte falla
    (timeout, credenciales, `service_tier` invalido) la excepcion sube y NO se
    escribe fila ninguna. Medido en vivo el 2026-07-29: un timeout de
    `deepseek-v4-flash` en este mismo vuelo dejo CERO filas.

    Por eso esta funcion NO infiere el transporte desde `latency_ms`: una version
    previa lo hacia y era CODIGO MUERTO con un mensaje que habria mandado al
    humano a revisar credenciales por un fallo de backend. La distincion que pide
    el DoD (e) es REAL, pero su otro lado NO se observa en el scorecard: se
    observa en la AUSENCIA de fila, que es cosa del recuento de lentes
    (`min_distinct`), no de este diagnostico. El mensaje lo dice explicitamente
    para que nadie vuelva a buscar el transporte en la fila equivocada.
    """
    failure_mode = (row.get("failure_mode") or "").strip()
    if failure_mode:
        # La adjudicacion ya clasifico esta ronda; su etiqueta manda sobre
        # cualquier inferencia nuestra.
        return f"respuesta descartada por la adjudicacion: {failure_mode}"
    return (
        "hubo llamada y la respuesta llego VACIA: revisa el BACKEND o el bundle "
        "enviado (tamano, formato). Un fallo de TRANSPORTE no deja fila: se "
        "manifiesta como lente AUSENTE del recuento, no como ronda muda"
    )


def _valid_nonces_for(
    emitted: list[dict], commit_sha: str, loop_id: str | None
) -> dict[str, str]:
    """nonce -> issued_before_ts, para las emisiones de este commit (y loop si se da).

    Solo las emisiones cuyo `commit_sha` casa cuentan: un nonce emitido para OTRO
    commit no autoriza este. Si se pasa `loop_id`, tambien debe casar (un nonce de
    L700 no vale para L800)."""
    valid: dict[str, str] = {}
    for row in emitted:
        if row.get("commit_sha") != commit_sha:
            continue
        if loop_id is not None and row.get("loop_id") not in (None, loop_id):
            continue
        nonce = row.get("challenge_nonce")
        ts = row.get("issued_before_ts") or row.get("ts")
        if nonce and ts:
            # si el mismo nonce se emitio varias veces, quedarse con el mas TEMPRANO
            prev = valid.get(nonce)
            if prev is None or ts < prev:
                valid[nonce] = ts
    return valid


def distinct_execution_backends(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> set[str]:
    """Conjunto de `backend_key` DISTINTOS que ejecutaron una ronda VALIDA de este
    commit. Una ronda es valida sii:

      - `event == "ronda"` (no `adjudicate` ni cualquier otro evento);
      - su `commit_sha` casa (el receipt declara para que commit corrio);
      - lleva un `backend_key` no vacio;
      - su `challenge_nonce` fue emitido FUERA para este commit (y loop, si se da);
      - la emision del nonce es ANTERIOR a la ronda (`issued_before_ts <= ronda.ts`).

    EXCLUSION DEL EMISOR (criterio adjudicado por Codex): el `issuer_backend_key`
    no cuenta como lente ejecutora para N. En dogfooding el mismo backend (BA01 =
    Claude) emite el nonce Y es la lente lector-FS -- SI ejecuta una ronda-- pero
    contarlo inflaria N con una independencia que no existe: quien conoce el
    challenge de antemano no es una lente ciega. Descontamos todos los emisores de
    este commit. Devolver el CONJUNTO (no el conteo) deja que el caller reporte
    QUIENES corrieron.
    """
    return {
        row.get("backend_key")
        for row in structurally_valid_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        )
        if is_substantive(row)
    }


def structurally_valid_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas que pasan todos los filtros ESTRUCTURALES, sin mirar el contenido.

    Es la pasada UNICA que comparten el recuento de lentes y el listado de mudas
    (WOT-2026-043q): la sustancia es el ULTIMO filtro y el unico que las separa,
    asi que duplicar aqui la cadena de filtros haria que las dos vistas
    divergieran en cuanto alguien tocara una sola.
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    issuers = {
        row.get("issuer_backend_key")
        for row in emitted
        if row.get("commit_sha") == commit_sha and row.get("issuer_backend_key")
    }
    rounds: list[dict] = []
    for row in scorecard_rows:
        if row.get("event") != "ronda":
            continue
        if row.get("commit_sha") != commit_sha:
            continue
        bk = row.get("backend_key")
        nonce = row.get("challenge_nonce")
        if not bk or not nonce:
            continue
        if bk in issuers:
            continue  # el emisor no es una lente independiente del challenge
        emitted_ts = valid_nonces.get(nonce)
        if emitted_ts is None:
            continue  # nonce no emitido para este commit: fabricado
        row_ts = row.get("ts")
        if row_ts is not None and emitted_ts > row_ts:
            continue  # el nonce se emitio DESPUES de la ronda: sin ceremonia previa
        rounds.append(row)
    return rounds


def silent_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas estructuralmente validas que NO aportaron contenido: corrieron y callaron.

    Son exactamente las que `distinct_execution_backends` descarta por
    `is_substantive`. Se devuelven aparte para que el CLI pueda NOMBRARLAS: un gate
    que dice "4/4" sin decir quien callo obliga a re-medir a mano, y "conte a mano"
    no es barrera.
    """
    return [
        {
            "backend_key": row.get("backend_key"),
            "diagnosis": diagnose_silence(row),
            "outcome": row.get("outcome"),
            "failure_mode": row.get("failure_mode"),
            "output_chars": row.get("output_chars"),
        }
        for row in structurally_valid_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        )
        if not is_substantive(row)
    ]


def orphan_nonces(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Nonces emitted for this commit that have NO corresponding scorecard rounds.

    WOT-2026-044p (b): distinguishes "no nonce emitted" (no loop happened) from
    "nonce emitted without rounds" (loop happened and was lost). An orphan nonce
    means the loop was DECLARED but never ACCREDITED -- the worst case, because
    work was done and lost without detection.

    Returns a list of dicts with nonce, loop_id, and issued_before_ts for each
    orphan. Empty list means all emitted nonces have at least one round.
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    if not valid_nonces:
        return []

    # Collect all nonces that appear in structurally valid rounds
    rounds_with_nonce: set[str] = set()
    for row in structurally_valid_rounds(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    ):
        nonce = row.get("challenge_nonce")
        if nonce:
            rounds_with_nonce.add(nonce)

    orphans = []
    for nonce, ts in valid_nonces.items():
        if nonce not in rounds_with_nonce:
            # Find the loop_id from the emitted record
            emitted_loop = None
            for row in emitted:
                if row.get("challenge_nonce") == nonce:
                    emitted_loop = row.get("loop_id")
                    break
            orphans.append(
                {
                    "nonce": nonce,
                    "loop_id": emitted_loop,
                    "issued_before_ts": ts,
                    "diagnosis": (
                        "nonce emitido sin rondas: el bucle fue DECLARADO pero nunca "
                        "ACREDITADO -- el trabajo se perdio sin deteccion"
                    ),
                }
            )
    return orphans


def audit_commit(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    min_distinct: int,
    loop_id: str | None = None,
) -> dict:
    """Veredicto para UN commit: {commit_sha, distinct_backends, min_distinct, ok}.

    `ok` es True sii el nº de backend_key distintos con ronda valida alcanza
    `min_distinct`. El commit_sha se compara por prefijo NO: se exige match exacto
    del campo `commit_sha` que el receipt declara (el caller normaliza la longitud).
    """
    backends = distinct_execution_backends(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    )
    return {
        "commit_sha": commit_sha,
        "distinct_backends": sorted(backends),
        "min_distinct": min_distinct,
        "ok": len(backends) >= min_distinct,
        # WOT-2026-043q: rondas que corrieron y callaron. Se reportan SIEMPRE
        # (tambien en verde): una lente muda es una senal aunque el resto alcance
        # el minimo.
        "silent_rounds": silent_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        ),
        # WOT-2026-044p (b): nonces emitidos sin rondas (bucle declarado pero
        # no acreditado). Se reportan SIEMPRE: es la peor senal porque el
        # trabajo se perdio sin deteccion.
        "orphan_nonces": orphan_nonces(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        ),
    }


def audit(
    project_root: Path,
    *,
    commit_shas: list[str],
    deliverable_type: str | None = None,
    min_distinct: int | None = None,
    loop_id: str | None = None,
) -> list[dict]:
    """Veredicto por cada commit del vuelo, leyendo scorecard + emitted del destino.

    Before: `project_root` es el destino-rol con `.agent/runtime/ensemble/`;
        `commit_shas` son los commits de ticket a verificar (entrada, NO descubierta
        aqui). `min_distinct` gana sobre `deliverable_type` si se pasa.
    During: lee scorecard y emitted_nonces (ambos estrictos-UTF8), y para cada
        commit cuenta backend_key distintos con ronda valida.
    After: devuelve la lista de veredictos por commit. NO imprime ni sale; el CLI
        formatea. Sin efectos de escritura.
    """
    n = min_distinct if min_distinct is not None else min_distinct_for(deliverable_type)
    scorecard_rows, _sha = _read_scorecard(project_root)
    emitted = read_emitted_nonces(project_root)
    return [
        audit_commit(
            scorecard_rows,
            emitted,
            commit_sha=sha,
            min_distinct=n,
            loop_id=loop_id,
        )
        for sha in commit_shas
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--project-root", required=True)
    ap.add_argument(
        "--commit-sha",
        action="append",
        default=[],
        help="commit de ticket a verificar (repetible)",
    )
    ap.add_argument("--deliverable-type", default=None)
    ap.add_argument(
        "--min-distinct",
        type=int,
        default=None,
        help="override del N minimo de backend_key distintos (gana sobre --deliverable-type)",
    )
    ap.add_argument("--loop-id", default=None)
    args = ap.parse_args(argv)

    if not args.commit_sha:
        print("[loop-exec] SKIP: no --commit-sha dado (nada que verificar).")
        return 0

    project_root = Path(args.project_root).resolve()
    verdicts = audit(
        project_root,
        commit_shas=args.commit_sha,
        deliverable_type=args.deliverable_type,
        min_distinct=args.min_distinct,
        loop_id=args.loop_id,
    )
    failures = [v for v in verdicts if not v["ok"]]
    for v in verdicts:
        status = "OK" if v["ok"] else "FAIL"
        print(
            f"[loop-exec] {status} {v['commit_sha']}: "
            f"{len(v['distinct_backends'])}/{v['min_distinct']} lentes distintas "
            f"{v['distinct_backends']}"
        )
        # WOT-2026-043q: nombrar a quien callo, en verde y en rojo. Un contador
        # sin nombres obliga a re-medir a mano.
        for s in v["silent_rounds"]:
            print(
                f"[loop-exec]   MUDA {s['backend_key']}: {s['diagnosis']} "
                f"(output_chars={s['output_chars']})"
            )
        # WOT-2026-044p (b): nonces emitidos sin rondas (bucle declarado pero
        # no acreditado). Se reportan SIEMPRE como ERROR porque es la peor senal.
        for o in v["orphan_nonces"]:
            print(
                f"[loop-exec]   HUERFANO {o['nonce'][:12]}... "
                f"(loop={o['loop_id']}): {o['diagnosis']}"
            )
        if v["orphan_nonces"] and v not in failures:
            failures.append(v)
    if failures:
        print(
            "\n[loop-exec] ERROR: el bucle 1->9->2 NO corrio (o corrio DEGRADADO) "
            "para el/los commit(s) de arriba.\n"
            "  Cada commit de ticket exige >=N rondas de EJECUCION con backend_key\n"
            "  DISTINTO, un challenge_nonce emitido FUERA (emit-nonce) ANTES de la\n"
            "  ronda, y CONTENIDO en la respuesta: una lente que corre y CALLA no\n"
            "  aporta independencia (WOT-2026-043q). Las rondas MUDA de arriba, si\n"
            "  las hay, dicen si el fallo es de TRANSPORTE (no hubo llamada) o del\n"
            "  BACKEND (hubo llamada y respondio vacio). Corre el bucle de gobierno\n"
            "  de verdad -- no es una norma, es una barrera (WOT-2026-040b)."
        )
        return 1
    print("[loop-exec] OK: cada commit tiene el fan-out de gobierno ejecutado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
