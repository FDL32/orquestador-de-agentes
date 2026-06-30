"""Tests for the safe pytest runner argument contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_pytest_safe.py"
SELECTION_PATH = PROJECT_ROOT / "scripts" / "test_selection.py"


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
        data = self._stub_main(mod, tmp_path, monkeypatch, stream_return=(0, []))
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
            mod, tmp_path, monkeypatch, stream_return=(1, failing_ids)
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
        monkeypatch.setattr(mod, "stream_pytest", lambda cmd: (0, []))
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
