"""Pytest configuration and fixtures."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / ".agent"
TEST_RUNTIME_ROOT = PROJECT_ROOT / "tests" / "sandbox" / "test_runtime"
SESSION_RUNTIME_ROOT = TEST_RUNTIME_ROOT / f"session_{os.getpid()}"


# Add project root FIRST, then .agent directory to path so tests can import
# both runtime.* modules (from root) and bus modules (from .agent/).
# This fixes the import precedence issue for agents_config.py which imports
# runtime.project_root. Insert order matters: last insert wins at position 0.
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ProjectTmpPathFactory:
    """Project-owned replacement for pytest tmp_path_factory."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def mktemp(self, name: str, numbered: bool = True) -> Path:
        safe_name = name.replace("/", "_").replace("\\", "_")
        if numbered:
            self._counter += 1
            path = self.base_dir / f"{safe_name}{self._counter:04d}"
        else:
            path = self.base_dir / safe_name
        path.mkdir(parents=True, exist_ok=True)
        return path


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


@pytest.fixture(scope="session", autouse=True)
def _project_temp_environment() -> None:
    """Keep pytest temp activity inside the project sandbox."""
    original_tempdir = tempfile.tempdir
    original_env = {
        "TMPDIR": os.environ.get("TMPDIR"),
        "TEMP": os.environ.get("TEMP"),
        "TMP": os.environ.get("TMP"),
    }

    SESSION_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(SESSION_RUNTIME_ROOT)
    os.environ["TMPDIR"] = str(SESSION_RUNTIME_ROOT)
    os.environ["TEMP"] = str(SESSION_RUNTIME_ROOT)
    os.environ["TMP"] = str(SESSION_RUNTIME_ROOT)

    try:
        yield
    finally:
        tempfile.tempdir = original_tempdir
        for key, value in original_env.items():
            _restore_env(key, value)
        shutil.rmtree(SESSION_RUNTIME_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _restore_cwd() -> None:
    """Restore the working directory after each test."""
    original_cwd = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original_cwd)


@pytest.fixture(scope="session")
def tmp_path_factory() -> ProjectTmpPathFactory:
    """Project-local tmp_path factory."""
    return ProjectTmpPathFactory(SESSION_RUNTIME_ROOT / "factory")


@pytest.fixture
def tmp_path(
    tmp_path_factory: ProjectTmpPathFactory, request: pytest.FixtureRequest
) -> Path:
    """Project-local tmp_path fixture."""
    return tmp_path_factory.mktemp(request.node.name, numbered=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the session runtime once pytest finishes."""
    shutil.rmtree(SESSION_RUNTIME_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clear_runtime_project_root_cache() -> None:
    """Keep runtime.project_root cache isolated across tests."""
    try:
        pr = importlib.import_module("runtime.project_root")
    except Exception:
        yield
        return

    clear = getattr(pr, "clear_cache", None)
    if callable(clear):
        clear()
    try:
        yield
    finally:
        if callable(clear):
            clear()


# Real motor bus file: tests must never leave it mutated (WOT-2026-007f review).
_MOTOR_EVENTS_FILE = AGENT_DIR / "runtime" / "events" / "events.jsonl"


@pytest.fixture(autouse=True)
def _isolate_controller_event_bus() -> None:
    """Barrier (WOT-2026-007f review): isolate the agent_controller event bus.

    Closes two leaks that share the same root cause (an unmanaged module-level
    singleton + a real-motor bus path):

      1. ``agent_controller.event_bus`` is a lazily-initialized module global
         that is never reset. A test that initializes it leaks the instance into
         later tests and changes their behavior (e.g. whether a blocked
         mark-ready emits a BUILDER_EXIT). Reset it to None around every test.
      2. The controller resolves its bus path from ``runtime.project_root``
         (the real motor) regardless of a test patching
         ``agent_controller.PROJECT_ROOT``. Controller tests can therefore write
         events into the REAL motor ``events.jsonl``. Snapshot that file and
         restore it after each test so the suite never leaves the motor dirty.

    Verified barrier: with this fixture active, a full suite run leaves
    ``git status`` clean on ``.agent/runtime/events/events.jsonl``.
    """
    ac = sys.modules.get("agent_controller")
    if ac is not None:
        ac.event_bus = None

    before = _MOTOR_EVENTS_FILE.read_bytes() if _MOTOR_EVENTS_FILE.exists() else None
    try:
        yield
    finally:
        ac = sys.modules.get("agent_controller")
        if ac is not None:
            ac.event_bus = None
        after = _MOTOR_EVENTS_FILE.read_bytes() if _MOTOR_EVENTS_FILE.exists() else None
        if before != after:
            # A test mutated the real motor bus: restore so the motor stays clean.
            if before is None:
                _MOTOR_EVENTS_FILE.unlink(missing_ok=True)
            else:
                _MOTOR_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                _MOTOR_EVENTS_FILE.write_bytes(before)
