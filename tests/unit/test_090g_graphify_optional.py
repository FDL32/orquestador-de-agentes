"""WOT-2026-090g: barrera de coherencia del estado OPCIONAL de graphify.

La skill declaraba obligatoriedad por umbral (DEBE activar si >30 archivos)
que nunca se ejercio (sin graphify-out/ en el repo) y que contradecia al
resto del repo (bootstrap y pipeline la referencian condicionalmente). Esta
barrera evita que la obligatoriedad reaparezca en silencio.
"""

from __future__ import annotations

from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parent.parent.parent / "skills" / "graphify" / "SKILL.md"
)


def test_090g_skill_declares_optional_with_reason() -> None:
    """DoD(a): la skill declara su estado OPCIONAL y la razon de no-invocacion."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## Estado: OPCIONAL" in text
    assert "WOT-2026-090g" in text
    assert "Raz" in text and "no-invocaci" in text


def test_090g_no_mandatory_by_threshold_language() -> None:
    """DoD(b): 0 referencias que la exijan por umbral (DEBE activar / Builder
    ejecuta graphify al inicio)."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "El Builder DEBE activar" not in text
    assert (
        "El Builder ejecuta graphify al inicio de la fase IMPLEMENT cuando el corpus es grande:"
        not in text
    )


def test_090g_repo_references_stay_conditional() -> None:
    """DoD(c): las referencias externas al skill siguen condicionales
    (bootstrap la declara prescindible; pipeline la cita con 'si')."""
    prompts = Path(__file__).resolve().parent.parent.parent / "prompts"
    bootstrap = (prompts / "orchestrator_destination_bootstrap.md").read_text(
        encoding="utf-8"
    )
    assert "Graphify" in bootstrap  # sigue citada, como prescindible
    pipeline = (prompts / "orchestrator_pipeline.md").read_text(encoding="utf-8")
    assert "si las dependencias" in pipeline  # cita condicional intacta
