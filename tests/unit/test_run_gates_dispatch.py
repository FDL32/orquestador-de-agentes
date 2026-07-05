from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import scripts.pip_audit_policy as pip_audit_policy


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location(
    "run_gates_dispatch",
    PROJECT_ROOT / "scripts" / "run_gates_dispatch.py",
)
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


def test_read_deliverable_type_present(tmp_path, monkeypatch):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("- **deliverable_type:** documentation\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "documentation"


def test_read_deliverable_type_missing_fallback(tmp_path, monkeypatch, capsys):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("# Plan without type\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "code"
    err = capsys.readouterr().err
    assert "no deliverable_type" in err


def test_read_deliverable_type_compound_treated_as_mixed(tmp_path, monkeypatch):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text(
        "- **deliverable_type:** code+documentation\n", encoding="utf-8"
    )
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "mixed"


def test_read_deliverable_type_unknown_fallback(tmp_path, monkeypatch, capsys):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("- **deliverable_type:** nonsense\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_deliverable_type() == "code"
    err = capsys.readouterr().err
    assert "unknown type" in err


def test_read_delivery_authority_from_work_plan(tmp_path, monkeypatch):
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("- **delivery_authority:** repo_destino\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "WORK_PLAN", fake_plan)
    assert dispatch.read_delivery_authority() == "repo_destino"


def test_run_code_gates_uses_project_pip_audit_wrapper():
    """The dispatcher must share the same dependency-audit surface as pre-commit."""
    source = (PROJECT_ROOT / "scripts" / "run_gates_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "pip_audit_project.py" in source
    assert '"uv", "run", "pip-audit", "."' not in source
    assert "uv run pip-audit ." not in source


# WOT-2026-003e: has_local_tests — destino without a local suite must not fail gates


def test_has_local_tests_false_when_no_tests_dir(tmp_path):
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_false_when_tests_dir_empty(tmp_path):
    (tmp_path / "tests").mkdir()
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_false_when_tests_dir_has_no_test_files(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "helper.py").write_text("x = 1\n", encoding="utf-8")
    (tests / "conftest.py").write_text("", encoding="utf-8")
    assert dispatch.has_local_tests(tmp_path) is False


def test_has_local_tests_true_with_test_prefix(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_thing.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    assert dispatch.has_local_tests(tmp_path) is True


def test_has_local_tests_true_with_test_suffix_nested(tmp_path):
    nested = tmp_path / "tests" / "unit"
    nested.mkdir(parents=True)
    (nested / "thing_test.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    assert dispatch.has_local_tests(tmp_path) is True


# WOT-2026-008d: the dispatcher must run the naming gate as a barrier.


def test_dispatch_wires_check_naming_barrier():
    """Source-level: run_gates_dispatch invokes discover_skills --check-naming."""
    source = (PROJECT_ROOT / "scripts" / "run_gates_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "--check-naming" in source
    assert "discover_skills.py" in source


def test_dispatch_propagates_naming_failure(monkeypatch):
    """Behavioral: a failing --check-naming makes main() return non-zero.

    main() runs code/deliverable gates then the contract + naming barriers via
    subprocess. We stub everything green except --check-naming, which fails, and
    assert the failure propagates (fail-closed barrier).
    """
    calls: list[list[str]] = []

    class _FakeCompleted:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        # Fail only the naming check; everything else is green.
        if "--check-naming" in cmd:
            return _FakeCompleted(1)
        return _FakeCompleted(0)

    monkeypatch.setattr(dispatch, "read_deliverable_type", lambda: "documentation")
    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)

    rc = dispatch.main()

    assert rc == 1
    # The naming barrier was actually invoked.
    assert any("--check-naming" in c for c in calls)
    # And it ran after the contract barrier (order preserved).
    contract_idx = next(i for i, c in enumerate(calls) if "--check-contract" in c)
    naming_idx = next(i for i, c in enumerate(calls) if "--check-naming" in c)
    assert naming_idx > contract_idx


def test_run_code_gates_repo_motor_uses_motor_root_and_absolute_pytest(
    monkeypatch, tmp_path
):
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    (motor / "tests").mkdir(parents=True)
    destino.mkdir()

    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    class _FakeCompleted:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, Path(kwargs["cwd"]), kwargs.get("env")))
        return _FakeCompleted(0)

    monkeypatch.setattr(dispatch, "PROJECT_ROOT", destino)
    monkeypatch.setattr(dispatch, "MOTOR_ROOT", motor)
    monkeypatch.setattr(dispatch, "MOTOR_SCRIPTS_DIR", motor / "scripts")
    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)
    monkeypatch.setattr(dispatch, "has_local_tests", lambda root: root == motor)
    monkeypatch.setattr(
        pip_audit_policy,
        "should_run_pip_audit",
        lambda project_root: (False, "skip"),
    )

    rc = dispatch.run_code_gates("repo_motor")

    assert rc == 0
    assert calls[0][0][:4] == [dispatch.sys.executable, "-m", "ruff", "check"]
    assert calls[0][1] == motor
    pytest_cmd, pytest_cwd, pytest_env = calls[2]
    assert pytest_cmd == [
        dispatch.sys.executable,
        str(motor / "scripts" / "run_pytest_safe.py"),
    ]
    assert pytest_cwd == motor
    assert pytest_env is not None
    assert pytest_env["AGENT_PROJECT_ROOT"] == str(motor)


def test_run_deliverable_gates_uses_motor_script_and_destino_root(
    monkeypatch, tmp_path
):
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    motor.mkdir()
    destino.mkdir()

    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    class _FakeCompleted:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, Path(kwargs["cwd"]), kwargs.get("env")))
        return _FakeCompleted(0)

    monkeypatch.setattr(dispatch, "PROJECT_ROOT", destino)
    monkeypatch.setattr(dispatch, "MOTOR_ROOT", motor)
    monkeypatch.setattr(dispatch, "MOTOR_SCRIPTS_DIR", motor / "scripts")
    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)

    rc = dispatch.run_deliverable_gates()

    assert rc == 0
    cmd, cwd, env = calls[0]
    assert cmd == [
        dispatch.sys.executable,
        str(motor / "scripts" / "check_deliverables_exist.py"),
    ]
    assert cwd == motor
    assert env is not None
    assert env["AGENT_PROJECT_ROOT"] == str(destino)


def test_main_runs_barriers_from_motor_with_destino_project_root(monkeypatch, tmp_path):
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    motor.mkdir()
    destino.mkdir()

    calls: list[list[str]] = []

    class _FakeCompleted:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(0)

    monkeypatch.setattr(dispatch, "PROJECT_ROOT", destino)
    monkeypatch.setattr(dispatch, "MOTOR_ROOT", motor)
    monkeypatch.setattr(dispatch, "MOTOR_SCRIPTS_DIR", motor / "scripts")
    monkeypatch.setattr(dispatch, "read_deliverable_type", lambda: "documentation")
    monkeypatch.setattr(dispatch, "read_delivery_authority", lambda: "repo_motor")
    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)

    rc = dispatch.main()

    assert rc == 0
    assert calls == [
        [
            dispatch.sys.executable,
            str(motor / "scripts" / "check_deliverables_exist.py"),
        ],
        [
            dispatch.sys.executable,
            str(motor / "scripts" / "discover_skills.py"),
            "--check-contract",
        ],
        [
            dispatch.sys.executable,
            str(motor / "scripts" / "discover_skills.py"),
            "--check-naming",
        ],
        [
            dispatch.sys.executable,
            str(motor / "scripts" / "check_backlog_contract.py"),
            "--project-root",
            str(destino),
        ],
    ]


# WOT-2026-014e: mutation barrier — resolve_motor_root_path delegates to canonical helper


def test_resolve_motor_root_path_delegates_to_canonical_helper(tmp_path, monkeypatch):
    """Barrier: resolve_motor_root_path must call runtime.motor_link.resolve_motor_root.

    Mutation barrier: if the function were reverted to reopen motor_destination_link.json
    locally (without delegating), patching runtime.motor_link.resolve_motor_root would
    have no effect and the assertion on the sentinel value would FAIL.
    """
    from unittest.mock import patch as _patch

    sentinel = tmp_path / "sentinel_motor"
    sentinel.mkdir()

    with _patch(
        "runtime.motor_link.resolve_motor_root", return_value=sentinel.resolve()
    ) as mock_resolve:
        result = dispatch.resolve_motor_root_path(tmp_path)

    mock_resolve.assert_called_once_with(tmp_path)
    assert result == sentinel.resolve()


def test_resolve_motor_root_path_returns_resolved_path(tmp_path):
    """Barrier: the returned path must be .resolve()-normalised.

    WOT-2026-014j: hardened from false-green. Previous version used str(tmp_path/motor)
    which is already canonical on Windows/NTFS, so Path(x)==Path(x).resolve() passed both
    with and without the .resolve() in motor_link.py:43.

    Fix: build a non-canonical raw_path with a ".." segment (tmp_path/motor/sub/..).
    Path(raw_path) != Path(raw_path).resolve() because resolve() collapses the dotdot.
    Without .resolve() in the production code, the returned path would retain the ".."
    segment and result != raw_path.resolve() would FAIL.

    Mutation-verified: removing .resolve() from runtime/motor_link.py:43 makes this test
    FAIL (via the resolve_motor_root_path wrapper that delegates to resolve_motor_root).
    """
    # Create motor/sub so the dotdot path is traversable
    sub = tmp_path / "motor" / "sub"
    sub.mkdir(parents=True)

    # Build a non-canonical path: tmp_path/motor/sub/.. (dotdot not collapsed)
    raw_path = Path(str(tmp_path / "motor" / "sub" / ".."))

    # Pre-condition: raw_path must differ from its resolved form (barrera real)
    assert raw_path != raw_path.resolve(), (
        "WOT-2026-014j precondition: raw path must NOT be canonical "
        "(dotdot segment must differ from resolved form) for the test to exercise .resolve()"
    )

    project = tmp_path / "project"
    (project / ".agent" / "config").mkdir(parents=True)
    link = project / ".agent" / "config" / "motor_destination_link.json"
    # Write the non-canonical path string into the link JSON
    link.write_text(json.dumps({"motor_root": str(raw_path)}), encoding="utf-8")

    result = dispatch.resolve_motor_root_path(project)

    # Must equal the canonical (resolved) form
    assert result == raw_path.resolve()
    # Must NOT be the raw non-canonical path (if .resolve() is absent, this FAILS)
    assert result != raw_path, (
        "resolve_motor_root_path must call .resolve() via motor_link: "
        "returned the raw non-canonical path"
    )


# WOT-2026-019i: regression barrier — .agent must never shadow the top-level
# runtime package at module level.


def test_run_gates_dispatch_importable_without_module_shadowing():
    """Regression: running the script must not shadow runtime.motor_link.

    Before the fix, run_gates_dispatch.py inserted `.agent` into sys.path at
    module level (before importing runtime.motor_link inside
    resolve_motor_root_path), which made `import runtime` resolve to the
    `.agent/runtime/` package (only __init__.py, no motor_link.py) instead of
    `<motor>/runtime/`, raising ModuleNotFoundError at import time.

    The module under test (`dispatch`, imported above via importlib.util) is
    already loaded in this pytest process, so re-importing it here would not
    re-exercise the module-level import failure. This test invokes the script
    as an independent subprocess instead, using sys.executable so it runs
    under the same interpreter as the pytest process itself.
    """
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_gates_dispatch.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert "ModuleNotFoundError" not in result.stderr
    assert "No module named 'runtime.motor_link'" not in result.stderr
