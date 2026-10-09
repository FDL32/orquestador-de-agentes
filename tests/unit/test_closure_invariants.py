"""Tests for check_pre_closure_invariants sequence_number gating (WOT-2026-089b).

Before the fix, check_pre_closure_invariants warned on the mere EXISTENCE of a
BUILDER_EXIT. Because the event bus is append-only, the BUILDER_EXIT of a round
already closed by a --request-changes requeue stayed on the bus and re-triggered
the warning on every --validate until the next --mark-ready. The fix compares
sequence_number against the latest STATE_CHANGED, exactly as
check_builder_exit_order already does, and excludes reconcile_ticket synthetic
events via _is_reconciled_event.

The module is loaded with importlib under the single name "closure_invariants",
matching tests/test_closure_invariants_reconcile.py, so the module identity is
shared (no "same module under two names = two instances" seam).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_closure_invariants():
    import sys

    module_path = (
        Path(__file__).resolve().parents[2] / ".agent" / "closure_invariants.py"
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
    """Create a minimal event object."""
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
    """Minimal append-only bus: read order == append order == sequence order."""

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


TICKET = "WOT-2026-089b"
WARNING = "BUILDER_EXIT exists but ticket not in READY_FOR_REVIEW/COMPLETED"


def _state_changed(to_state, sequence_number):
    return _make_event(
        "STATE_CHANGED",
        TICKET,
        {"from_state": "IN_PROGRESS", "to_state": to_state, "reason": "test"},
        sequence_number=sequence_number,
    )


def _builder_exit(sequence_number, reconciled=False):
    payload = {"exit_reason": "normal completion", "completion_summary": "done"}
    if reconciled:
        payload = {
            "exit_reason": "reconcile_ticket: forced close",
            "completion_summary": "reconciled",
            "source": "reconcile_ticket",
        }
    return _make_event("BUILDER_EXIT", TICKET, payload, sequence_number=sequence_number)


class TestD1SequenceGate:
    """D1: gating by sequence_number against the latest STATE_CHANGED."""

    def test_builder_exit_older_than_latest_state_change_no_warning(self):
        mod = _load_closure_invariants()
        bus = MockEventBus([_builder_exit(2), _state_changed("IN_PROGRESS", 3)])
        assert mod.check_pre_closure_invariants(bus, TICKET) == []

    def test_builder_exit_equal_to_latest_state_change_no_warning(self):
        mod = _load_closure_invariants()
        bus = MockEventBus([_builder_exit(3), _state_changed("IN_PROGRESS", 3)])
        assert mod.check_pre_closure_invariants(bus, TICKET) == []

    def test_builder_exit_newer_than_latest_state_change_warns(self):
        """Negative control: a real violation must still be detected."""
        mod = _load_closure_invariants()
        bus = MockEventBus([_state_changed("IN_PROGRESS", 3), _builder_exit(4)])
        warnings = mod.check_pre_closure_invariants(bus, TICKET)
        assert warnings == [WARNING]

    def test_builder_exit_without_state_change_warns(self):
        """No STATE_CHANGED anchor: preserve the pre-fix behaviour (warn)."""
        mod = _load_closure_invariants()
        bus = MockEventBus([_builder_exit(1)])
        warnings = mod.check_pre_closure_invariants(bus, TICKET)
        assert warnings == [WARNING]


class TestD2ReconciledExclusion:
    """D2: reconcile_ticket synthetic exits are excluded from the comparison."""

    def test_reconciled_builder_exit_no_warning(self):
        mod = _load_closure_invariants()
        bus = MockEventBus([_builder_exit(1, reconciled=True)])
        assert mod.check_pre_closure_invariants(bus, TICKET) == []

    def test_reconciled_latest_exit_ignored_real_exit_is_compared(self):
        """A newer synthetic exit must not shadow the real one.

        Without the _is_reconciled_event filter, latest_event() would return the
        synthetic exit at seq=5 (> the STATE_CHANGED at seq=3) and warn. With the
        filter the real exit at seq=2 is used, which is older than seq=3.
        """
        mod = _load_closure_invariants()
        bus = MockEventBus(
            [
                _builder_exit(2),
                _state_changed("IN_PROGRESS", 3),
                _builder_exit(5, reconciled=True),
            ]
        )
        assert mod.check_pre_closure_invariants(bus, TICKET) == []


class TestD3RealScenario:
    """D3: reproduction of the measured WOT-2026-061e requeue sequence."""

    def test_requeued_round_no_warning(self):
        """BUILDER_EXIT(1), RFR(2), REVIEW_DECISION changes(3), IN_PROGRESS(4)."""
        mod = _load_closure_invariants()
        bus = MockEventBus(
            [
                _builder_exit(1),
                _state_changed("READY_FOR_REVIEW", 2),
                _make_event(
                    "REVIEW_DECISION",
                    TICKET,
                    {"decision": "changes"},
                    sequence_number=3,
                ),
                _state_changed("IN_PROGRESS", 4),
            ]
        )
        assert mod.check_pre_closure_invariants(bus, TICKET) == []

    def test_invariant_stays_alive_when_it_applies(self):
        """The invariant still fires when the exit has no later state change.

        This is the semantically correct "still alive when it applies" control
        under Decision 1 (temporal criterion): a BUILDER_EXIT emitted AFTER the
        latest STATE_CHANGED, without its STATE_CHANGED -> READY_FOR_REVIEW.
        """
        mod = _load_closure_invariants()
        bus = MockEventBus([_state_changed("IN_PROGRESS", 1), _builder_exit(2)])
        warnings = mod.check_pre_closure_invariants(bus, TICKET)
        assert warnings == [WARNING]

    def test_contract_control_without_requeue_state_change_no_warning(self):
        """Documented adjudication of a contract inconsistency.

        The contract's D3 control ("the same sequence minus the final
        STATE_CHANGED seq=4, still warns") is internally inconsistent with its
        own Decision 1: BUILDER_EXIT(1), READY_FOR_REVIEW(2) and the temporal
        criterion "warn only if BUILDER_EXIT.sequence_number > latest
        STATE_CHANGED" give 1 > 2 == False, i.e. NO warning, because the
        READY_FOR_REVIEW STATE_CHANGED at seq=2 is a later state change closing
        the round. Any rule that warned here would have to key on to_state,
        which Decision 1 explicitly forbids ("NO se filtra por to_state"). The
        bug report's DoD (b) ("un BUILDER_EXIT posterior sin su STATE_CHANGED ->
        READY_FOR_REVIEW SIGUE avisando") also matches the temporal criterion,
        not this control. Decision 1 therefore governs; this test pins its
        outcome for that exact sequence. See BUILDER_REPORT for the flag.
        """
        mod = _load_closure_invariants()
        bus = MockEventBus(
            [
                _builder_exit(1),
                _state_changed("READY_FOR_REVIEW", 2),
                _make_event(
                    "REVIEW_DECISION",
                    TICKET,
                    {"decision": "changes"},
                    sequence_number=3,
                ),
            ]
        )
        assert mod.check_pre_closure_invariants(bus, TICKET) == []
