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
