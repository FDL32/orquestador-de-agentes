from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.mark_destination_adopted import mark_adopted


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _install_fake_motor(
    motor: Path,
    project: Path,
    *,
    validate_payload: dict[str, object] | None = None,
    validate_exit: int = 0,
) -> None:
    payload = validate_payload or {"errors": {}, "warnings": {}}
    controller = (
        f"import json, sys\nprint(json.dumps({payload!r}))\nsys.exit({validate_exit})\n"
    )
    memory = f"print({str(project.resolve())!r})\n"
    _write(motor / ".agent/agent_controller.py", controller)
    _write(motor / "scripts/memory_context.py", memory)


def _valid_destination(project: Path, motor: Path) -> None:
    _write(
        project / ".agent/config/motor_destination_link.json",
        json.dumps(
            {
                "motor_root": str(motor.resolve()),
                "adopted": False,
                "contract_formation_required": True,
            }
        ),
    )
    _write(
        project / ".agent/config/agents.json",
        json.dumps({"active_profile": "host-project"}),
    )
    _write(project / "PROJECT.md", "Ticket prefix: TST\n")
    _init_git(project)


def test_mark_adopted_apply_writes_flag_after_all_gates_pass(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(motor, project)
    _valid_destination(project, motor)

    report = mark_adopted(project, motor, apply=True)

    assert report.ok is True
    assert report.applied is True
    data = json.loads(
        (project / ".agent/config/motor_destination_link.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["adopted"] is True
    assert data["adoption_verified_by"] == "scripts/mark_destination_adopted.py"
    assert data["contract_formation_required"] is True


def test_mark_adopted_dry_run_does_not_write(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(motor, project)
    _valid_destination(project, motor)

    report = mark_adopted(project, motor, apply=False)

    assert report.ok is True
    assert report.applied is False
    data = json.loads(
        (project / ".agent/config/motor_destination_link.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["adopted"] is False


def test_mark_adopted_blocks_tracked_sensitive_data(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(motor, project)
    _valid_destination(project, motor)
    _write(project / "data/real.xlsx", "not really excel\n")
    subprocess.run(
        ["git", "add", "data/real.xlsx"], cwd=project, check=True, capture_output=True
    )

    report = mark_adopted(project, motor, apply=True)

    assert report.ok is False
    assert report.applied is False
    assert "no_tracked_sensitive_or_data_files" in report.blockers
    data = json.loads(
        (project / ".agent/config/motor_destination_link.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["adopted"] is False


def test_mark_adopted_blocks_wrong_memory_root(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(motor, tmp_path / "other")
    _valid_destination(project, motor)

    report = mark_adopted(project, motor, apply=True)

    assert report.ok is False
    assert report.applied is False
    assert "memory_points_to_destination" in report.blockers


def test_mark_adopted_allows_tracked_env_example(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(motor, project)
    _valid_destination(project, motor)
    _write(project / ".env.example", "API_KEY=example\n")
    subprocess.run(
        ["git", "add", ".env.example"], cwd=project, check=True, capture_output=True
    )

    report = mark_adopted(project, motor, apply=True)

    assert report.ok is True
    assert report.applied is True


def test_mark_adopted_reports_validate_errors_when_command_fails(
    tmp_path: Path,
) -> None:
    motor = tmp_path / "motor"
    project = tmp_path / "project"
    project.mkdir()
    _install_fake_motor(
        motor,
        project,
        validate_payload={"errors": {"work_plan.md": ["bad"]}, "warnings": {}},
        validate_exit=1,
    )
    _valid_destination(project, motor)

    report = mark_adopted(project, motor, apply=True)

    assert report.ok is False
    assert report.applied is False
    validate_check = next(
        check for check in report.checks if check.name == "validate_zero_errors"
    )
    assert validate_check.evidence["errors_count"] == 1
