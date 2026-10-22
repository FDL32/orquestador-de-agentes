"""Tests for scripts/check_reference_keys.py (WOT-2026-114d).

Before: fixtures build tiny throwaway trees under tmp_path with a legend file,
    a reference module and zero or more citation files.
During: calls `check.check(project_root, legend_path)` directly (no subprocess;
    the CLI wrapper is a thin argparse shell over the same function).
After: asserts the exact violation shape for each failure mode the design doc
    (Secciones 6/6.1) commits to, and the clean-pass case for a well-formed tree.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_reference_keys as crk


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _make_legend(root: Path, rows: dict[str, str]) -> Path:
    legend_path = root / "docs" / "registry" / "reference_keys.md"
    body = "| letra | fichero |\n|-------|---------|\n"
    for letter, rel_path in rows.items():
        body += f"| {letter} | `{rel_path}` |\n"
    _write(legend_path, body)
    return legend_path


def test_citation_resolves_cleanly(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto completo del caso.\n")
    _write(tmp_path / "AGENTS.md", "- bullet corto (ver F1)\n")
    assert crk.check(tmp_path, legend) == []


def test_orphan_citation_fails(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto completo.\n")
    _write(tmp_path / "AGENTS.md", "- bullet corto (ver F2)\n")
    violations = crk.check(tmp_path, legend)
    assert len(violations) == 1
    assert "F2" in violations[0]
    assert "no tiene ningun ancla" in violations[0]


def test_duplicate_anchor_fails(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(
        tmp_path / "module.md",
        "**F1.** primera version.\n\n**F1.** version duplicada.\n",
    )
    _write(tmp_path / "AGENTS.md", "- bullet (ver F1)\n")
    violations = crk.check(tmp_path, legend)
    assert any("duplicada" in v for v in violations)


def test_letter_without_legend_row_fails(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto.\n")
    _write(tmp_path / "AGENTS.md", "- bullet (ver Z9)\n")
    violations = crk.check(tmp_path, legend)
    assert len(violations) == 1
    assert "letra 'Z'" in violations[0]
    assert "ausente de la leyenda" in violations[0]


def test_legend_points_to_missing_file_fails(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "nope.md"})
    _write(tmp_path / "AGENTS.md", "- bullet sin citas\n")
    violations = crk.check(tmp_path, legend)
    assert any("no existe" in v for v in violations)


def test_citation_inside_backtick_fence_is_excluded(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto.\n")
    _write(
        tmp_path / "AGENTS.md",
        "texto normal\n```\nejemplo con (ver F9) dentro de un fence\n```\n",
    )
    assert crk.check(tmp_path, legend) == []


def test_citation_inside_tilde_fence_is_excluded(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto.\n")
    _write(
        tmp_path / "AGENTS.md",
        "texto normal\n~~~\nejemplo con (ver F9) dentro de un fence\n~~~\n",
    )
    assert crk.check(tmp_path, legend) == []


def test_anchor_without_citation_is_not_a_violation(tmp_path: Path) -> None:
    legend = _make_legend(tmp_path, {"F": "module.md"})
    _write(tmp_path / "module.md", "**F1.** texto sin ninguna cita que lo use.\n")
    _write(tmp_path / "AGENTS.md", "- bullet sin citas\n")
    assert crk.check(tmp_path, legend) == []


def test_strip_fenced_code_preserves_line_count() -> None:
    text = "a\n```\nb\nc\n```\nd\n"
    stripped = crk.strip_fenced_code(text)
    assert len(stripped.splitlines()) == len(text.splitlines())
    assert stripped.splitlines()[0] == "a"
    assert stripped.splitlines()[-1] == "d"
    assert "b" not in stripped and "c" not in stripped
