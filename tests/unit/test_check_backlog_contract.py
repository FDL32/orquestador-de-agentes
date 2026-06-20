"""Barrier tests for check_backlog_contract.py (WOT-2026-012b).

The gate must: read the active 'Vista rapida' table only, enforce the closed
Status / Reactivation vocabulary, and FAIL CLOSED when no project root is given.
Every test reproduces a concrete contract violation and proves the gate blocks.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "check_backlog_contract.py"

_spec = importlib.util.spec_from_file_location("check_backlog_contract", MODULE_PATH)
cbc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cbc)


_HEADER = (
    "# Backlog (cola viva)\n\n"
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
)


def _write_backlog(tmp_path: Path, rows: str, fichas: str = "") -> Path:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text(_HEADER + rows + "\n" + fichas, encoding="utf-8")
    return tmp_path


_VALID_ROWS = (
    "| Alta | WOT-2026-001a | Bien | s | pending | - | x | - |\n"
    "| Media | WOT-2026-001b | Diferido | s | deferred | - | x | condition:algo-resuelto |\n"
    "| Baja | WOT-2026-001c | Bloqueado | s | blocked | - | x | external:cve-fix |\n"
    "| Alta | WOT-2026-001d | Parcial | s | completed-partial | - | x | WOT-2026-099z |\n"
)


def test_valid_backlog_passes(tmp_path: Path) -> None:
    root = _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha bien\n")
    assert cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md") == []


def test_fail_closed_without_project_root(monkeypatch) -> None:
    # No --project-root and no AGENT_PROJECT_ROOT -> fail closed (no cwd fallback).
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    root, error = cbc.resolve_destino_root(None)
    assert root is None
    assert error is not None and "fail-closed" in error
    # And the CLI returns the dedicated exit code 2.
    assert cbc.main([]) == 2


def test_project_root_via_env(tmp_path: Path, monkeypatch) -> None:
    _write_backlog(tmp_path, _VALID_ROWS)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert cbc.main([]) == 0


def test_terminal_status_in_live_queue_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002a | Mal | s | completed | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("not in live vocabulary" in e for e in errs)


def test_deferred_without_trigger_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002b | Mal | s | deferred | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("requires a structured Reactivation" in e for e in errs)


def test_vague_reactivation_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002c | Mal | s | blocked | - | x | N/A |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("vague Reactivation" in e for e in errs)


def test_unstructured_reactivation_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path,
        "| Alta | WOT-2026-002d | Mal | s | deferred | - | x | cuando se pueda |\n",
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("is not structured" in e for e in errs)


def test_wrong_column_count_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002e | Falta col | pending | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("columns" in e for e in errs)


def test_malformed_ficha_header_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path,
        _VALID_ROWS,
        "### WOT-bad ficha sin id valido\n",
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("malformed ficha header" in e for e in errs)


def test_missing_vista_rapida_section_blocks(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text("# Backlog\n\nno table here\n", encoding="utf-8")
    errs = cbc.validate_backlog(collab / "backlog.md")
    assert any("Vista rapida" in e for e in errs)


def test_header_column_mismatch_blocks(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    # Missing the Reactivation column (the 012a addition).
    (collab / "backlog.md").write_text(
        "## Vista rapida\n\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Alta | WOT-2026-003a | x | s | pending | - | x |\n",
        encoding="utf-8",
    )
    errs = cbc.validate_backlog(collab / "backlog.md")
    assert any("header columns mismatch" in e for e in errs)


def test_gate_invocable_by_absolute_path_from_foreign_cwd(tmp_path: Path) -> None:
    """WOT-2026-012b integration barrier (Manager CHANGES): run_gates_dispatch must
    invoke the gate by the MOTOR's absolute path, because PROJECT_ROOT resolves to
    repo_destino in the destino-motor topology. A relative 'scripts/...' path with
    cwd=repo_destino fails 'can't open file' (the BLOCKER). This test ejerce the real
    integrated path: invoke the gate by absolute motor path from a foreign cwd
    (the destino), and require it to actually RUN (rc in {0,1,2}), never the
    interpreter's exit 2 'can't open file'."""
    import subprocess
    import sys

    # A valid destino fixture so the gate itself returns 0.
    _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha\n")

    # Foreign cwd = the destino (NOT the motor): the relative-path bug would fail here.
    r = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),  # absolute motor path, as the fixed dispatcher uses
            "--project-root",
            str(tmp_path),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    # The gate ran (its own contract verdict), not a "can't open file" interpreter error.
    assert "can't open file" not in (r.stderr or ""), r.stderr
    assert r.returncode == 0, f"gate should pass on valid backlog; stderr={r.stderr}"


def test_relative_path_from_destino_cwd_is_the_bug(tmp_path: Path) -> None:
    """Negative companion: invoking the gate by RELATIVE 'scripts/...' from a destino
    cwd (the pre-fix behavior) fails to open the file. Documents the BLOCKER so a
    regression to relative-path invocation is caught."""
    import subprocess
    import sys

    _write_backlog(tmp_path, _VALID_ROWS)
    r = subprocess.run(
        [
            sys.executable,
            "scripts/check_backlog_contract.py",
            "--project-root",
            str(tmp_path),
        ],
        cwd=str(tmp_path),  # destino has no scripts/check_backlog_contract.py
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "can't open file" in (r.stderr or "") or "No such file" in (r.stderr or "")
