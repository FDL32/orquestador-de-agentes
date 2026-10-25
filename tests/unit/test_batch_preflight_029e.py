"""WOT-2026-029e: contract-test del pre-flight de vuelo del batch.

Pinea las 2 preguntas canonicas sobre el prompt REAL del batch (no fixture),
verifica que el extractor falla cerrado ante seccion/pregunta ausente, y que
el modo mid-flight del cierre remite a las mismas preguntas (fuente unica).
Mutation que mata este test y ningun otro: renombrar un id de pregunta en el
prompt, o retirar la seccion / el cite del mid-flight.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, "scripts")

import batch_preflight as bp


BATCH_PROMPT = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "orchestrator_autonomous_ticket_batch.md"
)
CLOSE_PROMPT = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "orchestrator_session_close_full_audit.md"
)


def test_extractor_lee_el_prompt_real_y_pinea_los_ids() -> None:
    questions = bp.extract_questions()
    assert set(questions) == set(bp.PREFLIGHT_QUESTION_IDS)
    for qid, text in questions.items():
        assert text, qid
        assert len(text) > 40, f"{qid}: pregunta sin contenido suficiente"


def test_seccion_ausente_falla_cerrado(tmp_path: Path) -> None:
    original = BATCH_PROMPT.read_text(encoding="utf-8-sig")
    sin_seccion = "\n".join(
        ln for ln in original.splitlines() if "WOT-2026-029e" not in ln
    )
    try:
        bp.extract_questions(sin_seccion)
    except ValueError as exc:
        assert "ausente" in str(exc)
    else:
        raise AssertionError("la seccion ausente no fue detectada")


def test_pregunta_canonica_ausente_falla_cerrado() -> None:
    original = BATCH_PROMPT.read_text(encoding="utf-8-sig")
    sin_q2 = "\n".join(
        ln for ln in original.splitlines() if not ln.startswith("- **q2-")
    )
    try:
        bp.extract_questions(sin_q2)
    except ValueError as exc:
        assert "q2-human-break-points" in str(exc)
    else:
        raise AssertionError("la pregunta canonica ausente no fue detectada")


def test_adjudicacion_valida_pasa() -> None:
    record = {
        "adjudications": {
            "q1-backend-liveness": {
                "answer": "BA11 vivo con round-trip de 200 bytes",
                "adjudicated_at": "2026-10-25T12:00:00+00:00",
            },
            "q2-human-break-points": {
                "answer": "parada esperada en G-011 por REQUIERE_HUMANO",
                "adjudicated_at": "2026-10-25T12:00:00+00:00",
            },
        }
    }
    assert bp.validate_adjudications(record) == []


def test_adjudicacion_incompleta_falla_con_la_pregunta_nombrada() -> None:
    record = {
        "adjudications": {
            "q1-backend-liveness": {"answer": " ", "adjudicated_at": "ayer"},
        }
    }
    errors = bp.validate_adjudications(record)
    assert any("q2-human-break-points" in e for e in errors)
    assert any("q1-backend-liveness" in e and "vacia" in e for e in errors)
    assert any("adjudicated_at" in e for e in errors)
    assert bp.validate_adjudications(None)
    assert bp.validate_adjudications({"otra": "forma"})


def test_midflight_del_cierre_remite_a_las_mismas_preguntas() -> None:
    close = CLOSE_PROMPT.read_text(encoding="utf-8-sig")
    assert "WOT-2026-029e" in close, "el modo mid-flight no cita el pre-flight"
    for qid in bp.PREFLIGHT_QUESTION_IDS:
        assert qid in close, f"mid-flight sin la pregunta {qid}"
    assert "batch_preflight.py" in close
