"""Barrier tests for check_contract_backlog_reconcile.py (WOT-2026-024e).

The gate must list every FROZEN contract in ticket_contracts.md that has no row in
the live backlog nor the archive (the batch reads only backlog.md, so it can never
execute an orphan). It must: scope to `**status:** frozen` (excluding operational
`Frozen at HEAD` registrations), key on `ticket_id:` (header only as fallback, never
body WOT enumeration), and resolve rows across BOTH table layouts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_contract_backlog_reconcile import (
    find_frozen_ids,
    find_orphans,
    main,
)
from scripts.prepush_check import run_contract_reconcile_check


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "check_contract_backlog_reconcile.py"

_BACKLOG_HEADER = (
    "# Backlog (cola viva)\n\n"
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|---|---|---|---|---|---|---|---|\n"
)
_ARCHIVE_HEADER = "# Backlog -- historico\n\n"


def _write_contracts(root: Path, body: str) -> None:
    d = root / ".agent" / "planning"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ticket_contracts.md").write_text(body, encoding="utf-8")


def _write_backlog(root: Path, rows: str) -> None:
    d = root / ".agent" / "collaboration"
    d.mkdir(parents=True, exist_ok=True)
    (d / "backlog.md").write_text(_BACKLOG_HEADER + rows, encoding="utf-8")


def _write_archive(root: Path, rows: str) -> None:
    """Archive layout: ID in the FIRST cell (no Prioridad)."""
    d = root / ".agent" / "collaboration" / "_archive"
    d.mkdir(parents=True, exist_ok=True)
    (d / "backlog_done.md").write_text(_ARCHIVE_HEADER + rows, encoding="utf-8")


def _frozen_block(header_id: str, ticket_id: str | None, body: str = "") -> str:
    tid_line = f"- **ticket_id:** {ticket_id}\n" if ticket_id else ""
    return (
        f"## Contrato T-X -- {header_id}\n\n{tid_line}- **status:** frozen\n{body}\n\n"
    )


def test_frozen_scope_detects_status_frozen(tmp_path: Path) -> None:
    _write_contracts(tmp_path, _frozen_block("WOT-2026-001a", "WOT-2026-001a"))
    assert find_frozen_ids(
        (tmp_path / ".agent/planning/ticket_contracts.md").read_text()
    ) == ["WOT-2026-001a"]


def test_frozen_with_row_no_orphan(tmp_path: Path) -> None:
    _write_contracts(tmp_path, _frozen_block("WOT-2026-001a", "WOT-2026-001a"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == []


def test_frozen_orphan_is_listed_and_exit_1(tmp_path: Path, monkeypatch) -> None:
    """A frozen contract with no row anywhere -> orphan -> exit 1.

    Mutation-to-prove (DoD c): drop the presence check and this stops failing.
    """
    _write_contracts(tmp_path, _frozen_block("WOT-2026-002z", "WOT-2026-002z"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-999a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == ["WOT-2026-002z"]
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert main([]) == 1


def test_orphan_row_added_passes(tmp_path: Path, monkeypatch) -> None:
    _write_contracts(tmp_path, _frozen_block("WOT-2026-002z", "WOT-2026-002z"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-002z | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == []
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert main([]) == 0


def test_header_fallback_when_no_ticket_id(tmp_path: Path) -> None:
    """No ticket_id: field -> the id comes from the header line (fallback), and an
    orphan is still caught."""
    _write_contracts(tmp_path, _frozen_block("WOT-2026-003z", ticket_id=None))
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == ["WOT-2026-003z"]


def test_frozen_at_head_registration_is_out_of_scope(tmp_path: Path) -> None:
    """A block marked only `Frozen at HEAD` (operational flight registration) with no
    `status: frozen` is NOT a frozen contract -- excluded even with no row."""
    body = (
        "## Contrato T-Y -- WOT-2026-050a\n\n"
        "- **deliverable_type:** code. **Frozen at HEAD:** abc1234.\n\n"
    )
    _write_contracts(tmp_path, body)
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    assert find_frozen_ids(body) == []
    assert find_orphans(tmp_path) == []


def test_body_dependency_wot_is_not_enumerated(tmp_path: Path) -> None:
    """A frozen contract for WOT-004a (with row) whose BODY cites WOT-777b (a
    dependency, no row) must NOT flag WOT-777b: only the contract's own id counts."""
    block = _frozen_block(
        "WOT-2026-004a",
        "WOT-2026-004a",
        body="- **Depende de:** WOT-2026-777b (sin fila)\n",
    )
    _write_contracts(tmp_path, block)
    _write_backlog(tmp_path, "| Alta | WOT-2026-004a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == []


def test_row_in_archive_first_cell_layout_no_orphan(tmp_path: Path) -> None:
    """Two-layout reuse: a frozen contract whose only row is in the archive (ID in
    cell[0]) is found -> not an orphan. A cell[1]-anchored parser would false-flag it."""
    _write_contracts(tmp_path, _frozen_block("WOT-2026-005c", "WOT-2026-005c"))
    _write_archive(
        tmp_path, "| WOT-2026-005c | completed | nota | - | x | commit:abc |\n"
    )
    assert find_orphans(tmp_path) == []


def test_cli_import_runs_by_subprocess(tmp_path: Path) -> None:
    """DoD (f): the guard runs as a real CLI -- the `from scripts.check_backlog_contract
    import _ticket_has_row` (which drags bus.state_machine) must not break execution."""
    _write_contracts(tmp_path, _frozen_block("WOT-2026-006d", "WOT-2026-006d"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-006d | t | s | pending | - | x | - |\n")
    r = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert "ImportError" not in (r.stderr or ""), r.stderr
    assert "Traceback" not in (r.stderr or ""), r.stderr
    assert r.returncode == 0, f"stdout={r.stdout} stderr={r.stderr}"


# --- Wiring: WARN default vs FAIL opt-in (DoD e, anti-M20) --------------------


def _orphan_root(tmp_path: Path) -> Path:
    _write_contracts(tmp_path, _frozen_block("WOT-2026-007e", "WOT-2026-007e"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    return tmp_path


def test_wiring_warn_default_reports_but_does_not_block(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CONTRACT_RECONCILE_STRICT", raising=False)
    res = run_contract_reconcile_check(_orphan_root(tmp_path))
    assert res.passed is False  # the orphan is reported
    assert res.is_blocking is False  # ...but WARN default does not fail the close
    assert "WOT-2026-007e" in res.output


def test_wiring_strict_opt_in_blocks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CONTRACT_RECONCILE_STRICT", "1")
    res = run_contract_reconcile_check(_orphan_root(tmp_path))
    assert res.passed is False
    assert res.is_blocking is True  # FAIL opt-in makes the same orphan block
    assert "WOT-2026-007e" in res.output
