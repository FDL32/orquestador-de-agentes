"""Tests para check_context_budget.py (WOT-2026-071a).

Cubre: resolucion de @import transitiva con 2+ niveles, deteccion de ciclo
sin bucle infinito, exit code 0 en ambos casos de pct (por encima y por
debajo del 5%), y formato --json valido.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.check_context_budget import (
    check_budget,
    measure_chars,
    resolve_import_closing,
)


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Crea un workspace temporario con ficheros para pruebas."""
    return tmp_path


def test_resolve_import_single(tmp_workspace: Path) -> None:
    """Resuelve un unico @import."""
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@AGENTS.md\n", encoding="utf-8")
    agentsmd = tmp_workspace / "AGENTS.md"
    agentsmd.write_text("x" * 100, encoding="utf-8")

    paths = resolve_import_closing(tmp_workspace, ["CLAUDE.md"])
    resolved = [p.resolve() for p in paths]
    assert agentsmd.resolve() in resolved


def test_resolve_import_transitive_two_levels(tmp_workspace: Path) -> None:
    """Resuelve @import transitivo con 2 niveles."""
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@AGENTS.md\n", encoding="utf-8")
    agentsmd = tmp_workspace / "AGENTS.md"
    agentsmd.write_text("@PROMPT.md\n", encoding="utf-8")
    promptmd = tmp_workspace / "PROMPT.md"
    promptmd.write_text("contenido del prompt", encoding="utf-8")

    paths = resolve_import_closing(tmp_workspace, ["CLAUDE.md"])
    resolved = [p.resolve() for p in paths]
    assert agentsmd.resolve() in resolved
    assert promptmd.resolve() in resolved


def test_resolve_import_cycle_detection(tmp_workspace: Path) -> None:
    """Detecta ciclo sin bucle infinito: A->B->A."""
    a = tmp_workspace / "A.md"
    a.write_text("@B.md\n", encoding="utf-8")
    b = tmp_workspace / "B.md"
    b.write_text("@A.md\n", encoding="utf-8")

    paths = resolve_import_closing(tmp_workspace, ["A.md"])
    resolved = [p.resolve() for p in paths]
    assert a.resolve() in resolved
    assert b.resolve() in resolved


def test_resolve_import_no_cycle_infinite_loop(tmp_workspace: Path) -> None:
    """No entra en bucle infinito con un ciclo real."""
    a = tmp_workspace / "A.md"
    a.write_text("@B.md\n", encoding="utf-8")
    b = tmp_workspace / "B.md"
    b.write_text("@A.md\n@C.md\n", encoding="utf-8")
    c = tmp_workspace / "C.md"
    c.write_text("contenido de c", encoding="utf-8")

    # Si hubiera bucle infinito, esto colgaria. pytest --timeout lo caza,
    # pero el test pasa si resolve_import_closing devuelve correctamente.
    paths = resolve_import_closing(tmp_workspace, ["A.md"])
    resolved = [p.resolve() for p in paths]
    assert a.resolve() in resolved
    assert b.resolve() in resolved
    assert c.resolve() in resolved


def test_resolve_import_multiple_roots(tmp_workspace: Path) -> None:
    """Resuelve cierre desde multiples ficheros raiz."""
    a = tmp_workspace / "CLAUDE.md"
    a.write_text("@X.md\n", encoding="utf-8")
    b = tmp_workspace / "OTHER.md"
    b.write_text("@Y.md\n", encoding="utf-8")
    x = tmp_workspace / "X.md"
    x.write_text("x" * 50, encoding="utf-8")
    y = tmp_workspace / "Y.md"
    y.write_text("y" * 30, encoding="utf-8")

    paths = resolve_import_closing(tmp_workspace, ["CLAUDE.md", "OTHER.md"])
    resolved = [p.resolve() for p in paths]
    assert x.resolve() in resolved
    assert y.resolve() in resolved


def test_measure_chars(tmp_workspace: Path) -> None:
    """Mide chars de varios ficheros."""
    f1 = tmp_workspace / "f1.txt"
    f1.write_text("hola", encoding="utf-8")  # 4 chars
    f2 = tmp_workspace / "f2.txt"
    f2.write_text("mundo\n", encoding="utf-8")  # 6 chars

    measured = measure_chars([f1, f2])
    assert len(measured) == 2
    chars_by_path = {m["path"]: m["chars"] for m in measured}
    assert chars_by_path[str(f1)] == 4
    assert chars_by_path[str(f2)] == 6


def test_check_budget_below_threshold(
    tmp_workspace: Path, capsys: pytest.CaptureFixture
) -> None:
    """Pct <= 5%: exit code 0, sin WARN."""
    # Crear un CLAUDE.md con @import a un fichero pequeno
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@small.md\n", encoding="utf-8")
    small = tmp_workspace / "small.md"
    small.write_text("x" * 100, encoding="utf-8")  # 100 chars = 25 tokens

    # window_tokens=1000 -> 25/1000 = 2.5% (debajo de 5%)
    with patch("pathlib.Path.cwd", return_value=tmp_workspace):
        result = check_budget(window_tokens=1000, roots=["CLAUDE.md"])

    assert result["pct"] <= 5.0
    captured = capsys.readouterr()
    assert "WARN" not in captured.err


def test_check_budget_above_threshold(
    tmp_workspace: Path, capsys: pytest.CaptureFixture
) -> None:
    """Pct > 5%: exit code 0, emite WARN por stderr."""
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@big.md\n", encoding="utf-8")
    big = tmp_workspace / "big.md"
    # 3000 chars = 750 tokens -> 750/10000 = 7.5% (por encima de 5%)
    big.write_text("x" * 3000, encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_workspace):
        result = check_budget(window_tokens=10000, roots=["CLAUDE.md"])

    assert result["pct"] > 5.0
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "check_context_budget" in captured.err


def test_check_budget_json_output(
    tmp_workspace: Path, capsys: pytest.CaptureFixture
) -> None:
    """--json emite JSON valido a stdout."""
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@data.md\n", encoding="utf-8")
    data = tmp_workspace / "data.md"
    data.write_text("contenido", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_workspace):
        check_budget(
            window_tokens=200000,
            roots=["CLAUDE.md"],
            output_json=True,
        )

    captured = capsys.readouterr()
    # Debe ser JSON parseable
    parsed = json.loads(captured.out)
    assert "total_chars" in parsed
    assert "total_tokens_proxy" in parsed
    assert "window_tokens" in parsed
    assert "pct" in parsed
    assert "files" in parsed
    assert isinstance(parsed["files"], list)


def test_check_budget_returns_result_dict(tmp_workspace: Path) -> None:
    """check_budget() devuelve un dict con las métricas."""
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@big.md\n", encoding="utf-8")
    big = tmp_workspace / "big.md"
    big.write_text("x" * 3000, encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_workspace):
        result = check_budget(window_tokens=10000, roots=["CLAUDE.md"])
    assert isinstance(result, dict)
    assert "total_chars" in result
    assert "pct" in result
    assert result["pct"] > 5.0


def test_exit_code_zero_via_subprocess(tmp_workspace: Path) -> None:
    """Verifica exit code 0 corriendo el script como subprocess."""
    script_path = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_context_budget.py"
    )

    # Crear un CLAUDE.md ficticio en tmp_workspace
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=tmp_workspace,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_cli_json_flag(tmp_workspace: Path, capsys: pytest.CaptureFixture) -> None:
    """Prueba el CLI real con --json."""
    script_path = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_context_budget.py"
    )
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@f.md\n", encoding="utf-8")
    f = tmp_workspace / "f.md"
    f.write_text("data", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path), "--json"],
        cwd=tmp_workspace,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert "total_chars" in parsed


def test_cli_window_tokens(tmp_workspace: Path, capsys: pytest.CaptureFixture) -> None:
    """Prueba el CLI real con --window-tokens."""
    script_path = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_context_budget.py"
    )
    claudemd = tmp_workspace / "CLAUDE.md"
    claudemd.write_text("@f.md\n", encoding="utf-8")
    f = tmp_workspace / "f.md"
    f.write_text("x" * 200, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path), "--window-tokens", "100", "--json"],
        cwd=tmp_workspace,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    # 200 chars / 4 = 50 tokens -> 50/100 = 50%
    # 206 chars / 4 = 51 tokens -> 51/100 = 51% (includes CLAUDE.md content)
    assert parsed["pct"] == 51.0
