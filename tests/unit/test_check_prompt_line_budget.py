"""Tests for scripts/check_prompt_line_budget.py (WOT-2026-090d).

Hermetic: pure-function tests over strings and temp files, no network, no
backend, no LLM. The line-budget guard is a mechanical count-and-compare
check, no semantic oracle needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pytest import fixture


MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_prompt_line_budget as cplb  # noqa: E402


@fixture
def prompt_within_budget(tmp_path: Path) -> Path:
    """Crea un fichero con 3 lineas de contenido+frontmatter (total 7)
    y budget=7 -> within_budget=True. La cuenta incluye frontmatter."""
    content = "---\nrole: builder\nline_budget: 7\n---\na\nb\nc\n"
    path = tmp_path / "prompt.md"
    path.write_text(content, encoding="utf-8")
    return path


@fixture
def prompt_over_budget(tmp_path: Path) -> Path:
    """Crea un fichero con 14 lineas totales (frontmatter+contenido)
    y budget=5 -> within_budget=False."""
    content = (
        "---\n"
        "role: builder\n"
        "line_budget: 5\n"
        "---\n"
        "linea1\n"
        "linea2\n"
        "linea3\n"
        "linea4\n"
        "linea5\n"
        "linea6\n"
        "linea7\n"
        "linea8\n"
        "linea9\n"
    )
    path = tmp_path / "prompt.md"
    path.write_text(content, encoding="utf-8")
    return path


@fixture
def prompt_no_budget(tmp_path: Path) -> Path:
    """Crea un fichero con frontmatter sin line_budget."""
    content = "---\nrole: builder\nroute_kind: modulo\n---\ncontenido\n"
    path = tmp_path / "prompt.md"
    path.write_text(content, encoding="utf-8")
    return path


@fixture
def write_file(tmp_path: Path) -> Path:
    """Helper fixture para crear ficheros arbitrarios."""

    def _write(name: str, text: str) -> Path:
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p

    return _write


def test_within_budget_true(prompt_within_budget: Path):
    """7 lineas reales <= budget 7 -> within_budget=True (rc=0 via main)."""
    result = cplb.audit(prompt_within_budget)
    assert result.within_budget is True
    assert result.line_budget == 7
    assert result.actual_lines == 7

    rc = cplb.main([str(prompt_within_budget)])
    assert rc == 0


def test_over_budget_false(prompt_over_budget: Path):
    """13 lineas reales > budget 5 -> within_budget=False, motivo de exceso."""
    result = cplb.audit(prompt_over_budget)
    assert result.within_budget is False
    assert result.line_budget == 5
    assert result.actual_lines == 13
    assert "exceso" in result.motivo or "14" in result.motivo

    rc = cplb.main([str(prompt_over_budget)])
    assert rc == 1


def test_no_budget_fails_closed(prompt_no_budget: Path):
    """Sin line_budget en frontmatter -> within_budget=False, motivo NO_BUDGET_DECLARED."""
    result = cplb.audit(prompt_no_budget)
    assert result.within_budget is False
    assert result.line_budget is None
    assert result.motivo == "NO_BUDGET_DECLARED"

    rc = cplb.main([str(prompt_no_budget)])
    assert rc == 1


def test_real_prompts_within_budget():
    """REGRESION: los DOS ficheros reales de prompts/ cumplen su presupuesto
    tras las ediciones de WOT-2026-090d (a) y (d). Este test falla si alguien
    vuelve a inflar un prompt por encima del presupuesto.
    """
    for rel in cplb.NORMATIVE_PROMPTS:
        path = MOTOR_ROOT / rel
        result = cplb.audit(path)
        assert result.within_budget is True, (
            f"{rel}: {result.motivo} (budget={result.line_budget}, "
            f"lines={result.actual_lines})"
        )


def test_main_check_all_rc0():
    """--check-all sobre el repo actual debe dar exit 0 tras las ediciones."""
    rc = cplb.main(["--check-all"])
    assert rc == 0


def test_parse_frontmatter_no_frontmatter(tmp_path: Path):
    """Un fichero sin lineas --- no devuelve budget."""
    content = "solo texto sin frontmatter\n"
    result = cplb._parse_frontmatter_line_budget(content)
    assert result is None


def test_parse_frontmatter_budget_value():
    """El parser extrae correctamente el valor numerico del budget."""
    content = "---\nrole: manager\nline_budget: 440\n---\ncontenido\n"
    result = cplb._parse_frontmatter_line_budget(content)
    assert result == 440


def test_cli_admits_single_path(write_file):
    """CLI real: una sola ruta con budget suficiente -> exit 0."""
    p = write_file(
        "x.md",
        "---\nrole: builder\nline_budget: 7\n---\na\nb\nc\n",
    )
    rc = cplb.main([str(p)])
    assert rc == 0


def test_cli_admits_multiple_paths(write_file):
    """CLI real: multiples rutas, alguno fuera de presupuesto -> exit 1."""
    good = write_file(
        "good.md",
        "---\nrole: builder\nline_budget: 10\n---\na\nb\nc\n",
    )
    bad = write_file(
        "bad.md",
        "---\nrole: builder\nline_budget: 2\n---\na\nb\nc\n",
    )
    rc = cplb.main([str(good), str(bad)])
    assert rc == 1
