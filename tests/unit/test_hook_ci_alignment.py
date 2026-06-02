"""Test alignment between pre-commit hook and CI security audit workflow.

This test ensures that the pip-audit command in .pre-commit-config.yaml
semantically matches what .github/workflows/security-audit.yml executes,
preventing drift like the incident on 2026-05-16 where local hooks used
`pip-audit .` (reduced scope) while CI ran `pip-audit` (full environment).
"""

from pathlib import Path
from typing import Any

import pytest
import yaml


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent.parent


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_pip_audit_command_from_precommit(config: dict[str, Any]) -> str | None:
    """Extract the pip-audit entry command from pre-commit config.

    Args:
        config: Parsed .pre-commit-config.yaml

    Returns:
        The entry command string for pip-audit hook, or None if not found.
    """
    repos = config.get("repos", [])
    for repo in repos:
        hooks = repo.get("hooks", [])
        for hook in hooks:
            if hook.get("id") == "pip-audit":
                return hook.get("entry")
    return None


def extract_precommit_execution_from_ci(config: dict[str, Any]) -> str | None:
    """Extract the pre-commit execution command from CI workflow.

    Args:
        config: Parsed .github/workflows/security-audit.yml

    Returns:
        The pre-commit run command, or None if not found.
    """
    jobs = config.get("jobs", {})
    for job_data in jobs.values():
        steps = job_data.get("steps", [])
        for step in steps:
            run_cmd = step.get("run", "")
            # Look for pre-commit run command
            if "pre-commit run" in run_cmd:
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
        return load_yaml_file(repo_root / ".pre-commit-config.yaml")

    @pytest.fixture
    def ci_config(self) -> dict[str, Any]:
        """Load CI security audit workflow."""
        repo_root = get_repo_root()
        return load_yaml_file(
            repo_root / ".github" / "workflows" / "security-audit.yml"
        )

    def test_pip_audit_hook_exists(self, precommit_config: dict[str, Any]):
        """Verify pip-audit hook is defined in pre-commit config."""
        entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert entry is not None, "pip-audit hook not found in .pre-commit-config.yaml"
        # Entry delegates to wrapper; wrapper name or pip-audit must be present
        assert "pip_audit_project.py" in entry or "pip-audit" in entry

    def test_ci_runs_precommit(self, ci_config: dict[str, Any]):
        """Verify CI runs pre-commit hooks (not pip-audit directly)."""
        precommit_cmd = extract_precommit_execution_from_ci(ci_config)
        assert precommit_cmd is not None, (
            "CI does not run pre-commit; this breaks the delegate pattern"
        )
        assert "pre-commit run" in precommit_cmd

    def test_ci_uses_prepush_stage(self, ci_config: dict[str, Any]):
        """Verify CI uses pre-push stage for pre-commit."""
        precommit_cmd = extract_precommit_execution_from_ci(ci_config)
        assert precommit_cmd is not None
        assert "--hook-stage pre-push" in precommit_cmd, (
            "CI should use --hook-stage pre-push to match hook configuration"
        )

    def test_pip_audit_uses_project_wrapper(self, precommit_config: dict[str, Any]):
        """Verify pip-audit hook delegates to pip_audit_project.py wrapper.

        The wrapper exports uv.lock (all groups) to a temp requirements.txt
        and runs pip-audit -r against it. This guarantees:
        - Only project dependencies are audited (not the system Python env).
        - All dependency groups are included.
        - Results are reproducible from locked versions.

        Replaces the old 'no trailing dot' check, which guarded against a
        different anti-pattern (reduced-scope `pip-audit .`).
        """
        entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert entry is not None
        assert "pip_audit_project.py" in entry, (
            "pip-audit hook must delegate to scripts/pip_audit_project.py. "
            "Direct invocations (uv run pip-audit, pip-audit ., etc.) audit "
            "the wrong surface: either the system Python env or only pyproject.toml "
            "without dependency-groups."
        )

    def test_pip_audit_wrapper_script_exists(self):
        """Verify the pip_audit_project.py wrapper script exists."""
        repo_root = get_repo_root()
        wrapper = repo_root / "scripts" / "pip_audit_project.py"
        assert wrapper.exists(), (
            "scripts/pip_audit_project.py not found. "
            "The pre-commit hook entry references this wrapper."
        )

    def test_pip_audit_wrapper_audits_uv_lock(self):
        """Verify the wrapper exports from uv.lock and uses -r flag.

        The wrapper must call `uv export --all-groups ... --locked` to get
        the full project surface, then pass `-r <tmpfile>` to pip-audit.
        This protects against future edits that skip the lockfile export.
        """
        repo_root = get_repo_root()
        wrapper_src = (repo_root / "scripts" / "pip_audit_project.py").read_text(
            encoding="utf-8"
        )
        assert "uv" in wrapper_src and "export" in wrapper_src, (
            "Wrapper must call `uv export` to derive the auditable surface from uv.lock"
        )
        assert "--all-groups" in wrapper_src, (
            "Wrapper must pass --all-groups to include dev/test dependency groups"
        )
        assert "--locked" in wrapper_src, (
            "Wrapper must pass --locked to use pinned versions from uv.lock"
        )
        assert (
            '"-r"' in wrapper_src
            or "'-r'" in wrapper_src
            or '"-r", str(' in wrapper_src
        ), (
            "Wrapper must pass -r <requirements_file> to pip-audit, not audit the global env"
        )

    def test_semantic_alignment(
        self, precommit_config: dict[str, Any], ci_config: dict[str, Any]
    ):
        """Verify semantic alignment between hook and CI.

        This test validates that:
        1. CI delegates to pre-commit (not direct pip-audit call)
        2. pre-commit hook defines pip-audit without reduced scope
        3. Both use pre-push stage
        """
        # CI must delegate to pre-commit
        ci_precommit = extract_precommit_execution_from_ci(ci_config)
        assert ci_precommit is not None, "CI must delegate to pre-commit"
        assert "pre-commit run" in ci_precommit

        # Hook must define pip-audit (via wrapper or direct)
        hook_entry = extract_pip_audit_command_from_precommit(precommit_config)
        assert hook_entry is not None, "pip-audit hook must be defined"
        assert "pip_audit_project.py" in hook_entry or "pip-audit" in hook_entry

        # Hook must delegate to the project wrapper (not direct invocation)
        assert "pip_audit_project.py" in hook_entry, (
            "pip-audit hook must use scripts/pip_audit_project.py wrapper"
        )

        # CI must use pre-push stage
        assert "--hook-stage pre-push" in ci_precommit
