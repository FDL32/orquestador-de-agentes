"""WOT-2026-090g: barrera de coherencia del estado OPCIONAL de graphify.

La skill declaraba obligatoriedad por umbral (DEBE activar si >30 archivos)
que nunca se ejercio (sin graphify-out/ en el repo) y que contradecia al
resto del repo (bootstrap y pipeline la referencian condicionalmente). Esta
barrera evita que la obligatoriedad reaparezca en silencio.
"""

from __future__ import annotations

import re
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


# Ronda 2 (hallazgo Codex): la barrera debe ser el GREP GLOBAL del arbol, no
# dos cadenas exactas. Regex del propio Revisor, LINE-BASED (sin DOTALL: el
# SKILL.md dice "no obligatoria" y un cruce multi-linea daria falso positivo).
_MANDATORY_NEAR_GRAPHIFY_RE = re.compile(
    r"graphify.{0,100}(?:must|debe|obligatori)"
    r"|(?:must|debe|obligatori).{0,100}graphify",
    re.IGNORECASE,
)


def test_090g_no_mandatory_language_anywhere_in_tree() -> None:
    """DoD(b)+(c): barrera GLOBAL -- ninguna LINEA que cite graphify en
    AGENTS.md, prompts/, docs/ ni skills/ usa lenguaje obligatorio."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    targets: list[Path] = [repo_root / "AGENTS.md"]
    for rel in ("prompts", "docs", "skills"):
        base = repo_root / rel
        if base.is_dir():
            targets.extend(p for p in base.rglob("*.md"))
    violations: list[str] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _MANDATORY_NEAR_GRAPHIFY_RE.search(line):
                violations.append(f"{path.relative_to(repo_root)}:{i}")
    assert not violations, (
        "lenguaje obligatorio hacia graphify reaparecio en: " + ", ".join(violations)
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
