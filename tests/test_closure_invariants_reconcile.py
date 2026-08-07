"""Tests for closure_invariants filtering of reconcile_ticket synthetic events.

WOT-2026-050a: BUILDER_EXIT with source=reconcile_ticket must NOT satisfy the
closure invariant. Only real BUILDER_EXIT events (without reconcile source)
should count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_closure_invariants():
    import sys

    module_path = (
        Path(__file__).resolve().parents[1] / ".agent" / "closure_invariants.py"
    )
    spec = importlib.util.spec_from_file_location("closure_invariants", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["closure_invariants"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("closure_invariants", None)
        raise
    return module


def _make_event(event_type, ticket_id, payload, sequence_number=1):
    """Create a mock event object."""
    from dataclasses import dataclass

    @dataclass
    class MockEvent:
        event_type: str
        ticket_id: str
        payload: dict
        sequence_number: int

    return MockEvent(
        event_type=event_type,
        ticket_id=ticket_id,
        payload=payload,
        sequence_number=sequence_number,
    )


class MockEventBus:
    """Minimal event bus for testing closure invariants."""

    def __init__(self, events):
        self._events = events

    def read_events(self, ticket_id=None, event_type=None):
        result = self._events
        if ticket_id:
            result = [e for e in result if e.ticket_id == ticket_id]
        if event_type:
            result = [e for e in result if e.event_type == event_type]
        return result

    def latest_event(self, ticket_id=None, event_type=None):
        events = self.read_events(ticket_id=ticket_id, event_type=event_type)
        return events[-1] if events else None


def test_reconciled_builder_exit_does_not_satisfy_invariant():
    """A BUILDER_EXIT with source=reconcile_ticket must NOT satisfy the invariant."""
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "reconcile_ticket: forced close",
                "completion_summary": "reconciled",
                "source": "reconcile_ticket",
            },
            sequence_number=1,
        ),
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "from_state": "IN_PROGRESS",
                "to_state": "COMPLETED",
                "reason": "reconciled",
                "source": "reconcile_ticket",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    errors, _warnings = mod.check_post_closure_built_exit(
        bus, "WOT-2026-050a", "COMPLETED"
    )

    # The invariant should report Missing BUILDER_EXIT because the only one is reconciled
    assert any("Missing BUILDER_EXIT" in e for e in errors), (
        f"Expected 'Missing BUILDER_EXIT' error, got: {errors}"
    )


def test_real_builder_exit_satisfies_invariant():
    """A real BUILDER_EXIT (without reconcile source) must satisfy the invariant."""
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "normal completion",
                "completion_summary": "done",
            },
            sequence_number=1,
        ),
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "from_state": "READY_FOR_REVIEW",
                "to_state": "COMPLETED",
                "reason": "approved",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    errors, _warnings = mod.check_post_closure_built_exit(
        bus, "WOT-2026-050a", "COMPLETED"
    )

    # No errors - real BUILDER_EXIT satisfies the invariant
    assert not errors, f"Expected no errors, got: {errors}"


def test_mixed_events_real_one_satisfies():
    """When both reconciled and real BUILDER_EXIT exist, the real one satisfies."""
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "reconcile_ticket: forced close",
                "completion_summary": "reconciled",
                "source": "reconcile_ticket",
            },
            sequence_number=1,
        ),
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "normal completion",
                "completion_summary": "done",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    errors, _warnings = mod.check_post_closure_built_exit(
        bus, "WOT-2026-050a", "COMPLETED"
    )

    # No errors - real BUILDER_EXIT satisfies the invariant
    assert not errors, f"Expected no errors, got: {errors}"


def test_reconciled_events_filtered_in_order_check():
    """Reconciled BUILDER_EXIT events should be filtered in order check.

    When only reconciled BUILDER_EXIT exists, check_builder_exit_order should
    NOT warn (it checks ordering of real exits, not presence). Presence is
    checked by check_post_closure_built_exit.
    """
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "reconcile_ticket: forced close",
                "source": "reconcile_ticket",
            },
            sequence_number=1,
        ),
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "to_state": "READY_FOR_REVIEW",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    warnings = mod.check_builder_exit_order(bus, "WOT-2026-050a")

    # No warning - only reconciled exits exist, order check doesn't apply
    assert not warnings, f"Expected no warnings, got: {warnings}"


def test_real_exit_before_ready_satisfies_order():
    """A real BUILDER_EXIT before READY_FOR_REVIEW satisfies the order check."""
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "normal completion",
            },
            sequence_number=1,
        ),
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "to_state": "READY_FOR_REVIEW",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    warnings = mod.check_builder_exit_order(bus, "WOT-2026-050a")

    # No warning - real exit precedes READY_FOR_REVIEW
    assert not warnings, f"Expected no warnings, got: {warnings}"


def test_real_exit_after_ready_warns():
    """A real BUILDER_EXIT AFTER READY_FOR_REVIEW triggers order warning."""
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "to_state": "READY_FOR_REVIEW",
            },
            sequence_number=1,
        ),
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "normal completion",
            },
            sequence_number=2,
        ),
    ]

    bus = MockEventBus(events)
    warnings = mod.check_builder_exit_order(bus, "WOT-2026-050a")

    # Should warn - real exit comes AFTER READY_FOR_REVIEW
    assert any("ORDER INVARIANT" in w for w in warnings), (
        f"Expected ORDER INVARIANT warning, got: {warnings}"
    )


def test_synthetic_exit_before_ready_does_not_mask_real_exit_after():
    """El filtro de `check_builder_exit_order` DEBE tener dientes propios.

    Hueco cazado por el Review 2 fresh-context de WOT-2026-050a: los dos tests
    de orden anteriores pasaban IDENTICOS con y sin el filtro -- el primero por
    el early-return `if not builder_exits` y el segundo por la via de
    `has_prior_exit`. Dos verdes redundantes por rutas distintas: exactamente el
    falso-verde de la leccion 021u (un fixture que no AISLA la rama mutada).

    Este fixture es el unico donde ambas versiones DIVERGEN:
      seq=1  BUILDER_EXIT  SINTETICO (source=reconcile_ticket)
      seq=2  STATE_CHANGED -> READY_FOR_REVIEW
      seq=3  BUILDER_EXIT  REAL

    Con el filtro: el sintetico NO cuenta, luego el RFR de seq=2 no tiene
    ningun exit REAL previo -> ORDER INVARIANT.
    Sin el filtro (pre-fix): el sintetico cuenta como exit previo y el warning
    DESAPARECE -> el mutante sobrevive.
    """
    mod = _load_closure_invariants()

    events = [
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "reconcile_ticket: forced close",
                "source": "reconcile_ticket",
            },
            sequence_number=1,
        ),
        _make_event(
            "STATE_CHANGED",
            "WOT-2026-050a",
            {
                "to_state": "READY_FOR_REVIEW",
            },
            sequence_number=2,
        ),
        _make_event(
            "BUILDER_EXIT",
            "WOT-2026-050a",
            {
                "exit_reason": "builder finished",
                "completion_summary": "real work",
            },
            sequence_number=3,
        ),
    ]

    bus = MockEventBus(events)
    warnings = mod.check_builder_exit_order(bus, "WOT-2026-050a")

    # Un exit SINTETICO no puede satisfacer el orden por un RFR posterior.
    assert any("ORDER INVARIANT" in w for w in warnings), (
        "Un BUILDER_EXIT sintetico NO debe contar como exit previo del "
        f"READY_FOR_REVIEW. Warnings: {warnings}"
    )
