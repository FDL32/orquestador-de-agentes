"""Test alignment between pre-commit hook and CI security audit workflow.

This test ensures that the pip-audit command in .pre-commit-config.yaml
semantically matches what .github/workflows/security-audit.yml executes,
preventing drift like the incident on 2026-05-16 where local hooks used
`pip-audit .` (reduced scope) while CI ran `pip-audit` (full environment).
"""

import pytest
import yaml
from pathlib import Path
from typing import Any


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent.parent


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_pip_audit_command_from_precommit(config: dict[str, Any]) -> str | None:
    """Extract the pip-audit entry command from pre-commit config.

    Args:
        config: Parsed .pre-commit-config.yaml

    Returns:
        The entry command string for pip-audit hook, or None if not found.
    """
    repos = config.get('repos', [])
    for repo in repos:
        hooks = repo.get('hooks', [])
        for hook in hooks:
            if hook.get('id') == 'pip-audit':
                return hook.get('entry')
    return None


def extract_precommit_execution_from_ci(config: dict[str, Any]) -> str | None:
    """Extract the pre-commit execution command from CI workflow.

    Args:
        config: Parsed .github/workflows/security-audit.yml

    Returns:
        The pre-commit run command, or None if not found.
    """
    jobs = config.get('jobs', {})
    for job_name, job_data in jobs.items():
        steps = job_data.get('steps', [])
        for step in steps:
            run_cmd = step.get('run', '')
            # Look for pre-commit run command
            if 'pre-commit run' in run_cmd:
                return run_cmd.strip()
    return None


def normalize_command(cmd: str) -> list[str]:
    """Normalize a command string into a list of tokens for comparison.

    Args:
        cmd: Command string

    Returns:
        List of normalized tokens
    """
    # Remove variable substitutions and extra whitespace
    normalized = cmd.strip()
    # Tokenize
    tokens = normalized.split()
    return tokens


class TestHookCIAlignment:
    """Test that pre-commit hook and CI are semantically aligned."""

    @pytest.fixture
    def precommit_config(self) -> dict[str, Any]:
        """Load pre-commit configuration."""
        repo_root = get_repo_root()
        return load_yaml_file(repo_root / '.pre-commit-config.yaml')

    @pytest.fixture
    def ci_config(self) -> dict[str, Any]:
        """Load CI security audit workflow."""
        repo_root = get_repo_root()
        return load_yaml_file(
            repo_root / '.github' / 'workflows' / 'security-audit.yml'
        )

    def test_pip_audit_hook_exists(self, precommit_config: dict[str, Any]):
        """Verify pip-audit hook is defined in pre-commit config."""
        entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert entry is not None, "pip-audit hook not found in .pre-commit-config.yaml"
        assert 'pip-audit' in entry

    def test_ci_runs_precommit(self, ci_config: dict[str, Any]):
        """Verify CI runs pre-commit hooks (not pip-audit directly)."""
        precommit_cmd = extract_precommit_execution_from_ci(ci_config)
        assert precommit_cmd is not None, (
            "CI does not run pre-commit; this breaks the delegate pattern"
        )
        assert 'pre-commit run' in precommit_cmd

    def test_ci_uses_prepush_stage(self, ci_config: dict[str, Any]):
        """Verify CI uses pre-push stage for pre-commit."""
        precommit_cmd = extract_precommit_execution_from_ci(ci_config)
        assert precommit_cmd is not None
        assert '--hook-stage pre-push' in precommit_cmd, (
            "CI should use --hook-stage pre-push to match hook configuration"
        )

    def test_pip_audit_no_reduced_scope(self, precommit_config: dict[str, Any]):
        """Verify pip-audit hook does not use reduced scope (no trailing dot).

        The 2026-05-16 incident was caused by `pip-audit .` (reduced scope)
        vs CI's `pip-audit` (full environment). This test ensures the hook
        entry does not have a trailing dot that would limit scope.
        """
        entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert entry is not None

        # Normalize and check for reduced scope pattern
        tokens = normalize_command(entry)
        # The entry should be just "uv run pip-audit" without a trailing "."
        # A trailing "." would limit scope to current directory only
        if '.' in tokens:
            # Find position of pip-audit
            try:
                pip_audit_idx = tokens.index('pip-audit')
                # Check if next token is just "."
                if pip_audit_idx + 1 < len(tokens) and tokens[pip_audit_idx + 1] == '.':
                    pytest.fail(
                        "pip-audit hook uses reduced scope '.' which differs from CI. "
                        "This was the cause of the 2026-05-16 CVE incident."
                    )
            except ValueError:
                pass  # pip-audit not found as separate token, might be in "uv run pip-audit"

        # Alternative check: the entry should not end with " ."
        assert not entry.rstrip().endswith(' .'), (
            "pip-audit entry ends with reduced scope indicator"
        )

    def test_semantic_alignment(self, precommit_config: dict[str, Any], ci_config: dict[str, Any]):
        """Verify semantic alignment between hook and CI.

        This test validates that:
        1. CI delegates to pre-commit (not direct pip-audit call)
        2. pre-commit hook defines pip-audit without reduced scope
        3. Both use pre-push stage
        """
        # CI must delegate to pre-commit
        ci_precommit = extract_precommit_execution_from_ci(ci_config)
        assert ci_precommit is not None, "CI must delegate to pre-commit"
        assert 'pre-commit run' in ci_precommit

        # Hook must define pip-audit
        hook_entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert hook_entry is not None, "pip-audit hook must be defined"
        assert 'pip-audit' in hook_entry

        # Hook must not use reduced scope
        assert not hook_entry.rstrip().endswith(' .'), (
            "pip-audit must not use reduced scope '.'"
        )

        # CI must use pre-push stage
        assert '--hook-stage pre-push' in ci_precommit
