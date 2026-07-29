"""Contract tests for the DEC receipt clause in the DESIGN session prompts
(WOT-2026-042w).

Que protege
-----------
Ningun prompt de sesion de DISENO pedia consultar el registro de decisiones,
luego una sesion de diseno podia adjudicar CONTRA una DEC aceptada sin saber
siquiera que existia. El hueco era ANTERIOR a cualquier gate: faltaba la NORMA.
Estos tests fijan la norma en los DOS prompts.

Por que un test POR PROMPT y no uno que mire los dos
----------------------------------------------------
Aislamiento por rama (leccion 021u, mismo patron que
tests/unit/test_autonomous_batch_prompt_contract.py y
tests/test_pipeline_adversarial_wiring.py): un unico test parametrizado sobre
[bootstrap, close] tambien caeria al borrar UNA clausula, pero cablear solo uno
de los dos prompts dejaria al OTRO sin test propio en rojo. Cada prompt tiene su
node-id nombrado para que la mutacion se demuestre POR SEPARADO:

  borrar la clausula de orchestrator_session_bootstrap_design.md          -> ROJO en
    test_bootstrap_design_prompt_requires_decision_registry_consult
  borrar la clausula de orchestrator_session_close_full_audit_design.md   -> ROJO en
    test_close_design_prompt_requires_decision_registry_consult

Before / During / After
-----------------------
Before: ambos prompts existen en `<motor>/prompts/`.
During: se leen en UTF-8 y se buscan las clausulas normativas (consulta del
    registro, las TRES formas exactas del recibo, y el override escrito).
    Sin I/O mas alla de la lectura; sin red; sin subprocess.
After: exit 0 sii los dos prompts declaran la norma completa. No muta nada.
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
BOOTSTRAP_DESIGN = PROMPTS / "orchestrator_session_bootstrap_design.md"
CLOSE_DESIGN = PROMPTS / "orchestrator_session_close_full_audit_design.md"

# Las TRES formas exactas y parseables del recibo. El scope entre parentesis es
# parte del contrato: dice contra QUE registro se resuelve el id.
RECEIPT_FORMS = ("DEC-<id> (motor)", "DEC-<id> (destino)", "DEC-no-aplica:")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_declares_registry_consult(text: str, prompt_name: str) -> None:
    """La norma completa: consultar el registro + formato de recibo + override."""
    assert "decisions.md" in text, (
        f"{prompt_name} debe nombrar el registro del destino "
        "(.agent/planning/decisions.md) que la sesion tiene que CONSULTAR "
        "antes de adjudicar (WOT-2026-042w)"
    )
    assert "docs/decisions" in text, (
        f"{prompt_name} debe nombrar el registro del motor (docs/decisions/) "
        "-- son DOS registros y el scope del recibo los distingue"
    )
    for form in RECEIPT_FORMS:
        assert form in text, (
            f"{prompt_name} debe declarar la forma exacta del recibo {form!r}; "
            "un recibo sin scope explicito no es resoluble contra un registro"
        )
    assert "supersedes:" in text and "invalidates:" in text, (
        f"{prompt_name} debe exigir `supersedes:` o `invalidates:` sobre la DEC "
        "CONCRETA cuando la adjudicacion la contradiga: el override va ESCRITO"
    )


def test_bootstrap_design_prompt_requires_decision_registry_consult() -> None:
    """Node-id nombrado por la MUTATION del prompt de arranque de diseno."""
    _assert_declares_registry_consult(
        _read(BOOTSTRAP_DESIGN), "orchestrator_session_bootstrap_design.md"
    )


def test_close_design_prompt_requires_decision_registry_consult() -> None:
    """Node-id nombrado por la MUTATION del prompt de cierre de diseno."""
    _assert_declares_registry_consult(
        _read(CLOSE_DESIGN), "orchestrator_session_close_full_audit_design.md"
    )


@pytest.mark.parametrize(
    "prompt_path",
    [BOOTSTRAP_DESIGN, CLOSE_DESIGN],
    ids=["bootstrap_design", "close_design"],
)
def test_design_prompt_declares_registry_is_read_only(prompt_path: Path) -> None:
    """Crear o cambiar una DEC es decision humana: el prompt lo dice explicito.

    Sin esta clausula, una sesion de diseno que encuentra una DEC incomoda
    podria "arreglarla" en vez de declarar el override -- que es precisamente
    la contradiccion silenciosa que el recibo previene.
    """
    text = _read(prompt_path)
    lowered = text.lower()
    assert "lectura only" in lowered or "read-only" in lowered, (
        f"{prompt_path.name} debe declarar el registro de decisiones como "
        "LECTURA ONLY (no anadir, editar ni reordenar ninguna DEC)"
    )
    assert "decision humana" in lowered, (
        f"{prompt_path.name} debe declarar que crear/cambiar una DEC es una "
        "decision humana aparte, fuera del alcance de la sesion de diseno"
    )
