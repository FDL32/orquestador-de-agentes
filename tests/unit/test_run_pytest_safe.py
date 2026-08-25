"""Tests for the safe pytest runner argument contract."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"
SELECTION_PATH = PROJECT_ROOT / "scripts" / "test_selection.py"


def _load_conftest():
    """Load tests/conftest.py as a module to reuse REAL_SYSTEM_TEMP.

    pytest loads conftest as a plugin but not under an importable ``conftest``
    name from a sibling package, so resolve it by path (reusing an
    already-loaded instance from sys.modules when present).
    """
    for mod in sys.modules.values():
        if getattr(mod, "__file__", None) == str(
            PROJECT_ROOT / "tests" / "conftest.py"
        ):
            return mod
    spec = importlib.util.spec_from_file_location(
        "_conftest_under_test", PROJECT_ROOT / "tests" / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# WOT-2026-022g: every runner instance loaded during the test session gets its
# write-path constants redirected to a per-session tmp dir by the autouse fixture
# below. This registry lets the fixture reach instances created AFTER it ran
# (load_runner_module is called inside test bodies, not at collection time).
_LOADED_RUNNERS: list = []
_RUN_HISTORY_REDIRECT: dict = {}


def load_runner_module():
    spec = importlib.util.spec_from_file_location("run_pytest_safe", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # WOT-2026-022g: structural anti-contamination. If the autouse fixture has
    # installed a redirect, EVERY freshly loaded runner points its run-history /
    # last-run write paths at the per-test tmp. A new harness that calls main()
    # and forgets to monkeypatch RUN_HISTORY_JSONL no longer pollutes the real
    # runtime file: the default is already isolated.
    if _RUN_HISTORY_REDIRECT:
        module.RUN_HISTORY_JSONL = _RUN_HISTORY_REDIRECT["run_history"]
        module.LAST_RUN_JSON = _RUN_HISTORY_REDIRECT["last_run_json"]
        module.LAST_RUN_LOG = _RUN_HISTORY_REDIRECT["last_run_log"]
    _LOADED_RUNNERS.append(module)
    return module


@pytest.fixture(autouse=True)
def _isolate_run_history(tmp_path):
    """WOT-2026-022g: redirect RUN_HISTORY_JSONL / LAST_RUN_JSON / LAST_RUN_LOG of
    EVERY runner instance to a per-test tmp dir, so no main() can write the real
    runtime telemetry file even if its harness forgets the manual monkeypatch.

    This turns the anti-contamination invariant from DISCIPLINE (5 scattered
    manual patches) into a STRUCTURAL BARRIER. Tests may still override these
    paths explicitly; this only changes the DEFAULT from "the real file" to "an
    isolated tmp".
    """
    base = tmp_path / "_run_history_isolation" / ".agent" / "runtime" / "pytest-safe"
    base.mkdir(parents=True, exist_ok=True)
    _RUN_HISTORY_REDIRECT.clear()
    _RUN_HISTORY_REDIRECT.update(
        {
            "run_history": base / "run_history.jsonl",
            "last_run_json": base / "last-run.json",
            "last_run_log": base / "last-run.log",
        }
    )
    # Redirect any runner already loaded during THIS test (rare: load happens in
    # the body, but be safe).
    for mod in _LOADED_RUNNERS:
        mod.RUN_HISTORY_JSONL = _RUN_HISTORY_REDIRECT["run_history"]
        mod.LAST_RUN_JSON = _RUN_HISTORY_REDIRECT["last_run_json"]
        mod.LAST_RUN_LOG = _RUN_HISTORY_REDIRECT["last_run_log"]
    yield
    _LOADED_RUNNERS.clear()
    _RUN_HISTORY_REDIRECT.clear()


def load_selection_module():
    spec = importlib.util.spec_from_file_location("test_selection", SELECTION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_args_are_reported_as_default_discovery() -> None:
    runner = load_runner_module()

    assert runner.pytest_args_mode([]) == runner.DEFAULT_ARGS_MODE
    assert runner.pytest_args_mode(["--"]) == runner.DEFAULT_ARGS_MODE
    assert runner.default_test_target() == "tests/"


def test_explicit_args_are_not_reported_as_default_discovery() -> None:
    runner = load_runner_module()

    assert runner.pytest_args_mode(["--", "tests"]) == runner.EXPLICIT_ARGS_MODE
    assert runner.pytest_args_mode(["tests/unit"]) == runner.EXPLICIT_ARGS_MODE


# WOT-2026-010l: focal diff-driven test selector barriers.


def _make_run_fn(porcelain_z: str | None):
    """Return a fake subprocess.run yielding the given porcelain -z stdout.

    Passing ``None`` simulates ``git`` not being available (FileNotFoundError),
    which is how the scope-gate seam signals "diff cannot be read".
    """

    def run_fn(cmd, **kwargs):
        if porcelain_z is None:
            raise FileNotFoundError("git")

        class _Result:
            stdout = porcelain_z

        return _Result()

    return run_fn


def _porcelain(*paths: str) -> str:
    # ``git status --porcelain -z`` separates entries with NUL; each entry is
    # "XY <path>" and the stream is NUL-terminated.
    return "".join(f" M {p}\0" for p in paths)


def _repo_with_git(tmp_path: Path) -> Path:
    repo = tmp_path / "motor"
    (repo / ".git").mkdir(parents=True)
    (repo / "tests" / "unit").mkdir(parents=True)
    (repo / "tests" / "unit" / "test_run_pytest_safe.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    (repo / "tests" / "test_pre_handoff_guard.py").write_text(
        "def test_y():\n    assert True\n", encoding="utf-8"
    )
    (repo / "scripts").mkdir()
    return repo


def test_selector_git_failure_falls_open(tmp_path: Path) -> None:
    """Barrier: git diff fails -> fallback to canonical suite, auditable reason."""
    sel = load_selection_module()
    repo = _repo_with_git(tmp_path)
    result = sel.select_focal_tests(
        project_root=repo, motor_root=repo, run_fn=_make_run_fn(None)
    )
    assert result.is_fallback
    assert result.reason.startswith("no_diff_available")
    assert result.tests == []


@pytest.mark.parametrize("structural", ["pyproject.toml", "pytest.ini", ".agent/x.py"])
def test_selector_structural_change_falls_open(tmp_path: Path, structural: str) -> None:
    """Barrier: a structural file change -> fallback to canonical suite."""
    sel = load_selection_module()
    repo = _repo_with_git(tmp_path)
    run_fn = _make_run_fn(_porcelain(structural))
    result = sel.select_focal_tests(project_root=repo, motor_root=repo, run_fn=run_fn)
    assert result.is_fallback
    assert result.reason.startswith("structural_change")


def test_selector_unmapped_change_falls_open(tmp_path: Path) -> None:
    """Barrier: a change with no safe test mapping -> fallback."""
    sel = load_selection_module()
    repo = _repo_with_git(tmp_path)
    # A scripts module whose stem matches no test file under tests/.
    run_fn = _make_run_fn(_porcelain("scripts/nonexistent_module.py"))
    result = sel.select_focal_tests(project_root=repo, motor_root=repo, run_fn=run_fn)
    assert result.is_fallback
    assert result.reason.startswith("no_safe_mapping")


def test_selector_empty_diff_falls_open(tmp_path: Path) -> None:
    """Barrier: empty diff -> fallback to canonical suite."""
    sel = load_selection_module()
    repo = _repo_with_git(tmp_path)
    result = sel.select_focal_tests(
        project_root=repo, motor_root=repo, run_fn=_make_run_fn("")
    )
    assert result.is_fallback
    assert result.reason.startswith("empty_diff")


def test_selector_safe_subset_is_reproducible(tmp_path: Path) -> None:
    """Positive: a changed test file and a scripts/<name>.py map to a subset."""
    sel = load_selection_module()
    repo = _repo_with_git(tmp_path)
    run_fn = _make_run_fn(
        _porcelain(
            "tests/test_pre_handoff_guard.py",
            "scripts/run_pytest_safe.py",
        )
    )
    result = sel.select_focal_tests(project_root=repo, motor_root=repo, run_fn=run_fn)
    assert result.is_subset
    # Reproducible (sorted) and includes both the changed test and the
    # name-mapped test for scripts/run_pytest_safe.py.
    assert result.tests == sorted(result.tests)
    assert "tests/test_pre_handoff_guard.py" in result.tests
    assert "tests/unit/test_run_pytest_safe.py" in result.tests
    # Re-running yields the identical subset.
    again = sel.select_focal_tests(project_root=repo, motor_root=repo, run_fn=run_fn)
    assert again.tests == result.tests


def test_runner_resolve_focal_args_uses_real_selector() -> None:
    """resolve_focal_args wires the real selector against the live repo diff.

    It must return a (list, reason) tuple and never raise; whatever the live
    working tree looks like, an unsafe/empty resolution falls open (empty list
    + reason) rather than pass-opening silently.
    """
    runner = load_runner_module()
    extra, reason = runner.resolve_focal_args([])
    assert isinstance(extra, list)
    # Invariant: a subset (non-empty extra, reason None) XOR a fallback
    # (empty extra, reason set). Never both empty-and-no-reason (silent
    # pass-open) nor both populated.
    if extra:
        assert reason is None
    else:
        assert reason is not None


def test_selection_module_uses_scope_gate_seam_not_parallel_parser() -> None:
    """Anti-pattern guard: the selector must reuse get_changed_files, not a new
    git parser. It must not shell out to git directly."""
    source = SELECTION_PATH.read_text(encoding="utf-8")
    assert "scope_gate.get_changed_files" in source
    assert "subprocess" not in source
    assert '"git"' not in source


# WOT-2026-011e: opt-in xdist for an explicit unit subset, auditable fallback.


def test_xdist_enabled_for_explicit_unit_subset() -> None:
    """xdist runs only for level=unit + default discovery; reports workers."""
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("auto", "unit", mod.DEFAULT_ARGS_MODE)
    assert workers is not None and workers >= 2
    assert meta["enabled"] is True
    assert meta["workers"] == workers
    assert meta["fallback_reason"] is None


def test_xdist_explicit_worker_count() -> None:
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("4", "unit", mod.DEFAULT_ARGS_MODE)
    assert workers == 4
    assert meta["enabled"] is True


def test_xdist_not_requested_is_serial_backward_compat() -> None:
    """No flag -> serial, no xdist, backward compatible."""
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist(None, "unit", mod.DEFAULT_ARGS_MODE)
    assert workers is None
    assert meta["enabled"] is False
    assert meta["requested"] is False
    assert meta["fallback_reason"] == "not_requested"


def test_xdist_falls_back_to_serial_on_level_all() -> None:
    """The canonical close path (level=all) must NEVER parallelize."""
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("auto", "all", mod.DEFAULT_ARGS_MODE)
    assert workers is None
    assert meta["enabled"] is False
    assert "level=unit" in meta["fallback_reason"]


def test_xdist_falls_back_on_non_default_discovery() -> None:
    """Explicit/focal args are not the unit subset -> serial fallback."""
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("auto", "unit", "explicit_args")
    assert workers is None
    assert meta["enabled"] is False
    assert "default-discovery" in meta["fallback_reason"]


def test_xdist_falls_back_on_invalid_value() -> None:
    """A bad worker value falls back to serial with an auditable reason, never crashes."""
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("abc", "unit", mod.DEFAULT_ARGS_MODE)
    assert workers is None
    assert meta["enabled"] is False
    assert "invalid" in meta["fallback_reason"]


def test_xdist_falls_back_on_too_few_workers() -> None:
    mod = load_runner_module()
    workers, meta = mod.resolve_xdist("1", "unit", mod.DEFAULT_ARGS_MODE)
    assert workers is None
    assert "needs >=2" in meta["fallback_reason"]


# CTL-2026-007b (Fase 2.4): the canonical suite must run with the delivery
# repo's interpreter so the destination's deps are present. These barriers fail
# under the pre-fix behavior (command always used sys.executable).


def _make_venv(root: Path) -> Path:
    """Create a fake Windows-layout venv python under root; return its path."""
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    py = scripts / "python.exe"
    py.write_text("", encoding="utf-8")
    return py


def test_venv_python_finds_windows_layout(tmp_path: Path) -> None:
    mod = load_runner_module()
    py = _make_venv(tmp_path)
    assert mod._venv_python(tmp_path) == py


def test_venv_python_finds_posix_layout(tmp_path: Path) -> None:
    mod = load_runner_module()
    binp = tmp_path / ".venv" / "bin"
    binp.mkdir(parents=True)
    py = binp / "python"
    py.write_text("", encoding="utf-8")
    assert mod._venv_python(tmp_path) == py


def test_venv_python_absent_returns_none(tmp_path: Path) -> None:
    mod = load_runner_module()
    assert mod._venv_python(tmp_path) is None


def test_resolve_test_interpreter_prefers_destination_venv(tmp_path: Path) -> None:
    """When active root != motor and has a .venv, use the destination venv.

    Pre-fix the command always used sys.executable; this asserts the new
    selection so a regression back to sys.executable fails here.
    """
    mod = load_runner_module()
    destino = tmp_path / "destino"
    motor = tmp_path / "motor"
    destino.mkdir()
    motor.mkdir()
    venv_py = _make_venv(destino)

    mod._PROJECT_ROOT = destino
    mod._PROJECT_ROOT_BOOTSTRAP = motor
    assert mod.resolve_test_interpreter() == str(venv_py)
    assert mod.resolve_test_interpreter() != sys.executable


def test_resolve_test_interpreter_falls_back_to_sys_executable_for_motor(
    tmp_path: Path,
) -> None:
    """Single-repo/motor case (active == motor): keep sys.executable."""
    mod = load_runner_module()
    motor = tmp_path / "motor"
    motor.mkdir()
    mod._PROJECT_ROOT = motor
    mod._PROJECT_ROOT_BOOTSTRAP = motor
    assert mod.resolve_test_interpreter() == sys.executable


def test_resolve_test_interpreter_falls_back_when_destination_has_no_venv(
    tmp_path: Path,
) -> None:
    """Destination without a .venv falls back to sys.executable (legacy)."""
    mod = load_runner_module()
    destino = tmp_path / "destino"
    motor = tmp_path / "motor"
    destino.mkdir()
    motor.mkdir()
    mod._PROJECT_ROOT = destino
    mod._PROJECT_ROOT_BOOTSTRAP = motor
    assert mod.resolve_test_interpreter() == sys.executable


# =============================================================================
# WOT-2026-041h: the runner must DIAGNOSE an incomplete interpreter.
#
# Two branches of the same resolve_test_interpreter:
#   RAMA 1 (destination): interpreter without pytest -> "NO TESTS RAN" named the
#     SYMPTOM and hid the CAUSE. Fails closed (exit 5), so it stops the chain.
#   RAMA 2 (motor): `if active != motor` means the motor case falls to
#     sys.executable (:187), which may be the SYSTEM python without deps. Does
#     NOT fail closed -- measured cost ~1h with exit_code None / finished_at
#     None (= never finished, which is not the same as failed).
# =============================================================================


def test_041h_missing_pytest_diagnostic_names_interpreter_and_remedy(
    tmp_path: Path,
) -> None:
    """(a) RAMA 1: the message must name the interpreter, the cause and the fix.

    DoD is explicit: the output contains the interpreter PATH and the word
    pytest -- not just "NO TESTS RAN", which describes the symptom and lets an
    operator conclude "this repo has no tests" instead of "this env is
    incomplete".
    """
    mod = load_runner_module()
    fake_interpreter = str(tmp_path / "no_pytest" / "python.exe")
    diagnostic = mod.incomplete_interpreter_diagnostic(fake_interpreter)
    assert fake_interpreter in diagnostic, (
        "the diagnostic must NAME the resolved interpreter, else the operator "
        "cannot tell WHICH environment is incomplete"
    )
    assert "pytest" in diagnostic.lower(), "it must name the missing package"
    assert any(
        hint in diagnostic.lower() for hint in ("install", "instal", "uv ", "pip ")
    ), "a self-service gate must say HOW to fix it, not just what broke"


def test_041h_unittest_fallback_still_returns_nonzero(tmp_path: Path) -> None:
    """(b) No regression: the fallback path must keep failing closed.

    The ticket REFUTED its own initial suspicion (a misleading exit 0): the
    probe measured EXIT_CODE=5 and closeout_steps/gates.py:55 demands
    returncode == 0, so the chain already fails closed. This pins that.
    """
    mod = load_runner_module()
    command, runner = mod.select_test_runner(
        sys.executable, [], [], tmp_path, _probe=False
    )
    assert runner == "unittest", "no pytest -> unittest discover fallback"
    assert "unittest" in command


def test_041h_warns_when_motor_interpreter_is_not_the_venv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(d) RAMA 2: motor case + sys.executable != root .venv -> WARN naming BOTH.

    This is the branch that cost ~1h: it does NOT fail closed, it just runs with
    the wrong interpreter and dies by timeout leaving exit_code None.
    """
    mod = load_runner_module()
    motor = tmp_path / "motor"
    motor.mkdir()
    venv_py = _make_venv(motor)  # a .venv EXISTS...
    mod._PROJECT_ROOT = motor
    mod._PROJECT_ROOT_BOOTSTRAP = motor  # ...and this is the motor case

    resolved = mod.resolve_test_interpreter()
    captured = capsys.readouterr()
    warning = captured.out + captured.err

    assert resolved == sys.executable, (
        "(e) behavior is unchanged -- this is a WARN, never a redirect"
    )
    assert "WARN" in warning.upper(), "an undiagnosed mismatch is what cost ~1h"
    assert str(venv_py) in warning, "the WARN must name the venv NOT being used"
    assert sys.executable in warning, "and the interpreter actually in use"


def test_041h_no_warn_when_motor_runs_from_its_own_venv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(f) MUTATION half: with the CORRECT venv there must be SILENCE.

    Without this, the WARN could degrade into always-on noise and still pass
    the test above.
    """
    mod = load_runner_module()
    motor = tmp_path / "motor"
    motor.mkdir()
    mod._PROJECT_ROOT = motor
    mod._PROJECT_ROOT_BOOTSTRAP = motor
    # No .venv under motor -> nothing to compare against -> nothing to warn about.
    resolved = mod.resolve_test_interpreter()
    warning = (lambda c: c.out + c.err)(capsys.readouterr())

    assert resolved == sys.executable
    assert "WARN" not in warning.upper(), (
        "no .venv means no mismatch; warning here would be false noise"
    )


def test_041h_warn_is_not_fail_closed(tmp_path: Path) -> None:
    """(e) The WARN must NOT raise: CI, tox, uv run and pipx are legitimate
    cases where sys.executable is not the root .venv. Blocking them would be
    worse than the failure being diagnosed."""
    mod = load_runner_module()
    motor = tmp_path / "motor"
    motor.mkdir()
    _make_venv(motor)
    mod._PROJECT_ROOT = motor
    mod._PROJECT_ROOT_BOOTSTRAP = motor
    assert mod.resolve_test_interpreter() == sys.executable  # returns, never raises


# =============================================================================
# WOT-2026-017a: failed_test_ids field in last-run.json (G4)
# =============================================================================


def _parse_failed_ids_from_lines(lines: list[str]) -> list[str]:
    """Replicate the FAILED-line parser from stream_pytest for isolated testing.

    stream_pytest builds the failed_ids list from lines using a regex.
    We replicate the same contract here so we can test the parser without
    invoking pytest or a subprocess.
    """
    import re

    _failed_re = re.compile(r"^FAILED\s+(\S+)")
    result = []
    for line in lines:
        m = _failed_re.match(line.rstrip())
        if m:
            result.append(m.group(1))
    return result


class TestFailedTestIdsParsing:
    """G4: unit tests for the FAILED-line parser added by WOT-2026-017a.

    Tests feed example lines directly to the parser without invoking pytest,
    so they run in milliseconds and never spawn a subprocess.
    """

    def test_single_failed_line_parsed_correctly(self) -> None:
        """A single FAILED line yields the correct node-id."""
        lines = ["FAILED tests/foo/test_bar.py::TestFoo::test_one - AssertionError\n"]
        result = _parse_failed_ids_from_lines(lines)
        assert result == ["tests/foo/test_bar.py::TestFoo::test_one"]

    def test_multiple_failed_lines_parsed_in_order(self) -> None:
        """Multiple FAILED lines yield all node-ids in order."""
        lines = [
            "FAILED tests/foo/test_bar.py::TestFoo::test_one - AssertionError\n",
            "FAILED tests/foo/test_bar.py::TestFoo::test_two - ValueError\n",
            "FAILED tests/other/test_baz.py::test_top_level - RuntimeError\n",
        ]
        result = _parse_failed_ids_from_lines(lines)
        assert result == [
            "tests/foo/test_bar.py::TestFoo::test_one",
            "tests/foo/test_bar.py::TestFoo::test_two",
            "tests/other/test_baz.py::test_top_level",
        ]

    def test_non_failed_lines_are_ignored(self) -> None:
        """Lines that do not start with FAILED are ignored."""
        lines = [
            "PASSED tests/foo/test_bar.py::TestFoo::test_ok\n",
            "ERROR tests/foo/test_bar.py::TestFoo::test_err\n",
            "tests/foo/test_bar.py::TestFoo::test_ok PASSED\n",
            " FAILED tests/foo/test_bar.py::leading_space - note leading space\n",
            "FAILED tests/foo/test_bar.py::TestFoo::test_real - AssertionError\n",
        ]
        result = _parse_failed_ids_from_lines(lines)
        assert result == ["tests/foo/test_bar.py::TestFoo::test_real"]

    def test_empty_stream_yields_empty_list(self) -> None:
        """An empty stream (no lines) yields an empty list."""
        assert _parse_failed_ids_from_lines([]) == []

    def test_green_stream_yields_empty_list(self) -> None:
        """A fully green stream (no FAILED lines) yields an empty list."""
        lines = [
            "PASSED tests/foo/test_bar.py::TestFoo::test_ok\n",
            "1 passed in 0.12s\n",
        ]
        assert _parse_failed_ids_from_lines(lines) == []

    def test_node_id_without_class_parsed_correctly(self) -> None:
        """A top-level test (no class) is captured correctly."""
        lines = ["FAILED tests/test_simple.py::test_func - AssertionError\n"]
        result = _parse_failed_ids_from_lines(lines)
        assert result == ["tests/test_simple.py::test_func"]

    def test_first_token_only_captures_node_id_not_error_text(self) -> None:
        """Only the first token after FAILED is the node-id; remainder is ignored."""
        lines = [
            "FAILED tests/foo/test_bar.py::TestFoo::test_one"
            " - assert False != True (extra text here)\n"
        ]
        result = _parse_failed_ids_from_lines(lines)
        assert result == ["tests/foo/test_bar.py::TestFoo::test_one"]


class TestFailedTestIdsInSummary:
    """G4: integration-level checks for failed_test_ids field in last-run.json.

    These tests verify the contract without invoking the real pytest subprocess.
    They patch stream_pytest to return controlled (returncode, failed_ids) tuples
    and check that main() writes the expected fields to last-run.json.
    """

    def _stub_main(
        self, mod, tmp_path: Path, monkeypatch, stream_return: tuple
    ) -> None:
        """Wire a tmp_path-isolated environment into the module and call main()."""
        import json as _json

        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        last_run_json = (
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
        )
        last_run_log = tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.log"
        last_run_json.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", last_run_json)
        monkeypatch.setattr(mod, "LAST_RUN_LOG", last_run_log)
        # WOT-2026-021w: main() ahora hace append_run_history; sin aislar
        # RUN_HISTORY_JSONL estos harnesses contaminarian el jsonl REAL del
        # runtime con entradas sinteticas (tested_commit_sha=abc123).
        monkeypatch.setattr(
            mod,
            "RUN_HISTORY_JSONL",
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "run_history.jsonl",
        )

        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: stream_return)
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "abc123")
        lock_obj = {
            "pid": 0,
            "started_at": "2026-01-01T00:00:00+00:00",
            "cwd": str(tmp_path),
        }
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()
        return _json.loads(last_run_json.read_text(encoding="utf-8"))

    def test_failed_test_ids_empty_when_exit_code_zero(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When exit_code==0, failed_test_ids must be [] in last-run.json."""
        mod = load_runner_module()
        data = self._stub_main(mod, tmp_path, monkeypatch, stream_return=(0, [], []))
        assert data.get("exit_code") == 0
        assert data.get("failed_test_ids") == [], (
            "failed_test_ids must be [] when exit_code==0"
        )

    def test_failed_test_ids_list_when_exit_code_nonzero(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When exit_code!=0, failed_test_ids must contain the parsed node-ids."""
        mod = load_runner_module()
        failing_ids = [
            "tests/foo/test_bar.py::TestFoo::test_one",
            "tests/foo/test_bar.py::TestFoo::test_two",
        ]
        data = self._stub_main(
            mod, tmp_path, monkeypatch, stream_return=(1, failing_ids, [])
        )
        assert data.get("exit_code") == 1
        assert data.get("failed_test_ids") == failing_ids, (
            "failed_test_ids must contain the node-ids returned by stream_pytest"
        )

    def test_baseline_carry_forward_from_previous_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """baseline_failed_test_ids is read from the PREVIOUS last-run.json.

        Pre-populates last-run.json with failed_test_ids=[A, B], then calls
        main() with a green run (exit_code=0, failed_ids=[]). Verifies that
        the NEW last-run.json written by main() contains
        baseline_failed_test_ids == [A, B], proving the carry-forward mechanism.
        """
        import json as _json

        mod = load_runner_module()

        # Wire isolated paths.
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        last_run_json = (
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
        )
        last_run_log = tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.log"
        last_run_json.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", last_run_json)
        monkeypatch.setattr(mod, "LAST_RUN_LOG", last_run_log)
        # WOT-2026-021w: aislar RUN_HISTORY_JSONL para no contaminar el jsonl real.
        monkeypatch.setattr(
            mod,
            "RUN_HISTORY_JSONL",
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "run_history.jsonl",
        )

        # Pre-populate last-run.json with a previous red run.
        prev_failed = [
            "tests/foo/test_bar.py::TestFoo::test_a",
            "tests/foo/test_bar.py::TestFoo::test_b",
        ]
        last_run_json.write_text(
            _json.dumps(
                {"status": "finished", "exit_code": 1, "failed_test_ids": prev_failed}
            ),
            encoding="utf-8",
        )

        # Stub helpers so main() runs without a real repo. Green run this time.
        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: (0, [], []))
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "abc123")
        lock_obj = {
            "pid": 0,
            "started_at": "2026-01-01T00:00:00+00:00",
            "cwd": str(tmp_path),
        }
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()

        data = _json.loads(last_run_json.read_text(encoding="utf-8"))
        assert data.get("exit_code") == 0
        assert data.get("failed_test_ids") == [], (
            "green run must write empty failed_test_ids"
        )
        assert data.get("baseline_failed_test_ids") == prev_failed, (
            "baseline_failed_test_ids must carry-forward the failed_test_ids "
            "from the previous last-run.json"
        )


# =============================================================================
# WOT-2026-016k: error_test_ids field in last-run.json (separate from failed)
# =============================================================================


def _parse_test_ids_from_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """Replicate the FAILED+ERROR parser from stream_pytest for isolated testing.

    stream_pytest builds failed_ids and error_ids from lines using two regexes.
    We replicate the same contract here so we can test both parsers without
    invoking pytest or a subprocess.
    """
    import re

    _failed_re = re.compile(r"^FAILED\s+(\S+)")
    _error_re = re.compile(r"^ERROR\s+(\S+)")
    failed_result: list[str] = []
    error_result: list[str] = []
    for line in lines:
        m = _failed_re.match(line.rstrip())
        if m:
            failed_result.append(m.group(1))
        m = _error_re.match(line.rstrip())
        if m:
            error_result.append(m.group(1))
    return failed_result, error_result


class TestErrorTestIdsParsing:
    """G4: unit tests for the ERROR-line parser added by WOT-2026-016k.

    Tests feed example lines directly to the parser without invoking pytest,
    so they run in milliseconds and never spawn a subprocess.
    """

    def test_single_error_line_parsed_correctly(self) -> None:
        """A single ERROR line yields the correct node-id."""
        lines = ["ERROR tests/foo/test_bar.py::TestFoo::test_err -- AttributeError\n"]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == []
        assert errors == ["tests/foo/test_bar.py::TestFoo::test_err"]

    def test_multiple_error_lines_parsed_in_order(self) -> None:
        """Multiple ERROR lines yield all node-ids in order."""
        lines = [
            "ERROR tests/foo/test_bar.py::TestFoo::test_one -- AttributeError\n",
            "ERROR tests/foo/test_bar.py::TestFoo::test_two -- RuntimeError\n",
            "ERROR tests/other/test_baz.py::test_top_level -- ValueError\n",
        ]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == []
        assert errors == [
            "tests/foo/test_bar.py::TestFoo::test_one",
            "tests/foo/test_bar.py::TestFoo::test_two",
            "tests/other/test_baz.py::test_top_level",
        ]

    def test_mixed_failed_and_error_separated(self) -> None:
        """FAILED goes to failed_ids, ERROR goes to error_ids, never mixed."""
        lines = [
            "PASSED tests/foo/test_bar.py::TestFoo::test_ok\n",
            "FAILED tests/foo/test_bar.py::TestFoo::test_fail - AssertionError\n",
            "ERROR tests/foo/test_bar.py::TestFoo::test_err -- AttributeError\n",
            "FAILED tests/other/test_baz.py::test_other - ValueError\n",
            "ERROR tests/other/test_baz.py::test_err2 -- RuntimeError\n",
        ]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == [
            "tests/foo/test_bar.py::TestFoo::test_fail",
            "tests/other/test_baz.py::test_other",
        ]
        assert errors == [
            "tests/foo/test_bar.py::TestFoo::test_err",
            "tests/other/test_baz.py::test_err2",
        ]

    def test_empty_stream_yields_empty_lists(self) -> None:
        """An empty stream yields empty lists for both."""
        failed, errors = _parse_test_ids_from_lines([])
        assert failed == []
        assert errors == []

    def test_green_stream_yields_empty_lists(self) -> None:
        """A fully green stream yields empty lists."""
        lines = [
            "PASSED tests/foo/test_bar.py::TestFoo::test_ok\n",
            "1 passed in 0.12s\n",
        ]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == []
        assert errors == []

    def test_error_only_stream(self) -> None:
        """ERROR lines only: failed_ids must be empty, error_ids populated."""
        lines = [
            "ERROR tests/fake.py::test_teardown_error -- AttributeError\n",
        ]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == []
        assert errors == ["tests/fake.py::test_teardown_error"]

    def test_first_token_only_captures_node_id_not_error_text(self) -> None:
        """Only the first token after ERROR is the node-id; remainder is ignored."""
        lines = [
            "ERROR tests/foo/test_bar.py::TestFoo::test_one"
            " -- assert x == y (extra text here)\n"
        ]
        failed, errors = _parse_test_ids_from_lines(lines)
        assert failed == []
        assert errors == ["tests/foo/test_bar.py::TestFoo::test_one"]


class TestErrorTestIdsInSummary:
    """G4: integration-level checks for error_test_ids field in last-run.json.

    These tests verify the contract without invoking the real pytest subprocess.
    They patch stream_pytest to return controlled (returncode, failed_ids,
    error_ids) tuples and check that main() writes the expected fields to
    last-run.json.
    """

    def _stub_main(
        self, mod, tmp_path: Path, monkeypatch, stream_return: tuple
    ) -> None:
        """Wire a tmp_path-isolated environment into the module and call main()."""
        import json as _json

        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        last_run_json = (
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
        )
        last_run_log = tmp_path / ".agent" / "runtime" / "pytest-safe" / "last-run.log"
        last_run_json.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", last_run_json)
        monkeypatch.setattr(mod, "LAST_RUN_LOG", last_run_log)
        # WOT-2026-021w: main() ahora hace append_run_history; sin aislar
        # RUN_HISTORY_JSONL estos harnesses contaminarian el jsonl REAL del
        # runtime con entradas sinteticas (tested_commit_sha=abc123).
        monkeypatch.setattr(
            mod,
            "RUN_HISTORY_JSONL",
            tmp_path / ".agent" / "runtime" / "pytest-safe" / "run_history.jsonl",
        )

        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: stream_return)
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "abc123")
        lock_obj = {
            "pid": 0,
            "started_at": "2026-01-01T00:00:00+00:00",
            "cwd": str(tmp_path),
        }
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()
        return _json.loads(last_run_json.read_text(encoding="utf-8"))

    def test_error_test_ids_in_summary_on_teardown_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When stream_pytest returns ERROR ids, they appear in error_test_ids."""
        mod = load_runner_module()
        error_ids = ["tests/fake.py::test_teardown_error"]
        data = self._stub_main(
            mod, tmp_path, monkeypatch, stream_return=(1, [], error_ids)
        )
        assert data.get("exit_code") == 1
        assert data.get("failed_test_ids") == []
        assert data.get("error_test_ids") == error_ids, (
            "error_test_ids must contain the node-ids returned by stream_pytest"
        )

    def test_error_and_failed_separated_in_summary(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """FAILED and ERROR stay in separate fields in last-run.json."""
        mod = load_runner_module()
        failing_ids = [
            "tests/foo/test_bar.py::TestFoo::test_one",
        ]
        error_ids = [
            "tests/foo/test_bar.py::TestFoo::test_err",
        ]
        data = self._stub_main(
            mod, tmp_path, monkeypatch, stream_return=(1, failing_ids, error_ids)
        )
        assert data.get("exit_code") == 1
        assert data.get("failed_test_ids") == failing_ids
        assert data.get("error_test_ids") == error_ids
        # They must not be mixed: failed_test_ids must NOT contain error ids
        for eid in error_ids:
            assert eid not in data.get("failed_test_ids", []), (
                "error ids must not leak into failed_test_ids"
            )
        # and error_test_ids must NOT contain failed ids
        for fid in failing_ids:
            assert fid not in data.get("error_test_ids", []), (
                "failed ids must not leak into error_test_ids"
            )

    def test_error_test_ids_empty_when_green(self, tmp_path: Path, monkeypatch) -> None:
        """Green run: both failed_test_ids and error_test_ids are []."""
        mod = load_runner_module()
        data = self._stub_main(mod, tmp_path, monkeypatch, stream_return=(0, [], []))
        assert data.get("exit_code") == 0
        assert data.get("failed_test_ids") == []
        assert data.get("error_test_ids") == []

    def test_stream_pytest_real_error_re_with_mocked_subprocess(  # noqa: C901
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Exercise the REAL _error_re in stream_pytest via subprocess mock.

        This is the mutation-verify-critical test: it calls stream_pytest
        with a mocked Popen that produces ERROR lines, so the _error_re
        compiled regex inside stream_pytest (NOT the replica) must match them.
        If someone removes _error_re or breaks the regex, this test fails.
        """
        mod = load_runner_module()

        class _Capture:
            call_args: list | None = None

        class _MockProcess:
            returncode = 1

            def __init__(self, *a, **kw):
                self._idx = 0
                self._stdout_lines = [
                    "============================= test session starts =============================\n",
                    "platform win32 -- Python 3.10.19, pytest-9.0.3\n",
                    "collected 3 items\n\n",
                    "tests/unit/test_a.py::test_pass PASSED                             [ 33%]\n",
                    "tests/unit/test_a.py::test_fail FAILED                             [ 66%]\n",
                    "ERROR tests/unit/test_b.py::test_teardown_err -- AttributeError: 'NoneType'\n",
                    "\n=========================== short test summary ===========================\n",
                    "FAILED tests/unit/test_a.py::test_fail - AssertionError: assert False\n",
                    "1 failed, 1 passed, 1 error in 0.12s\n",
                ]

            @property
            def stdout(self):
                return self

            def __iter__(self):
                return self

            def __next__(self):
                if self._idx >= len(self._stdout_lines):
                    raise StopIteration
                line = self._stdout_lines[self._idx]
                self._idx += 1
                return line

            def wait(self):
                return self.returncode

            def terminate(self):
                pass

            def kill(self):
                pass

            def poll(self):
                return 1

        cap = _Capture()

        def mock_popen(command, *a, **kw):
            cap.call_args = command
            return _MockProcess()

        monkeypatch.setattr(mod.subprocess, "Popen", mock_popen)

        # Call the REAL stream_pytest (not a replica)
        returncode, failed_ids, error_ids = mod.stream_pytest(["pytest", "tests/"])

        assert returncode == 1
        assert failed_ids == ["tests/unit/test_a.py::test_fail"]
        assert error_ids == ["tests/unit/test_b.py::test_teardown_err"]
        # Critical: must not be empty - if _error_re is broken/removed, this fails
        assert len(error_ids) > 0, (
            "stream_pytest must capture ERROR lines via _error_re; "
            "if _error_re is removed or broken, error_ids stays empty"
        )


# =============================================================================
# WOT-2026-020f: state_leak covers *_WOT-*.md + basetemp outside repo
# =============================================================================


class TestStateLeakWotFiles:
    """WOT-2026-020f: check_canonical_state_leak must detect deletion of
    *_WOT-*.md files (AUDIT_WOT-*, PLAN_WOT-*), not just the 4 canonical files."""

    def test_wot_file_deletion_detected(self, tmp_path: Path, monkeypatch) -> None:
        mod = load_runner_module()
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wot_file = collab / "AUDIT_WOT-2026-020f.md"
        wot_file.write_text("audit content", encoding="utf-8")

        monkeypatch.setattr(mod, "_AGENT_DIR", tmp_path / ".agent")
        snapshot = mod.snapshot_canonical_state()
        assert "AUDIT_WOT-2026-020f.md" in snapshot

        wot_file.unlink()
        leaked = mod.check_canonical_state_leak(snapshot)
        assert "AUDIT_WOT-2026-020f.md" in leaked

    def test_wot_file_content_change_detected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        mod = load_runner_module()
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        wot_file = collab / "PLAN_WOT-2026-999z.md"
        wot_file.write_text("original", encoding="utf-8")

        monkeypatch.setattr(mod, "_AGENT_DIR", tmp_path / ".agent")
        snapshot = mod.snapshot_canonical_state()

        wot_file.write_text("modified", encoding="utf-8")
        leaked = mod.check_canonical_state_leak(snapshot)
        assert "PLAN_WOT-2026-999z.md" in leaked

    def test_no_wot_files_no_leak(self, tmp_path: Path, monkeypatch) -> None:
        mod = load_runner_module()
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)

        monkeypatch.setattr(mod, "_AGENT_DIR", tmp_path / ".agent")
        snapshot = mod.snapshot_canonical_state()
        leaked = mod.check_canonical_state_leak(snapshot)
        assert leaked == []

    def test_archived_wot_files_not_false_leak(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CTL-2026-012j: archived WOT files under _archive/ must NOT be a false leak.

        Regression barrier for the false-positive that turned a green suite
        (0 failed) into exit 1: the snapshot keyed archived files by basename,
        but the check looked them up at the collab root (where they do not
        exist), so every unchanged archived file was reported as a leak. With
        the relative-path key, archived files are found at their real path and
        an unchanged tree reports no leak.
        """
        mod = load_runner_module()
        collab = tmp_path / ".agent" / "collaboration"
        archive_dir = collab / "_archive" / "plan_audit"
        archive_dir.mkdir(parents=True)
        archived = archive_dir / "AUDIT_WOT-2026-015l.md"
        archived.write_text("archived audit content", encoding="utf-8")

        monkeypatch.setattr(mod, "_AGENT_DIR", tmp_path / ".agent")
        snapshot = mod.snapshot_canonical_state()
        # The archived file is keyed by its path relative to collab, not basename.
        assert "_archive/plan_audit/AUDIT_WOT-2026-015l.md" in snapshot
        assert "AUDIT_WOT-2026-015l.md" not in snapshot

        # No change during the "run" -> no leak (the pre-fix bug reported this).
        leaked = mod.check_canonical_state_leak(snapshot)
        assert leaked == [], (
            f"FALSE POSITIVE: unchanged archived WOT file reported as leak: {leaked}"
        )

    def test_archived_wot_file_change_detected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CTL-2026-012j: a real mutation of an archived WOT file IS detected.

        The relative-path key must not weaken the barrier: changing an archived
        file's content during the run is still a leak (named by its relative path).
        """
        mod = load_runner_module()
        collab = tmp_path / ".agent" / "collaboration"
        archive_dir = collab / "_archive" / "plan_audit"
        archive_dir.mkdir(parents=True)
        archived = archive_dir / "PLAN_WOT-2026-016b.md"
        archived.write_text("original archived", encoding="utf-8")

        monkeypatch.setattr(mod, "_AGENT_DIR", tmp_path / ".agent")
        snapshot = mod.snapshot_canonical_state()

        archived.write_text("mutated archived", encoding="utf-8")
        leaked = mod.check_canonical_state_leak(snapshot)
        assert "_archive/plan_audit/PLAN_WOT-2026-016b.md" in leaked, (
            f"Expected archived WOT mutation to be detected, got: {leaked}"
        )


class TestBasetempOutsideRepo:
    """WOT-2026-020f: make_run_dir must place basetemp OUTSIDE the repo motor
    so staged changes in the motor are not visible to resolve_evidence when
    project_root=tmp_path.

    NOTE: conftest hijacks tempfile.tempdir to a path inside the repo for test
    sandboxing. These tests restore tempfile.tempdir to REAL_SYSTEM_TEMP, the
    real system temp captured by tests/conftest.py at import-time (before the
    session-scoped fixture hijacks os.environ), to validate production
    behavior (run_pytest_safe.py runs as a script, before pytest/conftest load).
    """

    @pytest.fixture(autouse=True)
    def _restore_real_tempdir(self, monkeypatch):
        import tempfile

        conftest = _load_conftest()
        monkeypatch.setattr(tempfile, "tempdir", str(conftest.REAL_SYSTEM_TEMP))
        yield

    def test_make_run_dir_outside_runtime_dir(self) -> None:
        """basetemp must NOT be under RUNTIME_DIR (the old in-repo location).

        WOT-2026-020f: previously make_run_dir returned RUNTIME_DIR/run-*,
        placing basetemp inside the repo motor -> staged changes visible to
        resolve_evidence. Now it uses tempfile.gettempdir() as base.
        """
        mod = load_runner_module()
        run_dir = mod.make_run_dir()
        runtime_dir = mod.RUNTIME_DIR.resolve()
        assert not run_dir.is_relative_to(runtime_dir), (
            f"basetemp {run_dir} must not be under RUNTIME_DIR {runtime_dir}"
        )

    def test_make_run_dir_in_tempdir(self) -> None:
        import tempfile

        mod = load_runner_module()
        run_dir = mod.make_run_dir()
        temp_base = Path(tempfile.gettempdir()).resolve()
        assert run_dir.is_relative_to(temp_base), (
            f"basetemp {run_dir} must be under tempfile.gettempdir() {temp_base}"
        )
        # WOT-2026-021b: non-tautological check against the real DoD invariant
        # from 020f ("basetemp outside the repo motor"), independent of
        # whatever tempfile.tempdir was restored to above.
        assert not run_dir.is_relative_to(PROJECT_ROOT), (
            f"basetemp {run_dir} must not be under the repo motor {PROJECT_ROOT}"
        )


# =============================================================================
# WOT-2026-021w: run-history telemetry (parse_run_metrics + append_run_history)
# =============================================================================

_REAL_SUMMARY_LOG = """\
============================= slowest 25 durations =============================
7.58s teardown tests/unit/test_work_plan_schema.py::test_deliverable_type_extra
2.27s call     tests/test_check_publication_gate.py::test_dirty_sibling_blocks
0.03s setup    tests/unit/test_foo.py::test_bar
==================== 3757 passed, 47 skipped in 219.73s (0:03:39) ==============
"""


class TestParseRunMetrics:
    """Pure-function parser: counts + duration + top-slowest from log text."""

    def test_parses_passed_skipped_duration(self) -> None:
        mod = load_runner_module()
        m = mod.parse_run_metrics(_REAL_SUMMARY_LOG)
        assert m["passed"] == 3757
        assert m["skipped"] == 47
        assert m["failed_count"] is None  # no "failed" token in this summary
        assert m["duration_s"] == 219.73

    def test_parses_top_slowest_table(self) -> None:
        mod = load_runner_module()
        m = mod.parse_run_metrics(_REAL_SUMMARY_LOG)
        assert len(m["top_slowest"]) == 3
        first = m["top_slowest"][0]
        assert first["seconds"] == 7.58
        assert first["phase"] == "teardown"
        assert first["nodeid"].endswith("::test_deliverable_type_extra")

    def test_parses_failed_and_errors(self) -> None:
        mod = load_runner_module()
        m = mod.parse_run_metrics("==== 1 failed, 2 passed, 3 errors in 4.20s ====")
        assert m["failed_count"] == 1
        assert m["passed"] == 2
        assert m["errors"] == 3
        assert m["duration_s"] == 4.20

    def test_empty_log_returns_all_none(self) -> None:
        mod = load_runner_module()
        m = mod.parse_run_metrics("")
        assert m["passed"] is None
        assert m["skipped"] is None
        assert m["failed_count"] is None
        assert m["duration_s"] is None
        assert m["top_slowest"] == []

    def test_malformed_log_does_not_raise(self) -> None:
        mod = load_runner_module()
        # garbage without a summary line or a durations table -> all defaults
        m = mod.parse_run_metrics("random noise\nno summary here\n123 not-a-count\n")
        assert m["passed"] is None
        assert m["top_slowest"] == []

    def test_durations_table_without_summary_line(self) -> None:
        """A partial log (aborted before the summary) still yields the table."""
        mod = load_runner_module()
        log = (
            "===== slowest 3 durations =====\n"
            "1.11s call tests/x.py::test_a\n"
            "0.50s setup tests/x.py::test_b\n"
        )
        m = mod.parse_run_metrics(log)
        assert m["passed"] is None
        assert len(m["top_slowest"]) == 2

    def test_parametrized_nodeid_with_space_is_not_truncated(self) -> None:
        """A parametrized nodeid containing a space must be captured whole, not
        truncated at the first space (regression pin for the \\S.* nodeid group)."""
        mod = load_runner_module()
        log = (
            "===== slowest 1 durations =====\n"
            "2.00s call tests/x.py::test_a[param with space]\n"
        )
        m = mod.parse_run_metrics(log)
        assert len(m["top_slowest"]) == 1
        assert m["top_slowest"][0]["nodeid"] == "tests/x.py::test_a[param with space]"


class TestTelemetrySanityWarning:
    """WOT-2026-022h: main() must emit a sanity signal when the suite finishes
    green (exit_code == 0) but parse_run_metrics found no 'passed' count -- the
    symptom of a pytest summary-line format change that would silently degrade
    run-history telemetry to counts=None.
    """

    def _run_main_with_log(self, tmp_path, monkeypatch, capsys, log_text):
        mod = load_runner_module()
        base = Path(mod.LAST_RUN_JSON).parent
        base.mkdir(parents=True, exist_ok=True)
        # The log parse_run_metrics reads is LAST_RUN_LOG; write our text there.
        Path(mod.LAST_RUN_LOG).write_text(log_text, encoding="utf-8")

        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        # exit_code 0, and stream_pytest must NOT overwrite our log.
        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: (0, [], []))
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "sha0")
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: {"pid": 0})
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])
        mod.main()
        # Read the persisted summary from last-run.json.
        summary = json.loads(Path(mod.LAST_RUN_JSON).read_text(encoding="utf-8"))
        return summary, capsys.readouterr()

    def test_green_run_without_summary_line_warns(self, tmp_path, monkeypatch, capsys):
        """exit 0 + no 'passed' count -> sanity warning present.

        Mutation: drop the `if exit_code == 0 and _metrics.get("passed") is None`
        branch in main() and this fails (no warning emitted).
        """
        log = "collected 0 items\nno summary line here at all\n"
        summary, captured = self._run_main_with_log(tmp_path, monkeypatch, capsys, log)
        assert summary.get("telemetry_sanity_warning"), (
            "a green run whose log has no 'passed' count must carry a "
            "telemetry_sanity_warning in the summary"
        )
        assert "telemetria vacia inesperada" in captured.err

    def test_green_run_with_normal_summary_does_not_warn(
        self, tmp_path, monkeypatch, capsys
    ):
        """exit 0 + a real 'N passed' line -> no sanity warning (no false alarm)."""
        log = "===== 5 passed in 1.23s =====\n"
        summary, captured = self._run_main_with_log(tmp_path, monkeypatch, capsys, log)
        assert "telemetry_sanity_warning" not in summary
        assert "telemetria vacia inesperada" not in captured.err


class TestAppendRunHistory:
    """append_run_history: append-only jsonl, tail-cap, fail-open."""

    def _wire_history(self, mod, tmp_path: Path, monkeypatch) -> Path:
        hist = tmp_path / ".agent" / "runtime" / "pytest-safe" / "run_history.jsonl"
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", hist)
        return hist

    def test_appends_one_json_line(self, tmp_path: Path, monkeypatch) -> None:
        import json as _json

        mod = load_runner_module()
        hist = self._wire_history(mod, tmp_path, monkeypatch)
        summary = {
            "finished_at": "2026-07-11T03:00:00+00:00",
            "level": "all",
            "status": "finished",
            "exit_code": 0,
            "passed": 3757,
            "skipped": 47,
            "duration_s": 219.73,
            "top_slowest": [{"seconds": 7.58, "phase": "teardown", "nodeid": "x::y"}],
            "tested_commit_sha": "abc123",
        }
        mod.append_run_history(summary)
        lines = [ln for ln in hist.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1
        rec = _json.loads(lines[0])
        assert rec["passed"] == 3757
        assert rec["tested_commit_sha"] == "abc123"
        assert rec["level"] == "all"

    def test_appends_are_cumulative(self, tmp_path: Path, monkeypatch) -> None:
        mod = load_runner_module()
        hist = self._wire_history(mod, tmp_path, monkeypatch)
        for i in range(3):
            mod.append_run_history({"exit_code": i})
        lines = [ln for ln in hist.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 3

    def test_tail_cap_bounds_growth(self, tmp_path: Path, monkeypatch) -> None:
        mod = load_runner_module()
        hist = self._wire_history(mod, tmp_path, monkeypatch)
        monkeypatch.setattr(mod, "RUN_HISTORY_MAX", 5)
        for i in range(12):
            mod.append_run_history({"exit_code": i})
        import json as _json

        lines = [ln for ln in hist.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 5, "history must be tail-capped to RUN_HISTORY_MAX"
        # the retained records must be the MOST RECENT (7..11), not the oldest
        exit_codes = [_json.loads(ln)["exit_code"] for ln in lines]
        assert exit_codes == [7, 8, 9, 10, 11]

    def test_fail_open_never_raises(self, tmp_path: Path, monkeypatch) -> None:
        """A tracker failure must be swallowed, never propagated to the run."""
        mod = load_runner_module()

        # Point RUN_HISTORY_JSONL at a path whose parent cannot be created
        # (a file used as a directory) to force an OSError inside the writer.
        bad_parent = tmp_path / "afile"
        bad_parent.write_text("x", encoding="utf-8")
        bad_path = bad_parent / "sub" / "run_history.jsonl"
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", bad_path)

        # Must return None without raising even though the write is impossible.
        assert mod.append_run_history({"exit_code": 0}) is None


class TestRunHistoryInSummary:
    """Integration: main() enriches last-run.json with metrics AND writes a
    run_history line, using the _stub_main harness."""

    def _stub_main_with_log(
        self, mod, tmp_path: Path, monkeypatch, log_text: str
    ) -> tuple:
        """Wire a tmp_path env; stub stream_pytest to WRITE the log then return
        (0, [], []) so main()'s parse-enrich path reads real metrics."""
        import json as _json

        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        base = tmp_path / ".agent" / "runtime" / "pytest-safe"
        base.mkdir(parents=True, exist_ok=True)
        last_run_json = base / "last-run.json"
        last_run_log = base / "last-run.log"
        history = base / "run_history.jsonl"
        monkeypatch.setattr(mod, "LAST_RUN_JSON", last_run_json)
        monkeypatch.setattr(mod, "LAST_RUN_LOG", last_run_log)
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", history)

        def _fake_stream(cmd):
            last_run_log.write_text(log_text, encoding="utf-8")
            return (0, [], [])

        monkeypatch.setattr(mod, "stream_pytest", _fake_stream)
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "deadbeef")
        lock_obj = {"pid": 0, "started_at": "2026-01-01T00:00:00+00:00", "cwd": "x"}
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()
        summary = _json.loads(last_run_json.read_text(encoding="utf-8"))
        hist_lines = [
            ln for ln in history.read_text(encoding="utf-8").splitlines() if ln
        ]
        return summary, hist_lines

    def test_metrics_land_in_last_run_json(self, tmp_path: Path, monkeypatch) -> None:
        mod = load_runner_module()
        summary, _ = self._stub_main_with_log(
            mod, tmp_path, monkeypatch, _REAL_SUMMARY_LOG
        )
        assert summary["passed"] == 3757
        assert summary["skipped"] == 47
        assert summary["duration_s"] == 219.73
        assert len(summary["top_slowest"]) == 3

    def test_history_line_written_on_run(self, tmp_path: Path, monkeypatch) -> None:
        import json as _json

        mod = load_runner_module()
        _, hist_lines = self._stub_main_with_log(
            mod, tmp_path, monkeypatch, _REAL_SUMMARY_LOG
        )
        assert len(hist_lines) == 1
        rec = _json.loads(hist_lines[0])
        assert rec["passed"] == 3757
        assert rec["tested_commit_sha"] == "deadbeef"
        assert rec["level"] == "all"


class TestRunHistoryTestIsolation:
    """WOT-2026-021w barrera anti-contaminacion: ningun harness que llame main()
    debe escribir en el run_history.jsonl REAL del runtime.

    Origen (2026-07-11): desde 021w, main() llama append_run_history; los
    harnesses _stub_main PRE-EXISTENTES (TestFailedTestIdsInSummary /
    TestErrorTestIdsInSummary / test_baseline_carry_forward) parcheaban
    LAST_RUN_JSON/LOG pero NO RUN_HISTORY_JSONL -> contaminaron el jsonl real con
    entradas sinteticas (tested_commit_sha=abc123). Este guard lo caza en el
    futuro: si un main() de test escribe en el RUN_HISTORY_JSONL real, falla.
    """

    def test_main_does_not_write_the_real_run_history(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        mod = load_runner_module()

        # Sentinel: apunta el RUN_HISTORY_JSONL REAL del modulo a un fichero
        # centinela FUERA de cualquier tmp que un harness pudiera parchear, y
        # afirmalo intacto tras un main() que -bien aislado- debe escribir en
        # OTRO sitio (el tmp del harness), nunca aqui.
        sentinel = tmp_path / "REAL_runtime" / "run_history.jsonl"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("SENTINEL-UNTOUCHED\n", encoding="utf-8")
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", sentinel)

        # Un harness BIEN aislado re-parchea RUN_HISTORY_JSONL a su propio tmp
        # (como hace _stub_main_with_log). Simulamos ese contrato: el harness
        # aislado escribe en harness_hist, NO en el sentinel.
        harness_hist = tmp_path / "harness" / "run_history.jsonl"
        base = tmp_path / ".agent" / "runtime" / "pytest-safe"
        base.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", base / "last-run.json")
        monkeypatch.setattr(mod, "LAST_RUN_LOG", base / "last-run.log")
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", harness_hist)  # aislado
        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: (0, [], []))
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "sha0")
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: {"pid": 0})
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()

        # El sentinel (que representa el run_history REAL cuando el harness lo
        # deja sin re-parchear) permanece intacto; el write fue al tmp aislado.
        assert sentinel.read_text(encoding="utf-8") == "SENTINEL-UNTOUCHED\n", (
            "un main() de test escribio en el RUN_HISTORY_JSONL no-aislado: "
            "el harness debe parchear RUN_HISTORY_JSONL a tmp_path"
        )
        assert harness_hist.exists(), "el harness aislado debe escribir en su tmp"

    def test_forgetful_harness_still_cannot_touch_real_run_history(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-022g: the STRUCTURAL barrier. A harness that calls main() and
        FORGETS to monkeypatch RUN_HISTORY_JSONL still does not pollute the real
        runtime telemetry, because the autouse fixture already redirected the
        default write path to a per-test tmp.

        This is what TestRunHistoryTestIsolation's single-body test could not
        guarantee: it only proved its OWN body was isolated. Here we deliberately
        OMIT the RUN_HISTORY_JSONL patch and rely on the structural default.

        Mutation: clear _RUN_HISTORY_REDIRECT in load_runner_module (disable the
        structural redirect) and this test RED-flags, because main() would write
        the real (module-default) run_history path.
        """
        mod = load_runner_module()

        # The default RUN_HISTORY_JSONL is ALREADY inside the per-test tmp thanks
        # to the autouse fixture. Capture it and assert main() writes THERE, never
        # under the real repo runtime dir.
        default_hist = Path(mod.RUN_HISTORY_JSONL)
        assert default_hist.is_relative_to(tmp_path), (
            "the autouse fixture must redirect RUN_HISTORY_JSONL into the test tmp"
        )
        assert not default_hist.is_relative_to(
            PROJECT_ROOT / ".agent" / "runtime" / "pytest-safe"
        ), "RUN_HISTORY_JSONL must NOT default to the real runtime dir under test"

        # A forgetful harness: patches only stream/lock, NOT RUN_HISTORY_JSONL.
        base = Path(mod.LAST_RUN_JSON).parent
        base.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: (0, [], []))
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "sha0")
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: {"pid": 0})
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()

        # main() wrote (if anything) to the isolated default path, inside tmp.
        assert default_hist.is_relative_to(tmp_path)


# =============================================================================
# WOT-2026-022i: Windows-safe PID liveness (SystemError no propaga, fail-safe)
# =============================================================================


class TestIsPidRunningWindowsSafe:
    """WOT-2026-022i: is_pid_running must never let os.kill's SystemError
    (Windows, foreign live pid) crash acquire_lock.

    Fail-safe conservative: on doubt treat the PID as alive so an active lock is
    never broken or released. Only an unambiguously-dead PID returns False.
    """

    def test_non_positive_pid_is_false(self) -> None:
        """pid <= 0 is never a live process (DoD invariant, unchanged)."""
        mod = load_runner_module()
        assert mod.is_pid_running(0) is False
        assert mod.is_pid_running(-1) is False

    def test_os_kill_systemerror_treated_as_alive(self, monkeypatch) -> None:
        """Mutation-critical: os.kill raising SystemError (Windows foreign live
        pid) must return True, not propagate.

        Restoring the pre-fix `os.kill(pid, 0)` with only `except OSError` lets
        SystemError escape (it is NOT an OSError) -> this test fails.
        """
        import os
        import shutil

        mod = load_runner_module()
        # Force the os.kill fallback (tasklist unavailable) so the SystemError
        # seam is exercised regardless of the host platform.
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)

        def _boom(pid: int, sig: int) -> None:
            raise SystemError("windows foreign live pid probe")

        monkeypatch.setattr(os, "kill", _boom)
        assert mod.is_pid_running(12345) is True

    def test_os_kill_process_lookup_error_is_dead(self, monkeypatch) -> None:
        """Unambiguously-dead PID (ProcessLookupError) stays False."""
        import os
        import shutil

        mod = load_runner_module()
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)

        def _dead(pid: int, sig: int) -> None:
            raise ProcessLookupError(3, "No such process")

        monkeypatch.setattr(os, "kill", _dead)
        assert mod.is_pid_running(99999) is False

    def test_os_kill_other_oserror_is_alive(self, monkeypatch) -> None:
        """A non-ProcessLookupError OSError (e.g. PermissionError) is
        inconclusive -> conservative alive (do not break a foreign lock)."""
        import os
        import shutil

        mod = load_runner_module()
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)

        def _denied(pid: int, sig: int) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(os, "kill", _denied)
        assert mod.is_pid_running(12345) is True

    @staticmethod
    def _force_windows_tasklist_branch(monkeypatch, shutil_mod) -> None:
        """Make the Windows `tasklist` branch of is_pid_running REACHABLE.

        is_pid_running gates that branch on ``os.name == "nt"``. Without forcing
        os.name, the branch is DEAD CODE on Linux: mocking shutil.which and
        subprocess.run has no effect because control never reaches them, and the
        call falls through to os.kill instead.

        That is what broke CI (Linux) while the suite was green on Windows: the
        tests passed locally by accident of the host platform, not because the
        seam worked. Forcing os.name exercises the branch on EVERY platform --
        the same approach the os.kill tests in this class already take
        ("the seam is exercised regardless of the host platform").
        """
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(
            shutil_mod,
            "which",
            lambda name, *a, **k: (
                "C:/fake/tasklist.EXE" if name == "tasklist" else None
            ),
        )

    def test_tasklist_miss_is_dead(self, monkeypatch) -> None:
        """Windows tasklist reports the PID absent -> unambiguously dead."""
        import shutil
        import subprocess

        mod = load_runner_module()
        self._force_windows_tasklist_branch(monkeypatch, shutil)

        class _Result:
            returncode = 0
            stdout = "INFO: No tasks are running which match the specified criteria.\n"

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Result())
        assert mod.is_pid_running(99999) is False

    def test_tasklist_hit_is_alive(self, monkeypatch) -> None:
        """Windows tasklist reports the PID present -> alive."""
        import shutil
        import subprocess

        mod = load_runner_module()
        self._force_windows_tasklist_branch(monkeypatch, shutil)

        class _Result:
            returncode = 0
            stdout = "python.exe                  12345 Console                    1     60,000 K\n"

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Result())
        assert mod.is_pid_running(12345) is True

    def test_tasklist_probe_error_is_alive(self, monkeypatch) -> None:
        """Any tasklist probe error (timeout / OSError) -> conservative alive."""
        import shutil
        import subprocess

        mod = load_runner_module()
        self._force_windows_tasklist_branch(monkeypatch, shutil)

        def _timeout(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(subprocess, "run", _timeout)
        assert mod.is_pid_running(12345) is True

    def test_acquire_lock_problematic_pid_reports_active_not_crash(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """acquire_lock with a lock whose PID triggers the Windows-problematic
        SystemError must raise RuntimeError (lock activo), not crash.

        End-to-end: acquire_lock -> is_pid_running(lock_pid) -> SystemError is
        swallowed conservatively (alive) -> stale=False -> RuntimeError.
        """
        import json as _json
        import os
        import shutil

        mod = load_runner_module()
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        lock_file = runtime / "pytest.lock"
        monkeypatch.setattr(mod, "RUNTIME_DIR", runtime)
        monkeypatch.setattr(mod, "LOCK_FILE", lock_file)
        lock_file.write_text(
            _json.dumps(
                {
                    "pid": 12345,
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "cwd": str(tmp_path),
                }
            ),
            encoding="utf-8",
        )
        # Force the os.kill fallback to raise SystemError (the Windows bug).
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)

        def _boom(pid: int, sig: int) -> None:
            raise SystemError("windows foreign live pid probe")

        monkeypatch.setattr(os, "kill", _boom)
        with pytest.raises(RuntimeError):
            mod.acquire_lock(force_unlock=False)


class TestSuiteRegressionReportWiring:
    """WOT-2026-031a: the suite performance regression REPORT is wired post-suite.

    The reporter (scripts/suite_regression_report.py, WOT-2026-022q) existed and
    was tested but nobody invoked it. These tests prove: (1) main() actually
    invokes it after append_run_history, and (2) it is STRICTLY INFORMATIVE --
    a reporter that BLOWS UP must NEVER change main()'s exit_code.
    """

    def _run_main(
        self, mod, tmp_path: Path, monkeypatch, stream_return: tuple
    ) -> tuple[int, str]:
        """Run main() in a tmp-isolated env; return (exit_code, captured stdout)."""
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        base = tmp_path / ".agent" / "runtime" / "pytest-safe"
        base.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", base / "last-run.json")
        monkeypatch.setattr(mod, "LAST_RUN_LOG", base / "last-run.log")
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", base / "run_history.jsonl")

        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: stream_return)
        monkeypatch.setattr(mod, "_delivery_head_sha", lambda: "abc123")
        lock_obj = {
            "pid": 0,
            "started_at": "2026-01-01T00:00:00+00:00",
            "cwd": str(tmp_path),
        }
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: lock_obj)
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mod.main()
        return code, buf.getvalue()

    def test_reporter_is_invoked_post_suite(self, tmp_path: Path, monkeypatch) -> None:
        """main() prints an [suite-regression] line -> the reporter IS wired.

        Without the WOT-2026-031a wiring, nothing invokes the reporter and the
        '[suite-regression]' marker never appears in main()'s stdout.
        """
        mod = load_runner_module()
        code, out = self._run_main(
            mod, tmp_path, monkeypatch, stream_return=(0, [], [])
        )
        assert code == 0
        assert "[suite-regression]" in out, (
            "main() must invoke suite_regression_report post-suite "
            "(no '[suite-regression]' marker -> reporter not wired)"
        )

    def test_reporter_exception_does_not_change_exit_code(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """MUTATION WITH TEETH: if the reporter RAISES, exit_code is unchanged.

        This isolates the 'never affects rc' invariant: we monkeypatch the
        reporter's analyze() to raise, and assert main() still returns the
        pytest exit_code (0). If the wiring were NOT fail-open (e.g. the call
        sat outside a try/except, or propagated the exception), main() would
        crash or return a non-zero code -- this test would then fail.
        """
        mod = load_runner_module()

        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import suite_regression_report as srr

        def _boom(*a, **k):
            raise RuntimeError("reporter blew up mid-analysis")

        monkeypatch.setattr(srr, "analyze", _boom)

        code, _out = self._run_main(
            mod, tmp_path, monkeypatch, stream_return=(0, [], [])
        )
        assert code == 0, (
            "a reporter that raises must NOT change main()'s exit_code: "
            "the post-suite report is strictly informative and fail-open"
        )

    def test_reporter_nonzero_would_not_break_rc_on_red_suite(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """On a RED suite, exit_code stays the pytest code, unaffected by the report.

        The reporter never returns rc to main() (main ignores its return), but
        this guards the pairing: a failing pytest run keeps its own exit_code 1
        with the reporter wired in, and the report does not mask/alter it.
        """
        mod = load_runner_module()
        failing = ["tests/foo/test_bar.py::test_x"]
        code, out = self._run_main(
            mod, tmp_path, monkeypatch, stream_return=(1, failing, [])
        )
        assert code == 1, "red suite must keep exit_code 1 with the reporter wired"
        assert "[suite-regression]" in out


class TestStampSurvivesMutatingHooks:
    """WOT-2026-040n: the stamp is re-resolved when the measurement window
    CLOSES, and that re-stamp is strictly conditioned on the 040t invariant.

    The point of this class is the ASYMMETRY, because without it the fix reads
    like a bypass of WOT-2026-040t:

      * tree only REFORMATTED by the mutating pre-commit hooks (after the
        window) -> the run stays valid and the stamp follows the delivery HEAD,
        so pre_handoff_guard stops firing `stale_run` on legitimate work.
      * tree MOVED DURING the suite (stash/reset/checkout) -> 040t invalidates
        the run and the stamp must NOT be refreshed; re-stamping there would
        launder exactly the contaminated run 040t exists to catch.
      * window NOT VERIFIABLE (no pre-snapshot) -> also no re-stamp: absence of
        a violation is not proof of stability.

    [NON-REVERSE-CLASSICAL: fija la asimetria de un reordenamiento; el rojo
    previo lo da el probe de DoD del vuelo, no un bug con node-id.]
    """

    def _run_main(
        self,
        mod,
        tmp_path: Path,
        monkeypatch,
        *,
        head_seq: list[str],
        invariant_raises: BaseException | None = None,
        capture_raises: BaseException | None = None,
        post_status: str = "",
        stream_pytest_override=None,
    ) -> dict:
        """Drive main() with a delivery HEAD that CHANGES between the run-start
        stamp and the window close (that is what the mutating hooks do).

        ``head_seq`` is consumed one value per _delivery_head_sha() call, so the
        first call (run start) and the last (re-stamp) can differ.
        """
        base = tmp_path / ".agent" / "runtime" / "pytest-safe"
        base.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT_BOOTSTRAP", tmp_path)
        monkeypatch.setattr(mod, "LAST_RUN_JSON", base / "last-run.json")
        monkeypatch.setattr(mod, "LAST_RUN_LOG", base / "last-run.log")
        monkeypatch.setattr(mod, "RUN_HISTORY_JSONL", base / "run_history.jsonl")

        pending = list(head_seq)

        def _fake_head() -> str:
            return pending.pop(0) if len(pending) > 1 else pending[0]

        monkeypatch.setattr(mod, "_delivery_head_sha", _fake_head)

        if capture_raises is not None:

            def _raise_capture(_root):
                raise capture_raises

            monkeypatch.setattr(mod, "_invariant_capture_state", _raise_capture)
        else:
            # A REAL WorktreeState: main() reads .head/.status/.head_reflog_len
            # to build audit_state_pre. A bare object() would raise there and
            # silently route this harness down the "unverifiable window" path --
            # i.e. the stable-window test would pass for the wrong reason.
            from scripts.worktree_audit_invariant import WorktreeState

            # First call = pre-snapshot (clean). Later calls = the post-window
            # capture the re-stamp makes, which may report a DIRTY tree.
            _captures = {"n": 0}

            def _capture(_root):
                _captures["n"] += 1
                status = post_status if _captures["n"] > 1 else ""
                return WorktreeState(head="h", status=status, head_reflog_len=1)

            monkeypatch.setattr(mod, "_invariant_capture_state", _capture)

        def _verify(_root, _pre):
            if invariant_raises is not None:
                raise invariant_raises
            return None

        monkeypatch.setattr(mod, "_invariant_verify_unchanged", _verify)

        monkeypatch.setattr(
            mod,
            "stream_pytest",
            stream_pytest_override or (lambda cmd: (0, [], [])),
        )
        monkeypatch.setattr(mod, "acquire_lock", lambda force_unlock=False: {"pid": 0})
        monkeypatch.setattr(mod, "release_lock", lambda: None)
        monkeypatch.setattr(
            mod, "cleanup_known_temp_dirs", lambda: {"removed": [], "failed": []}
        )
        monkeypatch.setattr(mod, "check_canonical_state_leak", lambda snap: [])
        monkeypatch.setattr(mod, "snapshot_canonical_state", lambda: {})
        monkeypatch.setattr(
            mod,
            "select_test_runner",
            lambda interp, args, xdist, run_dir, test_dir: (["echo"], "pytest"),
        )
        monkeypatch.setattr(mod, "resolve_test_interpreter", lambda: sys.executable)
        monkeypatch.setattr(sys, "argv", ["run_pytest_safe.py", "--level", "all"])

        mod.main()
        return json.loads((base / "last-run.json").read_text(encoding="utf-8"))

    def test_stamp_follows_head_when_only_hooks_rewrote_the_tree(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The defect being closed: hooks rewrite the tree AFTER the window, so
        the commit lands on a new HEAD. The stamp must describe the tree that
        was actually measured, not the pre-hook HEAD.

        Mutation: delete the re-stamp block in main() and this goes RED
        (tested_commit_sha stays at the run-start value 'pre_hooks').
        """
        mod = load_runner_module()
        data = self._run_main(
            mod, tmp_path, monkeypatch, head_seq=["pre_hooks", "post_hooks"]
        )
        assert data.get("audit_window_invalidated") is None
        assert data["tested_commit_sha"] == "post_hooks", (
            "with a stable measurement window the stamp must be re-resolved at "
            "window close, so the handoff gate stops seeing a false stale_run"
        )

    def test_stamp_is_not_refreshed_when_tree_moved_during_the_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The other half of the asymmetry -- this is what keeps the fix from
        being a bypass of WOT-2026-040t.

        Mutation: drop the `audit_window_invalidated` condition from the
        re-stamp guard and this goes RED, because a contaminated run would then
        get a stamp matching the delivery HEAD and look handoff-ready.
        """
        mod = load_runner_module()
        violation = mod._AuditInvariantViolation("MEDICION INVALIDADA: test")
        data = self._run_main(
            mod,
            tmp_path,
            monkeypatch,
            head_seq=["pre_hooks", "post_hooks"],
            invariant_raises=violation,
        )
        assert data.get("audit_window_invalidated"), "040t must invalidate this run"
        assert data["tested_commit_sha"] == "pre_hooks", (
            "a run whose tree moved DURING the suite must NOT be re-stamped: "
            "that would launder the contaminated run 040t exists to catch"
        )
        assert data["exit_code"] == 1, "an invalidated window must not stay green"

    def test_crash_persists_a_stamp_marked_provisional(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-040n review A-1 (negative case). The re-stamp lives inside
        the `try`; a crash jumps to the `finally`, which persists the summary
        with the RUN-START sha. That stale stamp must not be indistinguishable
        from a validated one.

        Mutation: delete the "provisional_at_run_start" stamp_scope seed and
        this goes RED -- last-run.json would carry a stale SHA with no field
        saying so.
        """
        mod = load_runner_module()
        base = tmp_path / ".agent" / "runtime" / "pytest-safe"
        base.mkdir(parents=True, exist_ok=True)

        def _boom(_cmd):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            self._run_main(
                mod,
                tmp_path,
                monkeypatch,
                head_seq=["pre_hooks", "post_hooks"],
                stream_pytest_override=_boom,
            )

        data = json.loads((base / "last-run.json").read_text(encoding="utf-8"))
        assert data["tested_commit_sha"] == "pre_hooks", (
            "the finally persists the run-start sha after a crash"
        )
        assert data["stamp_scope"] == "provisional_at_run_start", (
            "a stamp persisted by the crash path must declare itself "
            "provisional; otherwise it reads as validated"
        )

    def test_revalidated_stamp_records_tree_dirtiness(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WOT-2026-040n review A-2. A re-stamp over a DIRTY tree still names a
        commit the working tree does not match, so the stamp must say so.

        Mutation: drop the stamp_tree_dirty capture and this goes RED.
        """
        mod = load_runner_module()
        data = self._run_main(
            mod,
            tmp_path,
            monkeypatch,
            head_seq=["pre_hooks", "post_hooks"],
            post_status=" M scripts/run_pytest_safe.py\n",
        )
        assert data["tested_commit_sha"] == "post_hooks"
        assert data["stamp_scope"] == "revalidated_at_window_close"
        assert data["stamp_tree_dirty"] is True, (
            "a re-stamp over a dirty tree must record that the tree does not "
            "match the commit it names"
        )
        assert data["stamp_status_entries"] == 1

    def test_stamp_is_not_refreshed_when_window_is_unverifiable(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """No pre-snapshot => the window is 'not verified', never 'verified
        stable'. Absence of a violation is not proof of stability.

        Mutation: weaken the guard to `not summary.get(...)` alone (dropping the
        `_audit_state_pre is not None` requirement) and this goes RED.
        """
        mod = load_runner_module()
        data = self._run_main(
            mod,
            tmp_path,
            monkeypatch,
            head_seq=["pre_hooks", "post_hooks"],
            capture_raises=RuntimeError("git unavailable"),
        )
        assert data["tested_commit_sha"] == "pre_hooks", (
            "an unverifiable window must not be re-stamped: that would assert a "
            "stability nobody measured"
        )


# ---------------- WOT-2026-055j: exit 5 (no tests collected) no acredita ---------
def test_exit_5_marks_last_run_as_no_tests_collected():
    """WOT-2026-055j (b): `exit_code: 5` (pytest: ningun test recolectado) deja el
    status en `no-tests-collected`, NO en `finished`, y anade la marca explicita.

    Medido 2026-08-12: un last-run.json del DESTINO con exit_code 5 y 1 segundo de
    duracion acreditaba `status: finished` para cualquier lector -- indistinguible
    de una corrida legitima -- y una lente con repo_root=destino emitio un BLOCKER
    falso. Sin esta marca, el artefacto miente sobre si midio algo.

    MUTACION QUE LA MATA: revertir la rama `exit_code == 5` -> este test cae.
    """
    rps = load_runner_module()
    summary = {"status": "finished", "exit_code": 5}
    rps._mark_no_tests_collected(5, summary)

    assert summary["status"] == "no-tests-collected", summary
    assert summary["no_tests_collected"] is True, summary
    assert summary["exit_code"] == 5, "conserva el 5: ningun gate verde lo acepta"


def test_non_zero_non_five_status_unchanged_by_marker():
    """WOT-2026-055j (d) CONTROL NEGATIVO: los demas exit codes no se tocan; una
    corrida legitima (exit 0) queda `finished` sin marca de no-acreditacion."""
    rps = load_runner_module()
    for code in (0, 1, 2):
        summary = {"status": "finished", "exit_code": code}
        rps._mark_no_tests_collected(code, summary)
        assert summary["status"] == "finished", f"exit {code}"
        assert "no_tests_collected" not in summary, f"exit {code}"
