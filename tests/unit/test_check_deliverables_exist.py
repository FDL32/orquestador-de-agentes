from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_deliverables_exist.py"


def _run_with_plan(
    plan_content: str, project_root: Path, motor_root: Path | None = None
) -> tuple[int, str]:
    plan_dir = project_root / ".agent" / "collaboration"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "work_plan.md").write_text(plan_content, encoding="utf-8")

    env = os.environ.copy()
    env["TEST_PROJECT_ROOT"] = str(project_root)
    if motor_root is not None:
        env["TEST_MOTOR_ROOT"] = str(motor_root)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout + result.stderr


def test_all_declared_paths_exist(tmp_path):
    existing = tmp_path / "existing.txt"
    existing.write_text("ok", encoding="utf-8")
    plan = "## Deliverables\n- `existing.txt` something\n"
    code, _ = _run_with_plan(plan, tmp_path)
    assert code == 0


def test_missing_deliverable_detected(tmp_path):
    plan = "## Deliverables\n- `does_not_exist.md` description\n"
    code, output = _run_with_plan(plan, tmp_path)
    assert code == 1
    assert "does_not_exist.md" in output


def test_work_plan_without_deliverables_section(tmp_path):
    plan = "# Just metadata, no deliverables section\n"
    code, _ = _run_with_plan(plan, tmp_path)
    assert code == 0


def test_wot_010j_real_case_motor_deliverable_resolves_against_motor_root(tmp_path):
    """Regression: WOT-2026-010j blocked because a repo_motor FLT deliverable
    was resolved against --project-root (destino) instead of motor_root."""
    motor_root = tmp_path / "motor"
    destino_root = tmp_path / "destino"
    motor_root.mkdir()
    destino_root.mkdir()

    deliverable = motor_root / "docs" / "test_performance"
    deliverable.mkdir(parents=True)
    (deliverable / "test_performance_baseline_WOT-2026-010j.md").write_text(
        "report", encoding="utf-8"
    )

    plan = (
        "## Metadata\n"
        "- **delivery_authority:** repo_motor\n\n"
        "## Files Likely Touched\n\n"
        "### repo_motor\n"
        "- `docs/test_performance/test_performance_baseline_WOT-2026-010j.md`\n"
    )
    code, output = _run_with_plan(plan, destino_root, motor_root=motor_root)
    assert code == 0, output


def test_namespaced_repo_motor_deliverable_passes(tmp_path):
    motor_root = tmp_path / "motor"
    destino_root = tmp_path / "destino"
    motor_root.mkdir()
    destino_root.mkdir()
    (motor_root / "scripts").mkdir()
    (motor_root / "scripts" / "thing.py").write_text("x = 1\n", encoding="utf-8")

    plan = "## Files Likely Touched\n\n### repo_motor\n- `scripts/thing.py`\n"
    code, output = _run_with_plan(plan, destino_root, motor_root=motor_root)
    assert code == 0, output


def test_namespaced_repo_destino_deliverable_passes_no_regression(tmp_path):
    motor_root = tmp_path / "motor"
    destino_root = tmp_path / "destino"
    motor_root.mkdir()
    destino_root.mkdir()
    (destino_root / ".agent" / "collaboration").mkdir(parents=True)
    (destino_root / "execution_log.md").write_text("log", encoding="utf-8")

    plan = "## Files Likely Touched\n\n### repo_destino\n- `execution_log.md`\n"
    code, output = _run_with_plan(plan, destino_root, motor_root=motor_root)
    assert code == 0, output


def test_namespaced_repo_motor_missing_deliverable_fails_closed(tmp_path):
    motor_root = tmp_path / "motor"
    destino_root = tmp_path / "destino"
    motor_root.mkdir()
    destino_root.mkdir()

    plan = "## Files Likely Touched\n\n### repo_motor\n- `scripts/does_not_exist.py`\n"
    code, output = _run_with_plan(plan, destino_root, motor_root=motor_root)
    assert code == 1
    assert "does_not_exist.py" in output


def test_read_inspect_only_and_manager_only_not_treated_as_deliverables(tmp_path):
    destino_root = tmp_path / "destino"
    destino_root.mkdir()

    plan = (
        "## Files Likely Touched\n\n"
        "### repo_destino\n"
        "- `execution_log.md`\n\n"
        "## Read/inspect only\n\n"
        "- `does_not_exist_either.md`\n\n"
        "## Manager-only\n\n"
        "- `also_missing.md`\n"
    )
    (destino_root / ".agent" / "collaboration").mkdir(parents=True)
    (destino_root / "execution_log.md").write_text("log", encoding="utf-8")

    code, output = _run_with_plan(plan, destino_root, motor_root=destino_root)
    assert code == 0, output
