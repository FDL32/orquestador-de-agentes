from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_deliverables_exist.py"


def _run_with_plan(plan_content: str, project_root: Path) -> tuple[int, str]:
    plan_dir = project_root / ".agent" / "collaboration"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "work_plan.md").write_text(plan_content, encoding="utf-8")

    env = os.environ.copy()
    env["TEST_PROJECT_ROOT"] = str(project_root)

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
