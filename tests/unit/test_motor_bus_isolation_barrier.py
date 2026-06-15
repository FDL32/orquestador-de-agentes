"""Regression tests for the pytest motor-bus isolation barrier."""

from collections.abc import Callable
from pathlib import Path

import pytest


def test_motor_bus_barrier_restores_existing_file(
    tmp_path: Path,
    motor_bus_isolation_guard: Callable[[Path, bytes | None, str], None],
) -> None:
    """A changed existing bus is restored and reported as contamination."""
    events_file = tmp_path / "events.jsonl"
    original = b'{"event_type":"ORIGINAL"}\n'
    events_file.write_bytes(original)

    before = events_file.read_bytes()
    events_file.write_bytes(b'{"event_type":"LEAK"}\n')

    with pytest.raises(pytest.fail.Exception, match=r"test_existing_bus"):
        motor_bus_isolation_guard(events_file, before, "test_existing_bus")
    assert events_file.read_bytes() == original


def test_motor_bus_barrier_removes_new_file(
    tmp_path: Path,
    motor_bus_isolation_guard: Callable[[Path, bytes | None, str], None],
) -> None:
    """A bus created by a test is removed and reported as contamination."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_bytes(b'{"event_type":"LEAK"}\n')

    with pytest.raises(pytest.fail.Exception, match=r"test_new_bus"):
        motor_bus_isolation_guard(events_file, None, "test_new_bus")
    assert not events_file.exists()


def test_motor_bus_barrier_allows_unchanged_file(
    tmp_path: Path,
    motor_bus_isolation_guard: Callable[[Path, bytes | None, str], None],
) -> None:
    """An unchanged bus does not trigger the barrier."""
    events_file = tmp_path / "events.jsonl"
    original = b'{"event_type":"ORIGINAL"}\n'
    events_file.write_bytes(original)

    motor_bus_isolation_guard(events_file, original, "test_unchanged_bus")
    assert events_file.read_bytes() == original
