"""Tests to ensure no mojibake exists in operational files."""

from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
AGENT_DIR = ROOT / ".agent"

SUSPICIOUS_CODEPOINTS = {
    0x00C3,
    0x00C2,
    0x00E2,
    0x00F0,
    0x0102,
    0xFFFD,
}

STATIC_FILES_TO_CHECK = [
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

GLOB_PATTERNS = [
    "skills/**/*.md",
    "prompts/**/*.md",
    "scripts/**/*.py",
    ".claude/**/*.md",
    "*.md",
]

KNOWN_DIRTY_GLOB_FILES = {
    "skills/_shared/ticket-anti-patterns.md",
    "skills/bui-implement-from-plan/references/code-rules.md",
    "skills/code-audit/references/audit-report-template.md",
    "skills/graphify/SKILL.md",
    "skills/man-review-implementation/references/review-checklist.md",
    "skills/man-review-implementation/references/verdict-format.md",
    "skills/setup-agent-system/SKILL.md",
    "skills/setup-agent-system/references/quickstart-checklist.md",
    "scripts/discover_skills.py",
    "scripts/migrate_legacy_project.py",
    "scripts/orquestador.py",
    "scripts/rollback.py",
    "scripts/run_pytest_safe.py",
    "scripts/sandbox/fix_rules_encoding.py",
    "scripts/test_goose_realworld.py",
    "scripts/upgrade.py",
    "scripts/upgrade_agent_system.py",
    "scripts/validate_agent_config.py",
    ".claude/agents/builder.md",
    ".claude/agents/manager.md",
    ".claude/commands/agent-build.md",
    ".claude/commands/agent-plan.md",
    ".claude/commands/agent-quick.md",
    ".claude/commands/agent-review.md",
    ".claude/commands/agent-status.md",
    ".claude/commands/pause-work.md",
    ".claude/commands/quality-gates.md",
    ".claude/commands/resume-work.md",
    ".claude/README.md",
    ".claude/rules/03-skills-discovery.md",
    ".claude/rules/06-project-manifest-architecture.md",
    "CHANGELOG.md",
}


def _find_mojibake_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) not in SUSPICIOUS_CODEPOINTS:
            continue
        snippet = text[idx : idx + 4]
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def _relative_path(file_path: Path) -> str:
    return file_path.relative_to(ROOT).as_posix()


def _collect_files_to_check() -> list[Path]:
    files = {path for path in STATIC_FILES_TO_CHECK}
    for pattern in GLOB_PATTERNS:
        files.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(files)


FILES_TO_CHECK = _collect_files_to_check()


@pytest.mark.parametrize(
    "file_path",
    FILES_TO_CHECK,
    ids=lambda path: path.relative_to(ROOT).as_posix(),
)
def test_no_mojibake_in_file(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    relative_path = _relative_path(file_path)
    if relative_path in KNOWN_DIRTY_GLOB_FILES:
        pytest.skip(f"Known dirty file pending cleanup: {relative_path}")

    content = file_path.read_text(encoding="utf-8")
    snippets = _find_mojibake_snippets(content)
    assert not snippets, f"Mojibake detected in {relative_path}: {snippets[:12]}"


@pytest.mark.parametrize("relative_path", sorted(KNOWN_DIRTY_GLOB_FILES))
def test_known_dirty_files_still_need_cleanup(relative_path):
    file_path = ROOT / relative_path
    assert file_path.exists(), f"Allowlisted file missing: {relative_path}"

    content = file_path.read_text(encoding="utf-8")
    snippets = _find_mojibake_snippets(content)
    assert snippets, (
        f"Allowlist entry is now clean and should be removed: {relative_path}"
    )
