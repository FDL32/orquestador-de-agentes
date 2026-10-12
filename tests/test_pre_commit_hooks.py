"""
Tests for pre-commit hook configuration.

Ensures that volatile snapshots and local settings are excluded from
pre-commit/pre-push hooks to prevent automatic mutations during git push.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml


# Path to the pre-commit configuration file
PRE_COMMIT_CONFIG_PATH = Path(__file__).parent.parent / ".pre-commit-config.yaml"


@pytest.fixture
def pre_commit_config_content() -> str:
    """Load the pre-commit configuration content."""
    return PRE_COMMIT_CONFIG_PATH.read_text(encoding="utf-8")


class TestVolatileFilesExclusion:
    """Test that volatile/regenerable files are excluded from hooks."""

    def test_project_map_excluded_from_end_of_file_fixer(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify project_map.md is excluded from end-of-file-fixer hook."""
        # Find the end-of-file-fixer section
        pattern = r"- id: end-of-file-fixer.*?exclude: '(.+?)'"
        match = re.search(pattern, pre_commit_config_content, re.DOTALL)
        assert match is not None, "end-of-file-fixer hook not found"

        exclude_pattern = match.group(1)
        # Verify project_map.md is in the exclude pattern
        assert r"\.agent/context/project_map\.md" in exclude_pattern, (
            f"project_map.md should be excluded. Current pattern: {exclude_pattern}"
        )

    def test_project_map_excluded_from_mixed_line_ending(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify project_map.md is excluded from mixed-line-ending hook."""
        # Find the mixed-line-ending section
        pattern = r"- id: mixed-line-ending.*?exclude: '(.+?)'"
        match = re.search(pattern, pre_commit_config_content, re.DOTALL)
        assert match is not None, "mixed-line-ending hook not found"

        exclude_pattern = match.group(1)
        # Verify project_map.md is in the exclude pattern
        assert r"\.agent/context/project_map\.md" in exclude_pattern, (
            f"project_map.md should be excluded. Current pattern: {exclude_pattern}"
        )

    def test_claude_settings_excluded_from_mixed_line_ending(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify .claude/settings.json is excluded from mixed-line-ending hook."""
        # Find the mixed-line-ending section
        pattern = r"- id: mixed-line-ending.*?exclude: '(.+?)'"
        match = re.search(pattern, pre_commit_config_content, re.DOTALL)
        assert match is not None, "mixed-line-ending hook not found"

        exclude_pattern = match.group(1)
        # Verify .claude/settings.json is in the exclude pattern
        assert r"\.claude/settings\.json" in exclude_pattern, (
            f".claude/settings.json should be excluded. Current pattern: {exclude_pattern}"
        )


class TestHookConfigurationIntegrity:
    """Test that hook configurations maintain proper structure."""

    def test_pre_commit_config_exists(self) -> None:
        """Verify pre-commit configuration file exists."""
        assert PRE_COMMIT_CONFIG_PATH.exists(), "pre-commit config not found"

    def test_end_of_file_fixer_has_exclude(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify end-of-file-fixer has an exclude pattern."""
        pattern = r"- id: end-of-file-fixer.*?exclude: '(.+?)'"
        match = re.search(pattern, pre_commit_config_content, re.DOTALL)
        assert match is not None, "end-of-file-fixer must have an exclude pattern"

    def test_mixed_line_ending_has_exclude(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify mixed-line-ending has an exclude pattern."""
        pattern = r"- id: mixed-line-ending.*?exclude: '(.+?)'"
        match = re.search(pattern, pre_commit_config_content, re.DOTALL)
        assert match is not None, "mixed-line-ending must have an exclude pattern"

    def test_exclude_patterns_are_valid_regex(
        self, pre_commit_config_content: str
    ) -> None:
        """Verify exclude patterns are valid regular expressions."""
        pattern = r"exclude: '(.+?)'"
        matches = re.findall(pattern, pre_commit_config_content)

        for exclude_pattern in matches:
            try:
                re.compile(exclude_pattern)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern '{exclude_pattern}': {e}")


class TestDiscoverSkillsCheckWiring:
    """WOT-2026-094a: pin the discover_skills --check-contract/--check-naming
    hooks. Both checks existed but only ran via run_gates_dispatch.py when
    someone invoked the dispatcher; measured 2026-10-07, the three red tests
    of WOT-2026-093d/093e were first seen by the canonical suite ~3 h after
    the merge. This pin guarantees the hooks cannot silently disappear or be
    demoted to a stage that does not run on every commit.
    """

    def _hook_by_id(self, config_content: str, hook_id: str) -> dict[str, Any]:
        config = yaml.safe_load(config_content)
        for repo in config.get("repos", []):
            for hook in repo.get("hooks", []):
                if hook.get("id") == hook_id:
                    return hook
        raise AssertionError(f"hook '{hook_id}' not found in .pre-commit-config.yaml")

    @pytest.mark.parametrize(
        ("hook_id", "check_flag"),
        [
            ("check-skill-contract", "--check-contract"),
            ("check-skill-naming", "--check-naming"),
        ],
    )
    def test_discover_skills_check_hook_wired(
        self, pre_commit_config_content: str, hook_id: str, check_flag: str
    ) -> None:
        """The hook exists, runs at pre-commit (not manual), and ignores argv
        (pass_filenames: false + always_run: true: both checks scan the live
        tree, so a delete-only commit must re-verify too)."""
        hook = self._hook_by_id(pre_commit_config_content, hook_id)
        assert f"scripts/discover_skills.py {check_flag}" in hook["entry"]
        assert hook["stages"] == ["pre-commit"]
        assert hook["pass_filenames"] is False
        assert hook["always_run"] is True
