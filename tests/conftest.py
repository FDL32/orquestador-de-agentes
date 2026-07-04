"""Pytest configuration and fixtures."""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import stat
import subprocess
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
        safe_name = (
            safe_name[:16]
            + "_"
            + hashlib.sha1(
                safe_name.encode("utf-8"), usedforsecurity=False
            ).hexdigest()[:8]
        )
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


def _force_remove_readonly(func, path, _exc) -> None:
    """rmtree error handler: clear the read-only bit and retry the removal.

    WOT-2026-013i. On Windows ``shutil.rmtree`` raises ``PermissionError``
    (WinError 5) on read-only files -- notably the ``.git/objects/*`` entries that
    git itself marks read-only inside test-fixture repos. The 013d purge used
    ``ignore_errors=True``, which SWALLOWED these errors: it spent ~39s walking the
    tree and removed nothing, so orphan session dirs accumulated indefinitely (575
    observed) and inflated every later session's setup. This handler chmods the
    offending path writable and retries ``func`` (unlink/rmdir), so the purge
    actually deletes the tree instead of silently failing.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        # Truly undeletable (locked by a live process): leave it. The next
        # session retries; the purge remains best-effort and never raises.
        pass


def _rmtree_robust(target: Path) -> bool:
    """Remove a tree, clearing read-only bits on error. Returns True if gone.

    Replaces ``shutil.rmtree(target, ignore_errors=True)``: instead of silently
    swallowing every error (which left read-only ``.git`` trees undeleted), it
    routes failures through ``_force_remove_readonly`` to chmod+retry. Compatible
    with both the pre-3.12 ``onerror(func, path, exc_info)`` API and the 3.12+
    ``onexc(func, path, exc)`` API. Never raises; reports whether the path is gone.
    """
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_force_remove_readonly)
    else:
        shutil.rmtree(
            target,
            onerror=lambda func, path, exc: _force_remove_readonly(func, path, exc),
        )
    return not target.exists()


def _purge_orphan_session_dirs(keep_pid: int) -> int:
    """WOT-2026-013d/013i: remove stale session_<PID> sandboxes from dead runs.

    The per-session sandbox lives under tests/sandbox/test_runtime/session_<PID>.
    When a run's finalizer does not execute (killed process, crash), its dir is
    orphaned and accumulates (566 observed at 013d baseline, 575 at 013i),
    inflating the latency and FS-race surface of any tree walk. This is the
    conftest-managed hygiene the 013d contract requires: deterministic cleanup of
    the sandbox noise, expressed as a fixture/harness -- never manual edits to the
    sandbox tree.

    WOT-2026-013i: removal goes through ``_rmtree_robust`` so read-only ``.git``
    fixture trees are actually deleted (the prior ``ignore_errors=True`` made the
    purge a no-op on Windows). Removes every session_* dir except the current
    pid's. Returns the count actually purged.
    """
    if not TEST_RUNTIME_ROOT.is_dir():
        return 0
    purged = 0
    keep = f"session_{keep_pid}"
    for entry in TEST_RUNTIME_ROOT.iterdir():
        if (
            entry.name.startswith("session_")
            and entry.name != keep
            and _rmtree_robust(entry)
        ):
            purged += 1
    return purged


@pytest.fixture(scope="session", autouse=True)
def _project_temp_environment() -> None:
    """Keep pytest temp activity inside the project sandbox."""
    # WOT-2026-013d: purge orphan session dirs from dead runs before this session.
    _purge_orphan_session_dirs(os.getpid())
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
        # WOT-2026-013i: robust removal so this session's own read-only .git
        # fixtures are deleted, preventing it from becoming the next orphan.
        _rmtree_robust(SESSION_RUNTIME_ROOT)


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
    # WOT-2026-013i: robust removal (read-only .git fixtures) instead of the
    # silent ignore_errors no-op that let orphans accumulate.
    _rmtree_robust(SESSION_RUNTIME_ROOT)


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


def _restore_motor_bus_if_changed(
    events_file: Path,
    before: bytes | None,
) -> bool:
    """Restore a mutated motor bus snapshot and report whether it changed."""
    after = events_file.read_bytes() if events_file.exists() else None
    if before == after:
        return False
    if before is None:
        events_file.unlink(missing_ok=True)
    else:
        events_file.parent.mkdir(parents=True, exist_ok=True)
        events_file.write_bytes(before)
    return True


def _enforce_motor_bus_isolation(
    events_file: Path,
    before: bytes | None,
    nodeid: str,
) -> None:
    """Restore a leaked motor bus and fail with the contaminating test id."""
    if _restore_motor_bus_if_changed(events_file, before):
        pytest.fail(
            "Test mutated the real motor event bus and was isolated: "
            f"{nodeid}. Patch agent_controller.event_bus or "
            "runtime.project_root to a temporary bus.",
            pytrace=False,
        )


@pytest.fixture
def motor_bus_isolation_guard():
    """Expose the exact isolation enforcement function for barrier tests."""
    return _enforce_motor_bus_isolation


def _read_motor_git_identity() -> tuple[str | None, str | None]:
    """Read the motor's local ``user.email``/``user.name`` (None if unset).

    Degrades to ``(None, None)`` instead of raising if ``git`` is not on
    ``PATH`` (e.g. a minimal CI image): a missing ``git`` binary must not break
    the whole suite via a fixture-collection error (WOT-2026-016z Review 2
    blocker 2).
    """

    def _read_one(key: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "config", "--local", key],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value if value else None

    return _read_one("user.email"), _read_one("user.name")


def _write_motor_git_identity_key(key: str, value: str | None) -> None:
    """Set (or unset) a single motor-local git config key.

    Degrades silently if ``git`` is not on ``PATH`` (see
    ``_read_motor_git_identity``): there is nothing to restore if it was never
    possible to read the identity in the first place.
    """
    try:
        if value is None:
            subprocess.run(
                ["git", "config", "--local", "--unset", key],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            subprocess.run(
                ["git", "config", "--local", key, value],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
    except (FileNotFoundError, OSError):
        pass


def _restore_motor_git_identity_if_changed(
    before: tuple[str | None, str | None],
) -> bool:
    """Restore a mutated motor git identity and report whether it changed."""
    after = _read_motor_git_identity()
    if before == after:
        return False
    before_email, before_name = before
    _write_motor_git_identity_key("user.email", before_email)
    _write_motor_git_identity_key("user.name", before_name)
    return True


def _enforce_motor_git_identity_isolation(
    before: tuple[str | None, str | None],
    nodeid: str,
) -> None:
    """Restore a leaked motor git identity and fail naming the contaminating test.

    ``nodeid`` is the exact pytest node id when the caller can attribute the
    change to a single test (used by the barrier tests below). The
    session-scoped fixture that drives this in production cannot name an
    individual test (see ``_isolate_motor_git_identity_session``); it passes a
    session-level description instead.
    """
    if _restore_motor_git_identity_if_changed(before):
        pytest.fail(
            "Test mutated the real motor git identity (user.email/user.name) and "
            f"was isolated: {nodeid}. Use a git -c user.email=... inline override "
            "or cwd=tmp_path/cwd=repo (a temporary repo fixture); never a "
            "persistent git config --local change on the real motor.",
            pytrace=False,
        )


@pytest.fixture
def motor_git_identity_guard():
    """Expose the exact isolation enforcement function for barrier tests."""
    return _enforce_motor_git_identity_isolation


@pytest.fixture(scope="session", autouse=True)
def _isolate_motor_git_identity_session() -> None:
    """Barrier (WOT-2026-016z): isolate the motor's local git identity.

    Snapshots ``git config --local user.email``/``user.name`` for the real
    motor (``PROJECT_ROOT``) ONCE at the start of the pytest session and, in
    this fixture's teardown (which runs at session end, after every test),
    restores the original value and fails the session if it changed. No
    fixture is known to mutate this today (WOT-2026-016z Fase 0 verified all
    ``git config`` usages in tests/ operate on ``cwd=tmp_path``/``cwd=repo``
    fixtures, never on the real motor), but this closes the risk of future
    recontamination with the same restore-and-fail mechanism already approved
    for the event bus (see ``_isolate_controller_event_bus``), scoped to the
    session instead of per-test.

    SESSION-SCOPE TRADE-OFF (WOT-2026-016z Review 2, blocker 1): the original
    design cloned the bus fixture's PER-TEST scope, which costs 4 ``git
    config`` subprocesses per test (2 keys, snapshot + restore-check) --
    empirically ~186s of added wall time across ~3500 tests (measured: 355-378s
    with per-test vs ~165-190s with session-scope). Per-test scope is not
    needed for correctness: the resource under guard is a single global (the
    motor's local git identity), not a per-test resource, and this event has 0
    observed occurrences. Session-scope reduces the cost to ~4 subprocesses
    total for the whole suite (one snapshot, one comparison at teardown), at
    the cost of losing the ability to name the exact contaminating test: on
    failure, the message can only say "some test in this session" rather than
    a specific nodeid. If this ever fires, bisect manually (rerun subsets of
    the suite) to find the offending test -- an acceptable trade given the
    event has never fired in this repo's history. A per-test scoped variant
    remains available for that manual bisection via ``motor_git_identity_guard``
    plus a temporary local fixture, without paying its cost by default.

    ``pytest.fail`` inside a session-scoped fixture's teardown (this method,
    not ``pytest_sessionfinish``) is used deliberately: ``pytest_sessionfinish``
    runs after the session is already finalized and cannot fail it, whereas a
    fixture teardown failure is reported as a session error and yields a
    non-zero exit code.
    """
    before = _read_motor_git_identity()
    try:
        yield
    finally:
        _enforce_motor_git_identity_isolation(
            before, "<session>: some test mutated the motor git identity"
        )


@pytest.fixture(autouse=True)
def _isolate_controller_event_bus(request: pytest.FixtureRequest) -> None:
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
         events into the REAL motor ``events.jsonl``. Snapshot that file,
         restore it after each test, and fail the contaminating test so the leak
         cannot hide behind a green suite.

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
        _enforce_motor_bus_isolation(
            _MOTOR_EVENTS_FILE,
            before,
            request.node.nodeid,
        )
