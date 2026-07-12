"""Shared test seams for forcing platform-specific branches.

WOT-2026-023a: helper importable (NOT a conftest fixture) so multiple test
files can force the Windows ``tasklist`` branch of ``bus.builder_locks``
regardless of the host platform running the suite (in particular, CI on
Linux).

Why a shim instead of ``monkeypatch.setattr(os, "name", ...)`` or
``monkeypatch.setattr(bl.os, "name", ...)``:

``bus.builder_locks`` does ``import os`` at module scope, so
``bus.builder_locks.os is os`` -- it is literally the SAME module object as
the global ``os``. Patching ``bl.os.name`` (or the global ``os.name``)
therefore mutates the process-wide ``os`` module for the duration of the
test. On Windows, ``pathlib`` internally branches on ``os.name`` to decide
between ``WindowsPath`` and ``PosixPath``. With ``os.name`` forced to
``"posix"`` on an actual Windows host, any ``Path`` construction that
happens during pytest's OWN reporting machinery (not just test code) can hit

    INTERNALERROR NotImplementedError: cannot instantiate 'PosixPath' on your
    system

This happens deep inside pytest's internals, outside the test's try/except,
so not even monkeypatch's automatic teardown can rescue the run -- the crash
happens while pytest is already unwinding.

The fix: never touch the real ``os`` module. Instead, replace the
module-global BINDING ``bus.builder_locks.os`` with a lightweight shim
object that delegates every attribute lookup to the real ``os`` module
EXCEPT ``.name``, which is pinned to whatever platform we want to simulate.
Only code that does ``bl.os.something`` sees the shim; pathlib and the rest
of the interpreter keep using the real, untouched ``os`` module.

Verified: 9/9 tests green with this mechanism, including forcing
``os.name == "posix"`` while running on an actual Windows host.
"""

from __future__ import annotations

import os
import types
from typing import Any

import bus.builder_locks as bl


class _OsNameShim:
    """Delegates all attribute access to the real ``os`` module except
    ``.name``, which is fixed to the value passed at construction time.
    """

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "name", name)

    def __getattr__(self, attr: str) -> Any:
        # __getattr__ is only invoked for names NOT found on the instance
        # itself (i.e. anything other than "name", which was set via
        # object.__setattr__ in __init__ and therefore lives in __dict__).
        return getattr(os, attr)


def force_os_name(monkeypatch: Any, name: str) -> None:
    """Force ``bus.builder_locks``'s ``os.name`` to ``name`` for this test.

    QUIRURGICO: only the module-global BINDING ``bus.builder_locks.os`` is
    replaced (with a shim that delegates everything to the real ``os``
    module except ``.name``). The real ``os`` module is left completely
    intact, so pathlib (and anything else outside ``bus.builder_locks``)
    keeps behaving normally -- including pytest's own internals.

    Also stubs ``bus.builder_locks.shutil.which`` so that, when simulating
    Windows (``name == "nt"``), the ``tasklist`` executable "exists" and the
    ``_is_pid_alive`` probe path is reachable without depending on an actual
    ``tasklist.exe`` on the test host.

    Callers are responsible for further mocking ``bl.subprocess.run`` (via
    ``monkeypatch.setattr(bl, "subprocess", ...)`` or
    ``monkeypatch.setattr(bl.subprocess, "run", ...)``) to control what the
    simulated ``tasklist`` probe reports.
    """
    monkeypatch.setattr(bl, "os", _OsNameShim(name))
    monkeypatch.setattr(
        bl,
        "shutil",
        types.SimpleNamespace(
            which=lambda n, *a, **k: "C:/fake/tasklist.EXE" if n == "tasklist" else None
        ),
    )
