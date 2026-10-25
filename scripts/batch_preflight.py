"""WOT-2026-029e: extractor canonico del pre-flight de vuelo del batch.

Before: prompts/orchestrator_autonomous_ticket_batch.md contiene la seccion
    canonica "Paso 0.25" anclada a WOT-2026-029e con las 2 preguntas.
During: extract_questions() aisla la seccion (del heading con el ancla al
    siguiente heading de nivel 2) y parsea las viñetas de pregunta
    (`- **<id>**: <texto>`); validate_adjudications() valida un registro de
    respuestas (respuesta no vacia + adjudicated_at ISO-8601 por pregunta
    canonica). Nada escribe a disco.
After: fail-closed -- seccion o pregunta canonica ausente levanta ValueError;
    un registro incompleto devuelve errores nombrando la pregunta. Fuente
    unica, tres consumidores (ejecutor del batch, handoff mid-flight del
    cierre, contract-test).
"""

from __future__ import annotations

import re
from pathlib import Path


PREFLIGHT_QUESTION_IDS = ("q1-backend-liveness", "q2-human-break-points")
_SECTION_ANCHOR = "WOT-2026-029e"
_Q_RE = re.compile(r"^- \*\*(q[0-9]+-[a-z0-9-]+)\*\*:?\s*(.+)$", re.MULTILINE)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _prompt_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "prompts"
        / "orchestrator_autonomous_ticket_batch.md"
    )


def extract_questions(prompt_text: str | None = None) -> dict[str, str]:
    """Return {question_id: question_text} from the canonical 029e section.

    Before: ``prompt_text`` optional (defaults to the REAL batch prompt; the
        contract-test exercises the real file, not a fixture copy).
    During: isolates the section whose heading carries the anchor and parses
        the question bullets.
    After: fail-closed -- ValueError if the section or any canonical question
        id is missing or arrives with empty text.
    """
    if prompt_text is None:
        prompt_text = _prompt_path().read_text(encoding="utf-8-sig")
    lines = prompt_text.splitlines()
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.startswith("## ") and _SECTION_ANCHOR in ln
        ),
        None,
    )
    if start is None:
        raise ValueError(
            f"seccion pre-flight {_SECTION_ANCHOR} ausente del prompt del batch"
        )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    found = {qid: text.strip() for qid, text in _Q_RE.findall(section)}
    missing = [qid for qid in PREFLIGHT_QUESTION_IDS if not found.get(qid)]
    if missing:
        raise ValueError(
            f"preguntas pre-flight ausentes o vacias en {_SECTION_ANCHOR}: {missing}"
        )
    return found


def validate_adjudications(record: object) -> list[str]:
    """Validate a pre-flight adjudication record (fail-closed, no I/O).

    Before: ``record`` is the decoded ``pre_flight_adjudications`` field of a
        batch_run / parte de parada (dict, o cualquier otra cosa = invalido).
    During: exige el dict ``adjudications`` con una entrada por pregunta
        canonica, ``answer`` no vacio y ``adjudicated_at`` ISO-8601.
    After: una cadena de error por problema; lista vacia == valido. Nunca
        lanza.
    """
    if not isinstance(record, dict) or not isinstance(
        record.get("adjudications"), dict
    ):
        return ["pre-flight record: falta el dict 'adjudications'"]
    errors: list[str] = []
    adjudications = record["adjudications"]
    for qid in PREFLIGHT_QUESTION_IDS:
        entry = adjudications.get(qid)
        if not isinstance(entry, dict):
            errors.append(f"pre-flight record: sin respuesta para {qid}")
            continue
        answer = entry.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            errors.append(f"pre-flight record: respuesta vacia para {qid}")
        stamped = entry.get("adjudicated_at")
        if not isinstance(stamped, str) or not _ISO_RE.match(stamped):
            errors.append(
                f"pre-flight record: 'adjudicated_at' ISO-8601 ausente para {qid}"
            )
    return errors
