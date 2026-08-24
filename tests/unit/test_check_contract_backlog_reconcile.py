"""Barrier tests for check_contract_backlog_reconcile.py (WOT-2026-024e).

The gate must list every FROZEN contract in ticket_contracts.md that has no row in
the live backlog nor the archive (the batch reads only backlog.md, so it can never
execute an orphan). It must: scope to `**status:** frozen` (excluding operational
`Frozen at HEAD` registrations), key on `ticket_id:` (header only as fallback, never
body WOT enumeration), and resolve rows across BOTH table layouts.
"""

from __future__ import annotations

import json
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


def _write_link(root: Path, prefix: str) -> None:
    """Write a motor_destination_link.json declaring the given ticket_prefix."""
    d = root / ".agent" / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "motor_destination_link.json").write_text(
        json.dumps({"ticket_prefix": prefix}), encoding="utf-8"
    )


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


# --- WOT-2026-055g: prefix from resolver, not hardcoded WOT --------------------


def test_non_wot_frozen_orphan_detected(tmp_path: Path, monkeypatch) -> None:
    """DoD 2: a frozen contract with a NON-WOT prefix (CTL) and no row is detected
    when the destination link declares that prefix."""
    _write_link(tmp_path, "CTL")
    _write_contracts(tmp_path, _frozen_block("CTL-2026-010a", "CTL-2026-010a"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == ["CTL-2026-010a"]
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert main([]) == 1


def test_mutation_wot_literal_breaks_non_wot_detection(tmp_path: Path) -> None:
    """DoD 3: if find_frozen_ids is called with prefix='WOT' (the mutation),
    a CTL contract is invisible -- proving the prefix parameter matters.

    This test verifies the MUTATION PROPERTY only: WOT prefix cannot see
    non-WOT contracts.  The correct behavior (CTL prefix sees CTL contracts)
    is verified by test_non_wot_frozen_orphan_detected (DoD 2).
    """
    _write_contracts(tmp_path, _frozen_block("CTL-2026-010a", "CTL-2026-010a"))
    contracts_text = (tmp_path / ".agent/planning/ticket_contracts.md").read_text()
    # Mutated: hardcoded WOT -> CTL contract is invisible
    assert find_frozen_ids(contracts_text, "WOT") == []


def test_wot_destination_frozen_with_row_no_orphan(tmp_path: Path, monkeypatch) -> None:
    """DoD 4: a WOT destination with a frozen contract that HAS a row -> exit 0."""
    _write_link(tmp_path, "WOT")
    _write_contracts(tmp_path, _frozen_block("WOT-2026-001a", "WOT-2026-001a"))
    _write_backlog(tmp_path, "| Alta | WOT-2026-001a | t | s | pending | - | x | - |\n")
    assert find_orphans(tmp_path) == []
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert main([]) == 0


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WOT-2026-058p: el gate perdia en SILENCIO los contratos de prefijo legacy
# cuando el destino declara `ticket_prefix`. AGENTS.md declara `WP-`/`WT-` como
# `legacy-compat` que los consumidores DEBEN aceptar; el gate los invisibilizaba
# y salia VERDE sin haberlos mirado -- un falso cierre, no un rechazo.
# ---------------------------------------------------------------------------


def _frozen_058p(ticket: str) -> str:
    """Un bloque de contrato `frozen` minimo para `find_frozen_ids`."""
    return f"## {ticket}\n\n**status:** frozen\n\nticket_id: {ticket}\n\n"


_FROZEN_PAIR = _frozen_058p("WT-2026-248a") + _frozen_058p("WOT-2026-099x")


def test_058p_legacy_prefix_is_visible_under_declared_prefix() -> None:
    """DoD (a)+(b): con `prefix='WOT'`, un contrato `frozen` de prefijo
    legacy-compat DEBE verse.

    Medido 2026-08-22 ANTES del fix: `find_frozen_ids(pair, 'WOT')` devolvia
    solo `['WOT-2026-099x']` -- el contrato `WT-` no se cruzaba contra el
    backlog y el gate salia VERDE sin haberlo mirado.
    """
    from scripts.check_contract_backlog_reconcile import find_frozen_ids

    assert find_frozen_ids(_FROZEN_PAIR, "WOT") == ["WT-2026-248a", "WOT-2026-099x"]


def test_058p_foreign_non_legacy_prefix_stays_invisible() -> None:
    """DoD (c) CONTROL NEGATIVO: un prefijo AJENO y no-legacy (`CTL-`) sigue SIN
    aparecer.

    Sin este par, el test de arriba pasaria con un guard que hubiera degradado
    al patron generico -- que es exactamente lo que NO se quiere: el destino
    `Crear_Texto_LLM` usa `CTL-` y sus contratos no son de este destino.
    """
    from scripts.check_contract_backlog_reconcile import find_frozen_ids

    assert find_frozen_ids(_frozen_058p("CTL-2026-001a"), "WOT") == []


def test_058p_none_prefix_fallback_unchanged() -> None:
    """NON-GOAL declarado en la ficha: el fallback de `prefix is None` es
    correcto y NO se toca. Pineado para que un cambio futuro lo note."""
    from scripts.check_contract_backlog_reconcile import find_frozen_ids

    assert find_frozen_ids(_FROZEN_PAIR, None) == ["WT-2026-248a", "WOT-2026-099x"]
