"""Barrier tests for check_closeout_reconciliation.py (WOT-2026-015l).

The gate reconciles the workspace backlog against the SUPERVISOR_CLOSED events of
the WORKSPACE bus (never the motor's). It must catch, bidirectionally:
  A (drift):           a ticket closed in the bus that is still live in backlog.
  B (orphan_declared): a ticket declared terminal in backlog_done that had bus
                       activity but never received SUPERVISOR_CLOSED.
It must exempt genuinely pre-bus history (zero bus events), read live+archive as
a union, and FAIL CLOSED when the project root or bus is missing. Each barrier
test carries a MUTATION note proving the assert is the barrier.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "check_closeout_reconciliation.py"

_spec = importlib.util.spec_from_file_location(
    "check_closeout_reconciliation", MODULE_PATH
)
ccr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccr)


_BACKLOG_HEADER = (
    "# Backlog (cola viva)\n\n"
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
)

_DONE_HEADER = (
    "# Backlog -- historico\n\n"
    "## Cierres\n\n"
    "| Ticket | Estado | Nota |\n"
    "|--------|--------|------|\n"
)


def _event(ticket: str, event_type: str, seq: int) -> str:
    return json.dumps(
        {
            "event_type": event_type,
            "ticket_id": ticket,
            "actor": "SUPERVISOR",
            "sequence_number": seq,
        }
    )


def _make_workspace(
    tmp_path: Path,
    *,
    live_rows: str = "",
    done_rows: str = "",
    live_events: list[str] | None = None,
    archive_events: dict[str, list[str]] | None = None,
) -> Path:
    """Build a synthetic workspace tree with bus + backlog + backlog_done."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text(_BACKLOG_HEADER + live_rows, encoding="utf-8")
    archive_dir = collab / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "backlog_done.md").write_text(
        _DONE_HEADER + done_rows, encoding="utf-8"
    )

    events_dir = tmp_path / ".agent" / "runtime" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "events.jsonl").write_text(
        "\n".join(live_events or []) + ("\n" if live_events else ""),
        encoding="utf-8",
    )
    bus_archive = events_dir / "archive"
    bus_archive.mkdir(parents=True, exist_ok=True)
    for name, lines in (archive_events or {}).items():
        (bus_archive / f"events.{name}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return tmp_path


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------
def test_coherent_backlog_and_bus_passes(tmp_path: Path) -> None:
    root = _make_workspace(
        tmp_path,
        live_rows="| Alta | WOT-2026-050a | vivo | s | pending | - | x | - |\n",
        done_rows="| WOT-2026-049a | completed | cerrado ok |\n",
        live_events=[_event("WOT-2026-049a", "SUPERVISOR_CLOSED", 10)],
    )
    report = ccr.run_gate(root)
    assert report["all_pass"] is True
    assert report["checks"]["drift"]["pass"] is True
    assert report["checks"]["orphan_declared"]["pass"] is True


# --------------------------------------------------------------------------
# Fixture A: drift (closed in bus, still live in backlog)
# --------------------------------------------------------------------------
def test_drift_closed_in_bus_but_still_live(tmp_path: Path) -> None:
    root = _make_workspace(
        tmp_path,
        live_rows="| Alta | WOT-2026-060a | aun vivo | s | pending | - | x | - |\n",
        live_events=[_event("WOT-2026-060a", "SUPERVISOR_CLOSED", 20)],
    )
    report = ccr.run_gate(root)
    # MUTATION: if run_gate stopped intersecting closed_bus & live_backlog (the A
    # assert), drift would be empty and this test would go green spuriously.
    assert report["checks"]["drift"]["pass"] is False
    ids = [f["ticket_id"] for f in report["checks"]["drift"]["findings"]]
    assert ids == ["WOT-2026-060a"]
    assert report["checks"]["drift"]["findings"][0]["sequence_number"] == 20
    assert report["all_pass"] is False


def test_completed_partial_is_not_drift(tmp_path: Path) -> None:
    # completed-partial is a legitimate live state that may carry a historic
    # SUPERVISOR_CLOSED for its closed part -> NOT drift.
    root = _make_workspace(
        tmp_path,
        live_rows=(
            "| Alta | WOT-2026-061a | parcial | s | completed-partial | - | x "
            "| WOT-2026-099z |\n"
        ),
        live_events=[_event("WOT-2026-061a", "SUPERVISOR_CLOSED", 21)],
    )
    report = ccr.run_gate(root)
    assert report["checks"]["drift"]["pass"] is True


# --------------------------------------------------------------------------
# Fixture B: orphan_declared (declared done, bus activity, no SUPERVISOR_CLOSED)
# --------------------------------------------------------------------------
def test_orphan_declared_done_without_closed_event(tmp_path: Path) -> None:
    root = _make_workspace(
        tmp_path,
        done_rows="| WOT-2026-070a | completed | dice cerrado |\n",
        # Bus activity for the ticket, but NO SUPERVISOR_CLOSED.
        live_events=[_event("WOT-2026-070a", "STATE_CHANGED", 30)],
    )
    report = ccr.run_gate(root)
    # MUTATION: if run_gate stopped computing (declared_done & present) - closed
    # (the B assert), orphan_declared would be empty and this test go green.
    assert report["checks"]["orphan_declared"]["pass"] is False
    ids = [f["ticket_id"] for f in report["checks"]["orphan_declared"]["findings"]]
    assert ids == ["WOT-2026-070a"]
    assert report["all_pass"] is False


def test_prebus_declared_is_exempt(tmp_path: Path) -> None:
    # A ticket declared terminal with ZERO bus events is pre-bus legacy, not an
    # auto-report -> exempt from check B.
    root = _make_workspace(
        tmp_path,
        done_rows="| WOT-2026-001a | completed | legado pre-bus |\n",
        live_events=[_event("WOT-2026-050a", "SUPERVISOR_CLOSED", 5)],
    )
    report = ccr.run_gate(root)
    assert report["checks"]["orphan_declared"]["pass"] is True
    assert report["prebus_exempt_count"] == 1


# --------------------------------------------------------------------------
# Union live + archive
# --------------------------------------------------------------------------
def test_archive_only_close_counts_as_closed(tmp_path: Path) -> None:
    # A SUPERVISOR_CLOSED that lives ONLY in archive/*.jsonl must count as closed:
    # otherwise a still-live backlog row for it would be a false negative.
    root = _make_workspace(
        tmp_path,
        live_rows="| Alta | WOT-2026-080a | aun vivo | s | pending | - | x | - |\n",
        live_events=[],
        archive_events={
            "WOT-2026-080a": [_event("WOT-2026-080a", "SUPERVISOR_CLOSED", 40)]
        },
    )
    report = ccr.run_gate(root)
    # MUTATION: if read_bus dropped the archive glob, closed would be empty and
    # drift would miss this -> false negative. The assert is the barrier.
    assert report["checks"]["drift"]["pass"] is False
    ids = [f["ticket_id"] for f in report["checks"]["drift"]["findings"]]
    assert ids == ["WOT-2026-080a"]


# --------------------------------------------------------------------------
# Fail-closed
# --------------------------------------------------------------------------
def test_fail_closed_without_project_root(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    with pytest.raises(ccr.ReconcileError):
        ccr.resolve_project_root(None)
    # CLI returns exit 1 (no cwd fallback, no pass-open).
    assert ccr.main([]) == 1


def test_fail_closed_when_bus_absent(tmp_path: Path) -> None:
    # Workspace with backlog but NO runtime/events at all -> fail closed.
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text(_BACKLOG_HEADER, encoding="utf-8")
    with pytest.raises(ccr.ReconcileError):
        ccr.run_gate(tmp_path)


def test_env_var_resolves_project_root(tmp_path: Path, monkeypatch) -> None:
    root = _make_workspace(
        tmp_path,
        live_events=[_event("WOT-2026-050a", "SUPERVISOR_CLOSED", 1)],
    )
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(root))
    assert ccr.resolve_project_root(None) == root.resolve()


# --------------------------------------------------------------------------
# CLI exit codes
# --------------------------------------------------------------------------
def test_cli_exit_zero_on_clean(tmp_path: Path) -> None:
    root = _make_workspace(
        tmp_path,
        live_events=[_event("WOT-2026-050a", "SUPERVISOR_CLOSED", 1)],
    )
    assert ccr.main(["--project-root", str(root)]) == 0


def test_cli_exit_one_on_violation(tmp_path: Path) -> None:
    root = _make_workspace(
        tmp_path,
        live_rows="| Alta | WOT-2026-060a | vivo | s | pending | - | x | - |\n",
        live_events=[_event("WOT-2026-060a", "SUPERVISOR_CLOSED", 2)],
    )
    assert ccr.main(["--project-root", str(root), "--json"]) == 1
