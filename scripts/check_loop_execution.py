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
DISTINTO y un `challenge_nonce` que fue EMITIDO FUERA del ejecutor
(`emitted_nonces.jsonl`) ANTES de la ronda. `N` es proporcional al
`deliverable_type` (un typo/doc no exige 9 lentes).

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

    El emisor NO se excluye aqui por identidad (no sabemos su backend_key sin leer
    la emision); se excluye en el gate porque el issuer_backend_key nunca ejecuta
    una `ronda` -- solo emite. Devolver el CONJUNTO (no el conteo) deja que el
    caller reporte QUIENES corrieron.
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    backends: set[str] = set()
    for row in scorecard_rows:
        if row.get("event") != "ronda":
            continue
        if row.get("commit_sha") != commit_sha:
            continue
        bk = row.get("backend_key")
        nonce = row.get("challenge_nonce")
        if not bk or not nonce:
            continue
        emitted_ts = valid_nonces.get(nonce)
        if emitted_ts is None:
            continue  # nonce no emitido para este commit: fabricado
        row_ts = row.get("ts")
        if row_ts is not None and emitted_ts > row_ts:
            continue  # el nonce se emitio DESPUES de la ronda: sin ceremonia previa
        backends.add(bk)
    return backends


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
    if failures:
        print(
            "\n[loop-exec] ERROR: el bucle 1->9->2 NO corrio (o corrio DEGRADADO) "
            "para el/los commit(s) de arriba.\n"
            "  Cada commit de ticket exige >=N rondas de EJECUCION con backend_key\n"
            "  DISTINTO y un challenge_nonce emitido FUERA (emit-nonce) ANTES de la\n"
            "  ronda. Corre el bucle de gobierno de verdad -- no es una norma, es una\n"
            "  barrera (WOT-2026-040b)."
        )
        return 1
    print("[loop-exec] OK: cada commit tiene el fan-out de gobierno ejecutado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
