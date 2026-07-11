"""Tests for the safe pytest runner argument contract."""

from __future__ import annotations

import importlib.util
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


def load_runner_module():
    spec = importlib.util.spec_from_file_location("run_pytest_safe", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
