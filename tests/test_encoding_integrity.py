"""Tests to ensure no mojibake exists in operational files."""

from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
AGENT_DIR = ROOT / ".agent"

# Broad mojibake markers from UTF-8 text interpreted as Latin-1/Win-1252.
MOJIBAKE_MARKERS = [
    "\u00c3",
    "\u00c2",
    "\u00e2\u0080",
    "\u00e2\u009d",
    "\u00f0\u009f",
    "\u0102",
]

FILES_TO_CHECK = [
    AGENT_DIR / "README.md",
    AGENT_DIR / "hooks" / "stop_hook.py",
    AGENT_DIR / "completion_common.py",
    AGENT_DIR / "collaboration" / "work_plan.md",
    AGENT_DIR / "collaboration" / "execution_log.md",
    AGENT_DIR / "collaboration" / "notifications.md",
    AGENT_DIR / "collaboration" / "TURN.md",
    AGENT_DIR / "workflows" / "manager_workflow.md",
    AGENT_DIR / "workflows" / "builder_workflow.md",
    ROOT / "skills" / "bui-run-quality-gates" / "SKILL.md",
    ROOT / "skills" / "bui-implement-from-plan" / "SKILL.md",
    ROOT / "skills" / "bui-self-audit" / "SKILL.md",
    ROOT / "skills" / "man-review-implementation" / "SKILL.md",
    ROOT / "skills" / "bui-run-quality-gates" / "references" / "common-fixes.md",
    ROOT / "skills" / "bui-implement-from-plan" / "references" / "log-format.md",
    AGENT_DIR / "templates" / "LEGACY_NOTE.md",
    AGENT_DIR / "templates" / "work_plan_template.md",
    AGENT_DIR / "templates" / "findings_template.md",
    AGENT_DIR / "templates" / "PRIVATE_REGISTRY.md",
    AGENT_DIR / "templates" / "work_plan_example_v2.md",
    AGENT_DIR / "legacy" / "LEGACY_NOTE.md",
    AGENT_DIR / "legacy" / "manager_workflow.md",
    AGENT_DIR / "legacy" / "builder_workflow.md",
    AGENT_DIR / "legacy" / "MANAGER_SKILLS.md",
    AGENT_DIR / "legacy" / "BUILDER_SKILLS.md",
    AGENT_DIR / "legacy" / "MANAGER_CONTEXT.md",
    AGENT_DIR / "legacy" / "BUILDER_CONTEXT.md",
]


@pytest.mark.parametrize("file_path", FILES_TO_CHECK)
def test_no_mojibake_in_file(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    content = file_path.read_text(encoding="utf-8")
    for marker in MOJIBAKE_MARKERS:
        assert marker not in content, (
            f"Mojibake marker {marker!r} detected in {file_path.name}"
        )
