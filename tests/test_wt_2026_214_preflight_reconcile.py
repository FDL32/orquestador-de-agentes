"""Tests for WT-2026-214 preflight reconcile decision.

Tests the derive_preflight_decision() function in preflight_reconcile.py
and its integration with reconcile_ticket.py for the RECONCILE case.

TP Check coverage:
  TP-01: preflight distinguishes cleanup local from bus reconcile.
  TP-02: terminal prev ticket → CLEANUP_LOCAL (no events emitted).
  TP-03: non-terminal prev ticket → RECONCILE (reconciliation triggered).
  TP-04: bus illegible/contradictory → ABORT.
  TP-05: aligned case → ALIGNED (no regression).
  TP-06: tests pass with pytest; ruff passes on touched surfaces.
  TP-07: distinction documented as system contract.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_reconcile_ticket():
    """Load reconcile_ticket module (for Case B integration test)."""
    import sys

    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "reconcile_ticket.py"
    )
    spec = importlib.util.spec_from_file_location("reconcile_ticket", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_ticket"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("reconcile_ticket", None)
        raise
    return module


def _load_preflight_reconcile():
    """Load preflight_reconcile module."""
    import sys

    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "preflight_reconcile.py"
    )
    spec = importlib.util.spec_from_file_location("preflight_reconcile", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["preflight_reconcile"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("preflight_reconcile", None)
        raise
    return module


def _ensure_events_dir(project_root: Path) -> Path:
    events_dir = project_root / ".agent" / "runtime" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return events_dir


def _emit_event_via_raw_jsonl(
    events_dir: Path,
    ticket_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    seq: int = 1,
) -> None:
    """Write a raw JSONL event without instantiating EventBus.

    This avoids depending on EventBus being re-exported by preflight_reconcile.
    The preflight module reads raw jsonl, so this is the correct level to test.
    """
    event = {
        "event_type": event_type,
        "ticket_id": ticket_id,
        "actor": "SUPERVISOR",
        "payload": payload,
        "sequence_number": seq,
        "timestamp": "2026-06-02T12:00:00+00:00",
    }
    events_path = events_dir / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _setup_supervisor_state(project_root: Path, ticket_id: str | None) -> Path:
    """Write supervisor_state.json with optional active_ticket."""
    runtime_dir = project_root / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "active_ticket": ticket_id,
        "completed_tickets": [],
        "last_action": "RECONCILED",
        "last_processed_sequence": 0,
        "loop_current_round": 1,
        "loop_max_rounds": 0,
        "last_requeue_trigger_sequence": 0,
        "last_manager_stale_trigger_sequence": 0,
    }
    path = runtime_dir / "supervisor_state.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _setup_bridge_state(project_root: Path, ticket_id: str | None) -> Path:
    """Write manager_bridge_state.json with optional last_ticket_id."""
    runtime_dir = project_root / ".agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "last_ticket_id": ticket_id,
        "last_ticket_state": "IN_PROGRESS",
        "last_processed_sequence": 0,
        "updated_at": "2026-06-02T12:00:00+00:00",
        "heartbeat_at": "2026-06-02T12:00:00+00:00",
    }
    path = runtime_dir / "manager_bridge_state.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ===========================================================================
# TP-05: Aligned case
# ===========================================================================


def test_no_runtime_state_returns_aligned(tmp_path: Path) -> None:
    """No supervisor/bridge state → no prev ticket → ALIGNED."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
    )

    assert decision["decision"] == "ALIGNED"
    assert decision["prev_ticket_id"] is None
    assert decision["bus_ok"] is True


def test_same_ticket_returns_aligned(tmp_path: Path) -> None:
    """supervisor_state points to same ticket as work plan → ALIGNED."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    _setup_supervisor_state(project_root, "WT-2026-214")

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-214"},
    )

    assert decision["decision"] == "ALIGNED"
    assert decision["prev_ticket_id"] == "WT-2026-214"
    assert decision["bus_ok"] is True


# ===========================================================================
# TP-02: Terminal prev ticket → CLEANUP_LOCAL
# ===========================================================================


def test_terminal_prev_ticket_returns_cleanup(tmp_path: Path) -> None:
    """Prev ticket COMPLETED in bus → CLEANUP_LOCAL, no events emitted."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    # Emit events for WT-2026-205 ending in COMPLETED via raw jsonl
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
        seq=1,
    )
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "IN_PROGRESS",
            "to_state": "COMPLETED",
            "reason": "completed",
            "source": "test",
        },
        seq=2,
    )
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "CLOSE_CONFIRMED",
        {
            "reason": "test close",
            "source": "test",
        },
        seq=3,
    )

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )

    assert decision["decision"] == "CLEANUP_LOCAL", (
        f"Expected CLEANUP_LOCAL, got {decision['decision']}: {decision['reason']}"
    )
    assert decision["prev_ticket_id"] == "WT-2026-205"
    assert decision["prev_ticket_state"] == "COMPLETED"
    assert decision["bus_ok"] is True


def test_terminal_via_supervisor_closed(tmp_path: Path) -> None:
    """Prev ticket with STATE_CHANGED→COMPLETED → CLEANUP_LOCAL."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
        seq=1,
    )
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "IN_PROGRESS",
            "to_state": "COMPLETED",
            "reason": "completed by reconciler",
            "source": "reconcile_ticket",
        },
        seq=2,
    )

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
        bridge_state={"last_ticket_id": "WT-2026-205"},
    )

    assert decision["decision"] == "CLEANUP_LOCAL"
    assert decision["prev_ticket_state"] == "COMPLETED"


# ===========================================================================
# TP-03: Non-terminal prev ticket → RECONCILE
# ===========================================================================


def test_non_terminal_prev_ticket_returns_reconcile(tmp_path: Path) -> None:
    """Prev ticket IN_PROGRESS in bus → RECONCILE."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
        seq=1,
    )

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )

    assert decision["decision"] == "RECONCILE", (
        f"Expected RECONCILE, got {decision['decision']}: {decision['reason']}"
    )
    assert decision["prev_ticket_id"] == "WT-2026-205"
    assert decision["prev_ticket_state"] == "IN_PROGRESS"
    assert decision["bus_ok"] is True


def test_non_terminal_in_review_returns_reconcile(tmp_path: Path) -> None:
    """Prev ticket READY_FOR_REVIEW in bus → RECONCILE."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "bootstrap",
            "source": "bootstrap",
        },
        seq=1,
    )
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "review ready",
            "source": "builder",
        },
        seq=2,
    )

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )

    assert decision["decision"] == "RECONCILE"
    assert decision["prev_ticket_state"] == "READY_FOR_REVIEW"


# ===========================================================================
# TP-04: Bus illegible → ABORT
# ===========================================================================


def test_no_events_for_prev_ticket_returns_abort(tmp_path: Path) -> None:
    """Prev ticket has no bus events → ABORT."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    # Create empty events file (no events for prev ticket)
    (events_dir / "events.jsonl").write_text("", encoding="utf-8")

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )

    assert decision["decision"] == "ABORT", (
        f"Expected ABORT, got {decision['decision']}: {decision['reason']}"
    )
    assert decision["prev_ticket_id"] == "WT-2026-205"
    assert decision["bus_ok"] is False
    assert "No bus events found" in decision["reason"]


def test_no_events_file_returns_abort(tmp_path: Path) -> None:
    """No events.jsonl file exists → ABORT."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    # Don't create events dir at all

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )

    assert decision["decision"] == "ABORT"
    assert decision["bus_ok"] is False


def test_supervisor_state_none_but_bridge_stale_aborts(tmp_path: Path) -> None:
    """Bridge state points to stale ticket with no bus events → ABORT."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    _ensure_events_dir(project_root)

    decision = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        bridge_state={"last_ticket_id": "WT-2026-205"},
    )

    assert decision["decision"] == "ABORT"
    assert decision["prev_ticket_id"] == "WT-2026-205"


# ===========================================================================
# TP-01: Distinction between cleanup and reconcile (architectural)
# ===========================================================================


def test_preflight_returns_distinct_decisions(tmp_path: Path) -> None:
    """Preflight returns three distinct decisions: ALIGNED, CLEANUP_LOCAL, RECONCILE."""
    mod = _load_preflight_reconcile()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)

    # Decision 1: ALIGNED (no drift)
    d1 = mod.derive_preflight_decision(
        project_root=project_root, work_plan_id="WT-2026-214"
    )
    assert d1["decision"] == "ALIGNED"

    # Decision 2: CLEANUP_LOCAL (prev ticket terminal)
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "COMPLETED",
            "reason": "done",
            "source": "test",
        },
        seq=1,
    )
    d2 = mod.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )
    assert d2["decision"] == "CLEANUP_LOCAL"

    # Decision 3: RECONCILE (prev ticket non-terminal)
    project_root2 = tmp_path / "case_reconcile"
    events_dir2 = _ensure_events_dir(project_root2)
    _emit_event_via_raw_jsonl(
        events_dir2,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "started",
            "source": "test",
        },
        seq=1,
    )
    d3 = mod.derive_preflight_decision(
        project_root=project_root2,
        work_plan_id="WT-2026-214",
        supervisor_state={"active_ticket": "WT-2026-205"},
    )
    assert d3["decision"] == "RECONCILE"


# ===========================================================================
# Case B Integration: RECONCILE → actual reconcile_ticket on same path
# ===========================================================================


def test_reconcile_invocation_integration(tmp_path: Path) -> None:
    """RECONCILE decision → reconcile_ticket() works on same runtime path.

    Verifies that when derive_preflight_decision returns RECONCILE,
    calling reconcile_ticket() on the same project_root successfully
    closes the ticket (emits terminal events and cleans artifacts).
    """
    preflight = _load_preflight_reconcile()
    reconciler = _load_reconcile_ticket()
    project_root = tmp_path
    events_dir = _ensure_events_dir(project_root)
    runtime_dir = project_root / ".agent" / "runtime"

    # Emit non-terminal events for prev ticket WT-2026-205 via raw jsonl.
    # The preflight reads raw jsonl; the reconciler uses EventBus which
    # also reads the same jsonl.
    _emit_event_via_raw_jsonl(
        events_dir,
        "WT-2026-205",
        "STATE_CHANGED",
        {
            "from_state": "BOOTSTRAP",
            "to_state": "IN_PROGRESS",
            "reason": "test bootstrap",
            "source": "test",
        },
        seq=1,
    )

    # Set up runtime state pointing to the old (stale) ticket
    _setup_supervisor_state(project_root, "WT-2026-205")

    # Create stal lock files that the reconciler should clean
    (runtime_dir / "builder_lock.txt").write_text(
        json.dumps({"ticket_id": "WT-2026-205"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (runtime_dir / "supervisor_lock.txt").write_text(
        json.dumps({"ticket_id": "WT-2026-205"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 1. Preflight decision → RECONCILE
    supervisor_state = preflight._load_json(
        project_root / preflight.SUPERVISOR_STATE_REL
    )
    decision = preflight.derive_preflight_decision(
        project_root=project_root,
        work_plan_id="WT-2026-214",
        supervisor_state=supervisor_state,
    )
    assert decision["decision"] == "RECONCILE", (
        f"Preflight must decide RECONCILE for non-terminal prev ticket. "
        f"Got: {decision['decision']}: {decision['reason']}"
    )

    # 2. Call reconcile_ticket() directly on the same path
    result = reconciler.reconcile_ticket(
        project_root, "WT-2026-205", reason="preflight test", dry_run=False
    )

    # 3. Verify reconciliation completed
    assert result.after_state in {"COMPLETED", "CLOSED"}, (
        f"Reconciliation must produce terminal state. Got: {result.after_state}"
    )
    assert (
        "STATE_CHANGED->COMPLETED" in result.events_emitted
        or "SUPERVISOR_CLOSED" in result.events_emitted
    )
    assert result.cleaned_artifacts, "Reconciliation must clean at least some artifacts"

    # 4. Verify supervisor state updated
    supervisor_state_after = reconciler._load_json(
        runtime_dir / "supervisor_state.json"
    )
    assert supervisor_state_after is not None
    assert supervisor_state_after["active_ticket"] is None
    assert "WT-2026-205" in supervisor_state_after["completed_tickets"]
