"""Tests to ensure no mojibake exists in operational files."""

from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
AGENT_DIR = ROOT / ".agent"

SUSPICIOUS_CODEPOINTS = {
    0x00C3,  # ?
    0x00C2,  # ?
    0x00E2,  # ?
    0x00F0,  # ?
    0x0102,  # ?
    0xFFFD,  # replacement char
}

FILES_TO_CHECK = [
    ROOT / "prompts" / "memory_upload.md",
    ROOT / "prompts" / "session_bootstrap.md",
    AGENT_DIR / "agent_controller.py",
    AGENT_DIR / "completion_checker.py",
    ROOT / "scripts" / "update_project_map.py",
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


def _find_mojibake_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) not in SUSPICIOUS_CODEPOINTS:
            continue
        snippet = text[idx : idx + 4]
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


@pytest.mark.parametrize("file_path", FILES_TO_CHECK)
def test_no_mojibake_in_file(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    content = file_path.read_text(encoding="utf-8")
    snippets = _find_mojibake_snippets(content)
    assert not snippets, f"Mojibake detected in {file_path.name}: {snippets[:12]}"
