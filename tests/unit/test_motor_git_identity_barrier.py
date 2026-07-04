"""Regression tests for the pytest motor-git-identity isolation barrier.

WOT-2026-016z: these tests exercise ``_enforce_motor_git_identity_isolation``
(exposed via the ``motor_git_identity_guard`` fixture) without ever invoking a
real ``git config --local`` against the motor (``PROJECT_ROOT``). Fase 0 of
this ticket established that no test may run ``git config`` with
``cwd=PROJECT_ROOT``, so contamination here is simulated purely in memory: the
module-level reader/writer functions in ``tests/conftest.py`` are monkeypatched
to fake "after" identity tuples and to record restore calls, and the guard is
invoked directly with an in-memory "before" tuple.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_conftest():
    """Load tests/conftest.py as a module to monkeypatch its internals directly.

    Mirrors tests/unit/test_windows_safe_temp_runtime.py::_load_conftest: pytest
    loads conftest as a plugin, not as an importable sibling module, so resolve
    it by path (reusing an already-loaded instance from sys.modules when
    present) instead of duplicating the reader/writer logic here.
    """
    for mod in sys.modules.values():
        if getattr(mod, "__file__", None) == str(
            PROJECT_ROOT / "tests" / "conftest.py"
        ):
            return mod
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_conftest_under_test_git_identity", PROJECT_ROOT / "tests" / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conftest = _load_conftest()


def test_motor_git_identity_barrier_restores_existing_value(
    monkeypatch: pytest.MonkeyPatch,
    motor_git_identity_guard: Callable[[tuple, str], None],
) -> None:
    """A changed existing identity is restored and reported as contamination."""
    before = ("original@example.invalid", "Original Name")
    after = ("leaked@example.invalid", "Leaked Name")
    restore_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(conftest, "_read_motor_git_identity", lambda: after)
    monkeypatch.setattr(
        conftest,
        "_write_motor_git_identity_key",
        lambda key, value: restore_calls.append((key, value)),
    )

    with pytest.raises(pytest.fail.Exception, match=r"test_existing_identity"):
        motor_git_identity_guard(before, "test_existing_identity")

    assert restore_calls == [
        ("user.email", "original@example.invalid"),
        ("user.name", "Original Name"),
    ]


def test_motor_git_identity_barrier_handles_previously_unset_value(
    monkeypatch: pytest.MonkeyPatch,
    motor_git_identity_guard: Callable[[tuple, str], None],
) -> None:
    """An identity that did not exist before is unset again (never invented)."""
    before = (None, None)
    after = ("leaked@example.invalid", "Leaked Name")
    restore_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(conftest, "_read_motor_git_identity", lambda: after)
    monkeypatch.setattr(
        conftest,
        "_write_motor_git_identity_key",
        lambda key, value: restore_calls.append((key, value)),
    )

    with pytest.raises(pytest.fail.Exception, match=r"test_new_identity"):
        motor_git_identity_guard(before, "test_new_identity")

    assert restore_calls == [("user.email", None), ("user.name", None)]


def test_motor_git_identity_barrier_allows_unchanged_value(
    monkeypatch: pytest.MonkeyPatch,
    motor_git_identity_guard: Callable[[tuple, str], None],
) -> None:
    """An unchanged identity does not trigger the barrier."""
    identity = ("original@example.invalid", "Original Name")
    restore_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(conftest, "_read_motor_git_identity", lambda: identity)
    monkeypatch.setattr(
        conftest,
        "_write_motor_git_identity_key",
        lambda key, value: restore_calls.append((key, value)),
    )

    motor_git_identity_guard(identity, "test_unchanged_identity")

    assert restore_calls == []
