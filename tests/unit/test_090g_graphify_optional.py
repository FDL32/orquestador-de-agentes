"""WOT-2026-090g: barrera de coherencia del estado OPCIONAL de graphify.

La skill declaraba obligatoriedad por umbral (DEBE activar si >30 archivos)
que nunca se ejercio (sin graphify-out/ en el repo) y que contradecia al
resto del repo (bootstrap y pipeline la referencian condicionalmente). Esta
barrera evita que la obligatoriedad reaparezca en silencio.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


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
_MANDATORY_LANGUAGE = (
    r"(?:must|debe|obligatori\w*|exig\w*|requier\w*|"
    r"es\s+necesari\w*|tiene\s+que|required|always)"
)
# Keep this line-local and bounded to 100 characters: it is deterministic and
# avoids treating a legitimate conditional sentence across lines as mandatory.
_MANDATORY_NEAR_GRAPHIFY_RE = re.compile(
    rf"\bgraphify\b.{{0,100}}{_MANDATORY_LANGUAGE}\b"
    rf"|{_MANDATORY_LANGUAGE}\b.{{0,100}}\bgraphify\b",
    re.IGNORECASE,
)


def _scan_markdown_roots(repo_root: Path, roots: list[Path]) -> list[str]:
    """Scan explicit Markdown roots and reject missing or empty universes."""
    violations: list[str] = []
    for root in roots:
        if not root.exists():
            raise AssertionError(f"raiz ausente: {root.relative_to(repo_root)}")
        paths = [root] if root.is_file() else sorted(root.rglob("*.md"))
        if not paths:
            raise AssertionError(f"raiz sin Markdown: {root.relative_to(repo_root)}")
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if _MANDATORY_NEAR_GRAPHIFY_RE.search(line):
                    violations.append(f"{path.relative_to(repo_root)}:{line_number}")
    return violations


def test_090g_no_mandatory_language_anywhere_in_tree() -> None:
    """DoD(b)+(c): barrera GLOBAL -- ninguna LINEA que cite graphify en
    AGENTS.md, prompts/, docs/ ni skills/ usa lenguaje obligatorio."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    targets = [repo_root / "AGENTS.md"] + [
        repo_root / rel for rel in ("prompts", "docs", "skills")
    ]
    violations = _scan_markdown_roots(repo_root, targets)
    assert not violations, (
        "lenguaje obligatorio hacia graphify reaparecio en: " + ", ".join(violations)
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "graphify exige activacion",
        "graphify requiere activacion",
        "graphify es necesario",
        "graphify tiene que activarse",
        "graphify required",
        "graphify always runs",
        "debe usar graphify",
    ],
)
def test_090g_expanded_mandatory_vocabulary_is_detected(phrase: str) -> None:
    assert _MANDATORY_NEAR_GRAPHIFY_RE.search(phrase)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("El Builder DEBE activar graphify", True),
        ("GRAPHIFY REQUIERE activacion", True),
        ("Graphify Es Necesario", True),
        ("graphify ALWAYS runs", True),
        ("El Builder DEBE activar la skill", False),
    ],
)
def test_090g_mandatory_language_is_case_insensitive_and_near_graphify(
    phrase: str, expected: bool
) -> None:
    assert bool(_MANDATORY_NEAR_GRAPHIFY_RE.search(phrase)) is expected


def test_090g_window_and_line_boundaries_are_explicit() -> None:
    assert _MANDATORY_NEAR_GRAPHIFY_RE.search("graphify " + "x" * 98 + " debe")
    assert not _MANDATORY_NEAR_GRAPHIFY_RE.search("graphify " + "x" * 99 + " debe")
    assert _MANDATORY_NEAR_GRAPHIFY_RE.search("debe " + "x" * 98 + " graphify")
    assert not _MANDATORY_NEAR_GRAPHIFY_RE.search("debe " + "x" * 99 + " graphify")
    assert not _MANDATORY_NEAR_GRAPHIFY_RE.search("graphify\n debe usar")


def test_090g_frontmatter_is_scanned_as_text(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.md"
    fixture.write_text(
        "---\npolicy: debe usar graphify\n---\ntexto condicional\n",
        encoding="utf-8",
    )
    assert _scan_markdown_roots(tmp_path, [fixture]) == ["fixture.md:2"]


@pytest.mark.parametrize("root_kind", ["missing", "empty"])
def test_090g_universe_root_must_exist_and_contain_markdown(
    tmp_path: Path, root_kind: str
) -> None:
    root = tmp_path / root_kind
    if root_kind == "empty":
        root.mkdir()
    expected = "raiz ausente" if root_kind == "missing" else "raiz sin Markdown"
    with pytest.raises(AssertionError, match=expected):
        _scan_markdown_roots(tmp_path, [root])


def test_090g_mutation_puede_activar_to_debe_usar_is_caught() -> None:
    source = "El Builder PUEDE activar graphify"
    assert source.count("PUEDE activar") == 1
    mutated = source.replace("PUEDE activar", "debe usar")
    assert _MANDATORY_NEAR_GRAPHIFY_RE.search(mutated)


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
