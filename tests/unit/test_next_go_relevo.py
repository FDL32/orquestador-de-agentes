"""Pruebas del selector de GO de relevo WOT-2026-161b."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[2] / "scripts" / "flight" / "next_go_relevo.py"
)
SPEC = importlib.util.spec_from_file_location("next_go_relevo", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("no se pudo cargar next_go_relevo.py")
next_go_relevo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(next_go_relevo)

MESSAGE_ID = "11111111-2222-3333-4444-555555555555"


def _write_registry(path: Path, rows: list[tuple[str, str]]) -> None:
    """Before: recibe estados para filas bN.

    During: escribe la tabla markdown con el esquema contractual de seis columnas.
    After: deja un registro que puede ordenar el CLI numéricamente.
    """
    lines = [
        f"| {number} | go-relevo24h-{number} | {MESSAGE_ID} | "
        f"hilo de CO-1 mcp:{MESSAGE_ID} 'Go {number}' | 2026-11-01 | {state} |"
        for number, state in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_rc0_selects_first_free_row_in_numeric_order(tmp_path: Path, capsys) -> None:
    """Before: b10 appears before free b2 in file order.

    During: reads and sorts all valid rows by the numeric bN suffix.
    After: returns rc 0 and selects b2 without requesting another GO.
    """
    registry = tmp_path / "registry.md"
    _write_registry(
        registry, [("b10", "SIN USAR"), ("b2", "SIN USAR"), ("b1", "USADO")]
    )

    rc = next_go_relevo.main(["--registro", str(registry)])

    output = capsys.readouterr().out
    assert rc == 0
    assert "GO LIBRE: b2" in output
    assert "NO PIDAS OTRO GO" in output


def test_rc3_when_every_row_is_used(tmp_path: Path, capsys) -> None:
    """Before: the registry has valid bN rows but none starts with SIN USAR.

    During: scans the sorted rows.
    After: returns rc 3 and says that a new GO is needed.
    """
    registry = tmp_path / "registry.md"
    _write_registry(registry, [("b1", "USADO"), ("b2", "USADO")])

    rc = next_go_relevo.main(["--registro", str(registry)])

    assert rc == 3
    assert "SIN GO LIBRE" in capsys.readouterr().out


def test_rc2_when_registry_is_absent_or_has_no_rows(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Before: neither the argument nor the environment resolves a registry.

    During: invokes the fail-closed input path.
    After: returns rc 2 and emits a cause on stderr.
    """
    monkeypatch.delenv("GO_RELEVO_REGISTRO", raising=False)

    rc = next_go_relevo.main([])

    assert rc == 2
    assert "falta --registro" in capsys.readouterr().err

    empty = tmp_path / "empty.md"
    empty.write_text("sin filas\n", encoding="utf-8")
    rc = next_go_relevo.main(["--registro", str(empty)])
    assert rc == 2
    assert "no tiene filas bN" in capsys.readouterr().err


def test_environment_registry_is_used_when_argument_is_omitted(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Before: the registry is supplied only through GO_RELEVO_REGISTRO.

    During: resolves that environment variable and reads it without writing.
    After: returns rc 0 for its free row.
    """
    registry = tmp_path / "registry.md"
    _write_registry(registry, [("b3", "SIN USAR - pendiente")])
    monkeypatch.setenv("GO_RELEVO_REGISTRO", str(registry))

    rc = next_go_relevo.main([])

    assert rc == 0
    assert "GO LIBRE: b3" in capsys.readouterr().out
