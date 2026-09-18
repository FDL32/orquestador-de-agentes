"""Heartbeat module: incremental observability for pytest runs.

WOT-2026-070i: writes NDJSON records to a per-PID file so that when the
pytest process is killed (TerminateProcess, Job Object, debugger), the
last recorded (nodeid, phase) survives on disk.

Contract:
  - Append-only NDJSON, one record per line, flushed after each write.
  - Fail-open: every write is wrapped in try/except that swallows all
    exceptions. A broken heartbeat never alters pytest's verdict.
  - File path: ``.agent/runtime/pytest-safe/heartbeat-<pid>.jsonl``.

Event kinds:
  - ``process_start``     : emitted at conftest import time.
  - ``collection_start``  : emitted once at the very beginning of collection.
  - ``collection_finish`` : emitted after collection completes.
  - ``test_start``        : emitted when a test begins (before setup).
  - ``phase``             : emitted after each phase (setup/call/teardown)
    with ``outcome`` (``passed``, ``failed``, ``skipped``, ``error``).

A test is considered *complete* when it has registered ``setup``, ``call``,
and ``teardown`` phases. The death point is the last ``(nodeid, when)``
record in the file.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Explicit import so monkeypatch can replace it in fail-open tests.
# Without this alias, the test would need to patch builtins.open which
# affects the entire test process. Patching the module-level name keeps
# the scope contained to this module only.
_open = open

# Directory and file pattern for heartbeat records.
HEARTBEAT_DIR = (
    Path(__file__).resolve().parents[1] / ".agent" / "runtime" / "pytest-safe"
)
HEARTBEAT_PATTERN = "heartbeat-{pid}.jsonl"

# Global state: one writer per PID to avoid interleaving across parallel runs.
_writer_lock = threading.Lock()
_active_path: Path | None = None
_active_file = None
_record_count = 0
_consecutive_failures = 0

# Maximum consecutive write failures before disabling the heartbeat channel.
# Prevents infinite retry loops when the failure is permanent (e.g. full disk,
# invalid path). After this threshold the channel is disabled for the rest
# of the suite run.
_MAX_FAILURES = 10


def _heartbeat_path() -> Path:
    """Return the heartbeat file path for the current process PID."""
    return HEARTBEAT_DIR / HEARTBEAT_PATTERN.format(pid=os.getpid())


def _ensure_dir(path: Path) -> None:
    """Create the heartbeat directory if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_record(event: dict[str, Any]) -> None:
    """Append a single NDJSON record to the heartbeat file.

    Fail-open: if the write fails for any reason (disk full, permission
    denied, invalid path), the exception is swallowed and the suite
    continues unaffected. After ``_MAX_FAILURES`` consecutive failures,
    the channel is disabled to avoid infinite retry overhead.
    """
    global _active_path, _active_file, _record_count, _consecutive_failures

    with _writer_lock:
        try:
            if _active_file is None:
                _active_path = _heartbeat_path()
                _ensure_dir(_active_path)
                _active_file = _open(_active_path, "a", encoding="utf-8")

            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            _active_file.write(line)
            _active_file.flush()
            _record_count += 1
            _consecutive_failures = 0  # reset on success
        except Exception:
            # Fail-open: never let heartbeat I/O break pytest.
            _consecutive_failures += 1
            if _consecutive_failures >= _MAX_FAILURES:
                # Permanent failure: disable the channel.
                _active_file = None
                _active_path = None
            else:
                # Temporary failure: reset so next call retries.
                _active_file = None
                _active_path = None


def close() -> None:
    """Flush and close the heartbeat file handle."""
    global _active_file, _active_path

    with _writer_lock:
        try:
            if _active_file is not None:
                _active_file.flush()
                _active_file.close()
        except Exception:  # noqa: S110
            pass
        finally:
            _active_file = None
            _active_path = None


def process_start() -> None:
    """Emit a ``process_start`` event when the conftest is imported.

    WOT-2026-070i DoD-2: ``pytest_collection`` only runs once pytest reaches the
    collection phase. A process that dies between conftest import and that point
    would leave NO marker at all, so this is emitted at import time.
    """
    write_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ev": "process_start",
            "pid": os.getpid(),
        }
    )


def collection_start() -> None:
    """Emit a ``collection_start`` event."""
    write_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ev": "collection_start",
            "pid": os.getpid(),
        }
    )


def collection_finish(total: int) -> None:
    """Emit a ``collection_finish`` event with the number of collected items."""
    write_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ev": "collection_finish",
            "pid": os.getpid(),
            "count": total,
        }
    )


def test_start(nodeid: str) -> None:
    """Emit a ``test_start`` event for the given node id."""
    write_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ev": "test_start",
            "pid": os.getpid(),
            "nodeid": nodeid,
        }
    )


def phase_report(nodeid: str, when: str, outcome: str) -> None:
    """Emit a ``phase`` event after a test phase completes.

    Parameters
    ----------
    nodeid : str
        The pytest node id (e.g. ``tests/unit/test_foo.py::test_bar``).
    when : str
        The phase name: ``setup``, ``call``, or ``teardown``.
    outcome : str
        The phase outcome: ``passed``, ``failed``, ``skipped``, ``error``.
    """
    write_record(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ev": "phase",
            "pid": os.getpid(),
            "nodeid": nodeid,
            "when": when,
            "outcome": outcome,
        }
    )
