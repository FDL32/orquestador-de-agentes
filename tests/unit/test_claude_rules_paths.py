"""Validate conditional loading paths for the real Claude Code rules.

Before: The two rules under test are read from the repository's real rules
    directory, and the measurement module is loaded from its production path.
During: Parse the small YAML frontmatter contract and exercise each required
    sensitive surface against the security rule's declared globs.
After: Confirm both rules declare paths and only the startup rule is autoloaded.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import sys
from pathlib import Path

import pytest


RULES_DIR = Path(__file__).resolve().parents[2] / ".claude" / "rules"


def _parse_paths_frontmatter(text: str) -> list[str]:
    """Return paths from the repository's limited frontmatter contract.

    Before: *text* may contain a Claude Code rule with or without frontmatter.
    During: Require ``---`` as the first line, find the closing delimiter, and
        collect quoted list items immediately following a column-zero ``paths:``.
    After: Return the declared globs, or an empty list when the contract is absent.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []

    try:
        end = lines.index("---", 1)
    except ValueError:
        return []

    frontmatter = lines[1:end]
    try:
        paths_index = frontmatter.index("paths:")
    except ValueError:
        return []

    paths: list[str] = []
    for line in frontmatter[paths_index + 1 :]:
        item = line.strip()
        if not (item.startswith('- "') and item.endswith('"')):
            break
        paths.append(item[3:-1])
    return paths


def _rule_paths(filename: str) -> list[str]:
    """Read one real rule and parse its conditional-loading globs."""
    return _parse_paths_frontmatter((RULES_DIR / filename).read_text(encoding="utf-8"))


def _load_measure_module() -> object:
    """Load the production measurement module using its test-suite pattern."""
    module_name = "measure_md_units_claude_rules_paths"
    module_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "measure_agents_md_units.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load measurement module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


@pytest.mark.parametrize(
    "filename",
    ["README.md", "01-security-architecture.md"],
)
def test_rule_declares_non_empty_paths(filename: str) -> None:
    """Both real rules declare at least one conditional-loading glob."""
    assert _rule_paths(filename)


@pytest.mark.parametrize(
    ("surface", "sample_path"),
    [
        (".claude/**", ".claude/settings.json"),
        (".env*", ".env.example"),
        ("privada/**", "privada/secreto.txt"),
        (".agent/hooks/**", ".agent/hooks/guard_paths.py"),
        ("scripts/pip_audit_project.py", "scripts/pip_audit_project.py"),
    ],
)
def test_security_rule_globs_cover_each_sensitive_surface(
    surface: str, sample_path: str
) -> None:
    """Each sensitive surface has its own matching security-rule glob."""
    paths = _rule_paths("01-security-architecture.md")
    assert surface in paths
    assert any(fnmatch.fnmatchcase(sample_path, path) for path in paths)


def test_only_startup_rule_is_autoloaded() -> None:
    """The production loader sees only the unconditional startup rule."""
    module = _load_measure_module()
    repo_root = Path(__file__).resolve().parents[2]
    assert [path.name for path in module.autoloaded_rules(repo_root)] == [
        "00-startup.md"
    ]
