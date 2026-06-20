from __future__ import annotations

import importlib.util
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
