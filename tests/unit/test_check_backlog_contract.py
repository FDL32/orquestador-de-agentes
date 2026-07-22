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


def test_ficha_redeclaring_flt_blocks(tmp_path: Path) -> None:
    """WOT-2026-013j: a detailed ficha that re-declares 'Files Likely Touched'
    must be blocked. The FLT is owned by the frozen contract, not the backlog.

    FAIL-without-fix: the gate only checked the table + ficha headers, so a
    declarative FLT bullet in the ficha body passed silently (the recurring
    013h/013i drift). PASS-with-fix: the gate fails closed naming the ficha.
    """
    ficha = (
        "### WOT-2026-001a - ficha que re-declara FLT\n"
        "- **Problema:** algo\n"
        "- **Files Likely Touched:**\n"
        "  - repo_motor: `scripts/foo.py`\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, ficha)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("re-declares 'Files Likely Touched'" in e for e in errs), errs
    assert any("WOT-2026-001a" in e for e in errs), errs


def test_ficha_prose_mention_of_flt_is_allowed(tmp_path: Path) -> None:
    """Negative companion: merely MENTIONING 'Files Likely Touched' in prose
    inside another bullet (not as a declarative key) must NOT be blocked. The
    ficha may reference the concept; it just may not own the FLT declaration.
    """
    ficha = (
        "### WOT-2026-001a - ficha que solo menciona FLT en prosa\n"
        "- **Problema:** las fichas re-declaran el `Files Likely Touched` "
        "que vive en el contrato frozen.\n"
        "- **Objetivo:** definir una sola fuente de verdad.\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, ficha)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert not any("re-declares 'Files Likely Touched'" in e for e in errs), errs


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


# ---------------------------------------------------------------------------
# WOT-2026-027t: the live queue must not fragment -- a ticket row OUTSIDE the
# 'Vista rapida' table (e.g. drifted under '## Fichas detalladas') is fail-closed.
# ---------------------------------------------------------------------------


def test_ticket_row_outside_table_blocks(tmp_path: Path) -> None:
    """The fragmentation trap: a well-formed 8-cell ticket row placed AFTER the
    Vista rapida table (under a later section) is invisible to the extractor, so
    the old contract 'held' over half the queue. The guard now fails closed and
    names the drifted row and its line.

    FAIL-without-fix (mutation): remove the `_ticket_rows_outside_table` call from
    validate_backlog -> this row passes silently, exactly the WOT-2026-027t defect.
    """
    fichas = (
        "### WOT-2026-001a - ficha\n\n"
        "| Alta | WOT-2026-099z | fuera de tabla | s | pending | - | x | - |\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, fichas)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("WOT-2026-099z" in e and "OUTSIDE" in e for e in errs), errs


def test_all_ticket_rows_inside_table_passes(tmp_path: Path) -> None:
    """Negative companion: when every ticket row lives inside the Vista rapida
    table, the fragmentation check adds no violation."""
    root = _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha\n")
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert not any("OUTSIDE" in e for e in errs), errs


def test_dependency_cell_citing_ticket_id_is_not_a_stray_row(tmp_path: Path) -> None:
    """Cell-based, never substring: a ficha bullet or a table cell that MENTIONS a
    ticket id in prose (e.g. a 'Depende de' reference) is NOT a ticket row -- only
    a row whose SECOND cell IS a bare id counts. A substring scan would false-flag
    the mention; this test dies under that mutation."""
    fichas = (
        "### WOT-2026-001a - ficha\n"
        "- **Depende de:** WOT-2026-099z (citado en prosa, no es una fila)\n"
        "- Una tabla ajena de otro esquema:\n"
        "| campo | WOT-2026-099z como dato | otro |\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, fichas)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    # The prose mention and the foreign-table cell (id in cell[2] but as free text
    # 'WOT-2026-099z como dato', not a bare id) must not be flagged as stray rows.
    assert not any("OUTSIDE" in e for e in errs), errs


# ---------------------------------------------------------------------------
# WOT-2026-023o: STATE.md ACTIVE_TICKET vs the scheduling surfaces (bus projection)
# ---------------------------------------------------------------------------

_ARCHIVE_HEADER = "# Backlog -- historico\n\n"


def _write_state(root: Path, ticket: str, status: str) -> None:
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        f"ACTIVE_TICKET: {ticket}\nSTATUS: {status}\n", encoding="utf-8"
    )


def _write_archive(root: Path, rows: str) -> None:
    """Archive layout: ID in the FIRST cell (no Prioridad column), unlike the
    live backlog where it is the SECOND cell. This is the two-layout trap."""
    arch = root / ".agent" / "collaboration" / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "backlog_done.md").write_text(_ARCHIVE_HEADER + rows, encoding="utf-8")


def test_active_ticket_ghost_blocks(tmp_path: Path) -> None:
    """A ghost ACTIVE_TICKET (no row in backlog nor archive) is a violation
    regardless of STATUS: the bus projection declares active something no
    scheduling surface knows."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_state(tmp_path, "WOT-2026-999z", "IN_PROGRESS")
    errs = cbc.validate_active_ticket_state(tmp_path)
    assert any("ghost" in e and "WOT-2026-999z" in e for e in errs), errs


def test_active_ticket_non_terminal_archive_only_blocks(tmp_path: Path) -> None:
    """The WOT-2026-022i incident: STATE.md declares a NON-terminal STATUS
    (READY_FOR_REVIEW) over a ticket that only exists in the archive."""
    _write_backlog(tmp_path, _VALID_ROWS)  # no live row for the archived ticket
    _write_archive(
        tmp_path, "| WOT-2026-022i | completed | archived | - | x | commit:9b852a1 |\n"
    )
    _write_state(tmp_path, "WOT-2026-022i", "READY_FOR_REVIEW")
    errs = cbc.validate_active_ticket_state(tmp_path)
    assert any(
        "only exists in the archive" in e and "WOT-2026-022i" in e for e in errs
    ), errs


def test_active_ticket_terminal_archive_only_passes(tmp_path: Path) -> None:
    """Complement: a COMPLETED (terminal) STATUS pointing to an archived ticket
    is the normal post-close residual -- must NOT block. Distinguishing this from
    the non-terminal case above is the whole point of the STATUS sensitivity."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive(
        tmp_path, "| WOT-2026-022i | completed | archived | - | x | commit:9b852a1 |\n"
    )
    _write_state(tmp_path, "WOT-2026-022i", "COMPLETED")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_active_ticket_live_row_passes(tmp_path: Path) -> None:
    """A non-terminal STATUS pointing to a ticket present in the LIVE backlog is
    exactly the healthy case."""
    _write_backlog(tmp_path, _VALID_ROWS)  # 001a is a live 'pending' row
    _write_state(tmp_path, "WOT-2026-001a", "IN_PROGRESS")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_layout_archive_id_first_cell_is_found(tmp_path: Path) -> None:
    """Two-layout trap: the archived ID sits in the FIRST cell. The cell-scan
    finds it (terminal STATUS -> passes). A parser anchored on cell[1] would miss
    it and raise a false ghost -- this test dies under that positional mutation."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive(
        tmp_path, "| WOT-2026-070x | completed | nota | - | x | commit:abc |\n"
    )
    _write_state(tmp_path, "WOT-2026-070x", "COMPLETED")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_layout_backlog_id_second_cell_is_found(tmp_path: Path) -> None:
    """Two-layout trap, other side: the live-backlog ID sits in the SECOND cell
    (after Prioridad). A parser anchored on cell[0] would read the priority and
    raise a false ghost -- this test dies under that positional mutation."""
    _write_backlog(tmp_path, _VALID_ROWS)  # 001b in cell[1] after 'Media'
    _write_state(tmp_path, "WOT-2026-001b", "IN_PROGRESS")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_no_state_md_not_applicable(tmp_path: Path) -> None:
    _write_backlog(tmp_path, _VALID_ROWS)
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_state_md_without_active_ticket_not_applicable(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text("STATUS: UNKNOWN\n", encoding="utf-8")
    _write_backlog(tmp_path, _VALID_ROWS)
    assert cbc.validate_active_ticket_state(tmp_path) == []
