from unittest.mock import patch

import pytest
from scripts.local_audit import (
    fix_mojibake,
    get_active_state,
    get_backends,
    get_recent_wps,
    get_skills,
    get_versions,
)


@pytest.fixture
def mock_project_root(tmp_path):
    project_root = tmp_path / "project_root"
    project_root.mkdir()

    agent_dir = project_root / ".agent"
    agent_dir.mkdir()

    collab_dir = agent_dir / "collaboration"
    collab_dir.mkdir()

    config_dir = agent_dir / "config"
    config_dir.mkdir()

    skills_dir = project_root / "skills"
    skills_dir.mkdir()

    return project_root


def test_get_versions(mock_project_root):
    (mock_project_root / "PROJECT.md").write_text(
        "- Version: `v1.2.3`\n", encoding="utf-8"
    )
    (mock_project_root / "pyproject.toml").write_text(
        'version = "2.0.0"\n', encoding="utf-8"
    )
    (mock_project_root / ".agent" / ".version_manifest.json").write_text(
        '{"agent_core_version": "3.0.0"}', encoding="utf-8"
    )

    with (
        patch("scripts.local_audit.PROJECT_ROOT", mock_project_root),
        patch("scripts.local_audit.AGENT_DIR", mock_project_root / ".agent"),
    ):
        versions = get_versions()

    assert versions["project_md"] == "v1.2.3"  # backticks stripped at parse time
    assert versions["pyproject"] == "2.0.0"
    assert versions["manifest"] == "3.0.0"


def test_get_active_state(mock_project_root):
    collab_dir = mock_project_root / ".agent" / "collaboration"
    state_file = collab_dir / "STATE.md"

    # Test fallback to work_plan.md when STATE.md doesn't exist
    work_plan = collab_dir / "work_plan.md"
    work_plan_content = """
## WP-2026-081: Some Plan
- **ID:** ** WP-2026-081 **
- **Estado:** ** COMPLETED **
"""
    work_plan.write_text(work_plan_content, encoding="utf-8")
    with patch("scripts.local_audit.COLLAB_DIR", collab_dir):
        state = get_active_state()

    assert state["plan"] == "WP-2026-081"
    assert state["status"] == "COMPLETED"

    # Test fallback to work_plan.md with multiple WPs parses the latest one (bottom-up)
    work_plan_multi = """
## WP-2026-081: Some Old Plan
- **ID:** ** WP-2026-081 **
- **Estado:** ** COMPLETED **

## WP-2026-082: Newest Active Plan
- **ID:** ** WP-2026-082 **
- **Estado:** ** IN_PROGRESS **
"""
    work_plan.write_text(work_plan_multi, encoding="utf-8")
    with patch("scripts.local_audit.COLLAB_DIR", collab_dir):
        state = get_active_state()
    assert state["plan"] == "WP-2026-082"
    assert state["status"] == "IN_PROGRESS"

    # Test STATE.md takes priority when it exists
    state_file.write_text(
        "- **Plan Activo:** ** WP-999 **\n- **Estado actual:** ** IN_PROGRESS **\n",
        encoding="utf-8",
    )
    with patch("scripts.local_audit.COLLAB_DIR", collab_dir):
        state = get_active_state()

    assert state["plan"] == "WP-999"
    assert state["status"] == "IN_PROGRESS"


def test_check_version_drift():
    from scripts.local_audit import check_version_drift

    # Drift detected
    versions_drift = {
        "project_md": "`v9.11.0`",
        "pyproject": "9.11.0",
        "manifest": "v9.9.0",
    }
    drift, cleaned = check_version_drift(versions_drift)
    assert drift is True
    assert cleaned["project_md"] == "9.11.0"
    assert cleaned["manifest"] == "9.9.0"

    # No drift
    versions_nodrift = {
        "project_md": "`v9.11.0`",
        "pyproject": "9.11.0",
        "manifest": "v9.11.0",
    }
    drift, cleaned = check_version_drift(versions_nodrift)
    assert drift is False


def test_fix_mojibake():
    # Test decoding standard double-encoded UTF-8 strings
    assert fix_mojibake("AuditorÃ­a") == "Auditoría"
    assert fix_mojibake("cÃ³digo") == "código"
    assert fix_mojibake("â†’") == "→"  # noqa: RUF001
    assert fix_mojibake("Normal string") == "Normal string"
    assert fix_mojibake("Test\ufffdString") == "Test?String"


def test_get_skills_parsing(mock_project_root):
    skill_dir = mock_project_root / "skills" / "test-skill"
    skill_dir.mkdir()

    skill_md = skill_dir / "SKILL.md"
    skill_content = """---
name: Test Skill
version: 1.0
triggers: [/test]
---
# Test Skill
This is a test skill.
| Table | Row |
|---|---|
"""
    skill_md.write_text(skill_content, encoding="utf-8-sig")

    with patch("scripts.local_audit.PROJECT_ROOT", mock_project_root):
        skills = get_skills()

    assert len(skills) == 1
    assert skills[0]["name"] == "Test Skill"
    assert skills[0]["triggers"] == ["/test"]
    assert "Table" not in skills[0]


def test_get_backends(mock_project_root):
    agents_json = mock_project_root / ".agent" / "config" / "agents.json"
    agents_json.write_text(
        '{"role_assignments": {"BUILDER": "test"}}', encoding="utf-8"
    )

    with patch("scripts.local_audit.AGENT_DIR", mock_project_root / ".agent"):
        backends = get_backends()

    assert backends["role_assignments"]["BUILDER"] == "test"


def test_get_recent_wps(mock_project_root):
    exec_log = mock_project_root / ".agent" / "collaboration" / "execution_log.md"
    exec_log.write_text(
        "### WP-001\n### WP-002\nsome text\n### WP-003", encoding="utf-8"
    )

    with patch(
        "scripts.local_audit.COLLAB_DIR", mock_project_root / ".agent" / "collaboration"
    ):
        wps = get_recent_wps()

    assert len(wps) == 3
    assert wps[0] == "WP-001"
    assert wps[1] == "WP-002"
    assert wps[2] == "WP-003"
