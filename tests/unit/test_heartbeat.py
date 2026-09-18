"""Tests for the heartbeat observability module.

WOT-2026-070i: these tests verify the heartbeat contract:
  (a) positioning by phase -- records include nodeid and phase.
  (b) fail-open -- broken I/O never propagates.
  (c) NDJSON integrity -- line-by-line parseable, no truncation, ends with newline.

These tests MUST fail without the conftest hooks (Red-first).
"""

import builtins
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# Save reference to built-in open for monkeypatching in fail-open tests.
builtins_open = builtins.open


# Resolve heartbeat module path directly so tests can import it even when
# the conftest import path is not yet active.
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_HEARTBEAT_PATH = Path(__file__).resolve().parent.parent / "heartbeat.py"
assert _HEARTBEAT_PATH.is_file(), (
    "tests/heartbeat.py must exist for WOT-2026-070i tests to run"
)


def _import_heartbeat() -> object:
    """Import the heartbeat module from its file path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("heartbeat", _HEARTBEAT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def heartbeat():
    """Yield the heartbeat module instance with clean state."""
    import contextlib

    mod = _import_heartbeat()
    # Close any open handle from a previous test.
    if mod._active_file is not None:
        with contextlib.suppress(Exception):
            mod._active_file.close()
    mod._active_path = None
    mod._active_file = None
    mod._record_count = 0
    yield mod
    # Cleanup after test.
    if mod._active_file is not None:
        with contextlib.suppress(Exception):
            mod._active_file.close()
    mod._active_file = None
    mod._active_path = None
    mod._record_count = 0


# ── (a) Positioning by phase ────────────────────────────────────────────────


class TestPositioningByPhase:
    """Verify that heartbeat records carry nodeid and phase information."""

    def test_phase_record_contains_nodeid_and_when(self, heartbeat, tmp_path):
        """A phase record must include nodeid, when, and outcome fields."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        heartbeat.phase_report(
            nodeid="tests/unit/test_example.py::test_example",
            when="call",
            outcome="passed",
        )
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
        record = json.loads(lines[0])
        assert record["ev"] == "phase"
        assert record["nodeid"] == "tests/unit/test_example.py::test_example"
        assert record["when"] == "call"
        assert record["outcome"] == "passed"

    def test_test_start_record_contains_nodeid(self, heartbeat, tmp_path):
        """A test_start record must include the nodeid."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        heartbeat.test_start("tests/unit/test_example.py::test_example")
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["ev"] == "test_start"
        assert record["nodeid"] == "tests/unit/test_example.py::test_example"

    def test_conftest_import_emits_process_start_first(self):
        """DoD-2: the conftest emits ``process_start`` at IMPORT time.

        ``pytest_collection`` only fires once collection begins, so a process
        that dies between conftest import and that point would leave no marker
        at all. This drives a real pytest subprocess and asserts the marker is
        the FIRST physical record of the resulting artifact.
        """
        from tests.conftest import REAL_SYSTEM_TEMP

        work = pathlib.Path(
            tempfile.mkdtemp(prefix="hb_procstart_", dir=str(REAL_SYSTEM_TEMP))
        )
        try:
            (work / "test_trivial.py").write_text(
                "import os\n"
                "def test_trivial():\n"
                "    print(f'HB_CHILD_PID={os.getpid()}')\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            for var in ("TMPDIR", "TEMP", "TMP"):
                env[var] = str(REAL_SYSTEM_TEMP)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "test_trivial.py",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "-p",
                    "tests.conftest",
                    "-s",
                ],
                capture_output=True,
                text=True,
                cwd=str(work),
                env={**env, "PYTHONPATH": str(_MOTOR_ROOT)},
            )
            assert result.returncode == 0, result.stdout + result.stderr

            # The child prints its own PID, so we read ITS artifact by name.
            # Picking the newest file by mtime would be a false green: another
            # pytest process (a live canonical suite) may be writing at the
            # same time, and we would assert against a stranger's file.
            hb_dir = _MOTOR_ROOT / ".agent" / "runtime" / "pytest-safe"
            child_pid = int(
                next(
                    line.split("=", 1)[1].strip()
                    for line in result.stdout.splitlines()
                    if line.startswith("HB_CHILD_PID=")
                )
            )
            artifact = hb_dir / f"heartbeat-{child_pid}.jsonl"
            assert artifact.is_file(), f"no existe {artifact.name}"
            rows = [
                json.loads(line)
                for line in artifact.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if line.strip()
            ]
            assert rows, f"{artifact.name} quedo vacio"
            assert rows[0]["ev"] == "process_start", (
                f"el PRIMER registro debe ser process_start, fue {rows[0]['ev']}"
            )
            assert rows[0]["pid"] == child_pid
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_collection_start_record(self, heartbeat, tmp_path):
        """A collection_start record must include pid and timestamp."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        heartbeat.collection_start()
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["ev"] == "collection_start"
        assert "pid" in record
        assert "ts" in record

    def test_collection_finish_record(self, heartbeat, tmp_path):
        """A collection_finish record must include the count."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        heartbeat.collection_finish(total=42)
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["ev"] == "collection_finish"
        assert record["count"] == 42

    def test_multiple_phases_create_multiple_records(self, heartbeat, tmp_path):
        """Three phases for the same test create three records."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        nid = "tests/unit/test_example.py::test_example"
        for phase in ("setup", "call", "teardown"):
            heartbeat.phase_report(nid, phase, "passed")
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        phases = [json.loads(line)["when"] for line in lines]
        assert phases == ["setup", "call", "teardown"]


# ── (b) Fail-open ──────────────────────────────────────────────────────────


class TestFailOpen:
    """Verify that broken I/O never propagates."""

    def test_write_to_impossible_path_does_not_raise(
        self, heartbeat, tmp_path, monkeypatch
    ):
        """Writing to an impossible path must not raise."""

        def _fail_open(*args, **kwargs):
            raise OSError("simulated I/O failure")

        monkeypatch.setattr(heartbeat, "_open", _fail_open)

        # This must NOT raise.
        heartbeat.phase_report("test_node", "call", "passed")

    def test_write_to_impossible_path_does_not_corrupt_state(
        self, heartbeat, tmp_path, monkeypatch
    ):
        """After a failed write, the heartbeat module must still work."""
        call_count = 0

        def _fail_then_succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("simulated I/O failure")
            return builtins_open(*args, **kwargs)

        monkeypatch.setattr(heartbeat, "_open", _fail_then_succeed)

        heartbeat.HEARTBEAT_DIR = tmp_path
        # First write fails.
        heartbeat.phase_report("test_node", "call", "passed")
        # Second write succeeds (module recovered).
        heartbeat.phase_report("test_node2", "call", "passed")
        heartbeat.close()

        path = tmp_path / f"heartbeat-{os.getpid()}.jsonl"
        assert path.exists(), f"Heartbeat file should exist at {path}"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["nodeid"] == "test_node2"


# ── (c) NDJSON integrity ───────────────────────────────────────────────────


class TestNDJSONIntegrity:
    """Verify that the heartbeat file is valid NDJSON."""

    def test_file_ends_with_newline(self, heartbeat, tmp_path):
        """The heartbeat file must end with a newline character."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        heartbeat.phase_report("test_node", "call", "passed")
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        raw = path.read_bytes()
        assert raw.endswith(b"\n"), "Heartbeat file must end with newline"

    def test_line_by_line_parseable(self, heartbeat, tmp_path):
        """Every line must be valid JSON, even after many writes."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        for i in range(50):
            heartbeat.phase_report(f"test_node_{i}", "call", "passed")
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        assert len(lines) == 50, f"Expected 50 lines, got {len(lines)}"
        for i, line in enumerate(lines):
            record = json.loads(line)  # raises on invalid JSON
            assert record["nodeid"] == f"test_node_{i}"

    def test_no_truncated_records(self, heartbeat, tmp_path):
        """Records must be complete (no partial JSON)."""
        heartbeat.HEARTBEAT_DIR = tmp_path

        long_nid = (
            "tests/unit/test_example.py::test_param[with spaces and \u00e9\u00e0\u00fc]"
        )
        heartbeat.phase_report(long_nid, "call", "passed")
        heartbeat.close()

        path = heartbeat.HEARTBEAT_DIR / f"heartbeat-{os.getpid()}.jsonl"
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["nodeid"] == long_nid


# ── (d) Integration: hooks in conftest write to heartbeat ──────────────────


class TestConftestIntegration:
    """Verify that conftest hooks actually write to the heartbeat file."""

    def test_hook_writes_heartbeat_file(self, tmp_path, monkeypatch):
        """The conftest hooks must create a heartbeat file during a pytest run."""
        test_file = tmp_path / "test_dummy.py"
        test_file.write_text("def test_dummy():\n    assert True\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-v", "-q"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "PYTEST_XDIST_WORKER_COUNT": "0"},
        )

        assert result.returncode == 0


# ── (e) Watchdog: faulthandler re-arm per test ─────────────────────────────


class TestWatchdog:
    """Verify the faulthandler watchdog actually FIRES (WOT-2026-070i DoD-6).

    Red-first history: the three tests that lived here were cosmetic by the
    AGENTS.md rubric (one had a ``pass`` body, another only asserted
    ``hasattr(faulthandler, ...)``). None could reach the real defect: the
    watchdog was armed on ``logstart`` but cancelled on EVERY phase report,
    and ``setup`` is reported BEFORE the test body runs -- so the timer was
    always disarmed during ``call``, the only phase where a hang matters.

    These tests drive a real pytest subprocess and count dumps, so they fail
    if the cancel/re-arm contract regresses.
    """

    # The child conftest DELEGATES to the motor's real hooks, so a regression in
    # tests/conftest.py propagates here. It only redirects the dump to a real
    # file: the production hook writes to ``sys.stderr``, which pytest replaces
    # with a capture object, and faulthandler binds the file descriptor at arm
    # time -- so a stderr dump never reaches the parent and would read as a
    # false "0 dumps".
    _CONFTEST = """import sys
sys.path.insert(0, r"{motor_root}")

from tests import conftest as motor_conftest

_DUMP = open(r"{dump}", "w")
motor_conftest._arm_watchdog = (
    lambda seconds: __import__("faulthandler").dump_traceback_later(
        seconds, repeat=False, file=_DUMP
    )
    if motor_conftest._watchdog_enabled
    else None
)

pytest_runtest_logstart = motor_conftest.pytest_runtest_logstart
pytest_runtest_logreport = motor_conftest.pytest_runtest_logreport
"""

    _TESTS = """import time


def test_fast_1():
    time.sleep(0.1)


def test_slow():
    time.sleep(8)


def test_fast_2():
    time.sleep(0.1)
"""

    def _run(self, env_seconds):
        """Run a 3-test suite under a watchdog and return the dump text.

        The child MUST run outside the motor tree. Both ``tmp_path`` AND plain
        ``tempfile.mkdtemp()`` land inside ``tests/sandbox/test_runtime/``,
        because the root conftest hijacks ``tempfile.tempdir``/``TMPDIR``/
        ``TEMP``/``TMP`` for the session. A child launched there loads the
        motor's own root ``conftest.py``, whose watchdog hooks override the ones
        under test -- measured: 0 dumps inside the repo vs 1 outside, for an
        identical scenario. ``REAL_SYSTEM_TEMP`` is the conftest's own documented
        escape hatch (captured at import time, before the hijack), and the child
        env is sanitised so it cannot be redirected back into the tree.
        """
        from tests.conftest import REAL_SYSTEM_TEMP

        work = pathlib.Path(
            tempfile.mkdtemp(prefix="wd_probe_", dir=str(REAL_SYSTEM_TEMP))
        )
        dump = work / "dump.txt"
        (work / "conftest.py").write_text(
            self._CONFTEST.format(dump=dump, motor_root=_MOTOR_ROOT),
            encoding="utf-8",
        )
        (work / "test_wd.py").write_text(self._TESTS, encoding="utf-8")

        env = {
            k: v for k, v in os.environ.items() if k != "FAULTHANDLER_WATCHDOG_SECONDS"
        }
        for var in ("TMPDIR", "TEMP", "TMP"):
            env[var] = str(REAL_SYSTEM_TEMP)
        if env_seconds is not None:
            env["FAULTHANDLER_WATCHDOG_SECONDS"] = env_seconds

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "test_wd.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            cwd=str(work),
            env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        try:
            if not dump.exists():
                return ""
            return dump.read_text(encoding="utf-8", errors="replace")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_watchdog_dumps_exactly_once_for_the_slow_test(self, tmp_path):
        """3 tests (fast/slow/fast), watchdog N=3 under an 8s test -> exactly 1 dump.

        The dump target is a REAL file, never ``sys.stderr``: faulthandler writes
        to the file descriptor captured at arm time, and pytest swaps
        ``sys.stderr`` for its capture object, so a stderr dump never reaches the
        parent pipe. Measuring through stderr yields a false "0 dumps".
        """
        text = self._run(env_seconds="3")
        dumps = text.count("Timeout (")
        assert dumps == 1, f"DoD-6 exige exactamente 1 volcado, hubo {dumps}"
        assert "test_slow" in text, "el volcado debe nombrar el test que colgaba"

    def test_watchdog_is_disabled_by_default(self, tmp_path):
        """Without FAULTHANDLER_WATCHDOG_SECONDS the channel stays silent.

        A noisy watchdog is worse than none (contract STOP condition), so the
        same slow test must produce ZERO dumps when the env var is absent.
        """
        text = self._run(env_seconds=None)
        assert text.count("Timeout (") == 0, "el watchdog debe estar OFF por defecto"
