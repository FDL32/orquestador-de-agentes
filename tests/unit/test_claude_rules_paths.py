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
import re
import sys
from pathlib import Path

import pytest


RULES_DIR = Path(__file__).resolve().parents[2] / ".claude" / "rules"


def _frontmatter_lines(text: str) -> list[str]:
    """Return the lines inside this test's strict frontmatter contract.

    Before: *text* may contain a Claude Code rule with or without frontmatter.
    During: Require ``---`` as the first line and the next exact ``---`` as
        the closing delimiter.
    After: Return only the enclosed lines, or an empty list when the strict
        delimiter contract is absent.

    This helper intentionally implements a stricter contract than the
    production measurement parser: list items use double quotes, the closing
    delimiter is exact, and the ``paths`` key is expected in column zero.
    A legitimate frontmatter reformat (for example, single quotes or an
    inline comment) must update this test too.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []

    try:
        end = lines.index("---", 1)
    except ValueError:
        return []

    return lines[1:end]


def _parse_paths_frontmatter(text: str) -> list[str]:
    """Return paths from the repository's limited frontmatter contract.

    Before: *text* may contain a Claude Code rule with or without frontmatter.
    During: Collect quoted list items immediately following a column-zero
        ``paths:`` in the strict frontmatter returned by
        :func:`_frontmatter_lines`.
    After: Return the declared globs, or an empty list when the contract is absent.

    The parser is intentionally stricter than the production measurement
    parser: items must use double quotes, the closing delimiter must be exact,
    and ``paths:`` must be in column zero. A legitimate frontmatter reformat
    (for example, single quotes or an inline comment) must update this test as
    well as the rule.
    """
    frontmatter = _frontmatter_lines(text)
    if not frontmatter:
        return []

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
    "filename",
    ["README.md", "01-security-architecture.md"],
)
def test_rule_frontmatter_is_well_formed(filename: str) -> None:
    """Rule frontmatter has no tabs and exactly one column-zero paths key."""
    text = (RULES_DIR / filename).read_text(encoding="utf-8")
    frontmatter = _frontmatter_lines(text)

    assert all("\t" not in line for line in frontmatter)
    assert sum(re.match(r"^paths\s*:", line) is not None for line in frontmatter) == 1


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


@pytest.mark.parametrize(
    ("router_domain", "sample_path"),
    [
        (".agent/collaboration/**", ".agent/collaboration/work_plan.md"),
        ("agent_system/refactor_kit/**", "agent_system/refactor_kit/README.md"),
        ("skills/**", "skills/graphify/SKILL.md"),
    ],
)
def test_readme_globs_cover_router_domains(
    router_domain: str, sample_path: str
) -> None:
    """README router domains are declared and match representative paths."""
    paths = _rule_paths("README.md")
    assert router_domain in paths
    assert any(fnmatch.fnmatchcase(sample_path, path) for path in paths)


def test_only_startup_rule_is_autoloaded() -> None:
    """The production loader sees only the unconditional startup rule."""
    module = _load_measure_module()
    repo_root = Path(__file__).resolve().parents[2]
    assert [path.name for path in module.autoloaded_rules(repo_root)] == [
        "00-startup.md"
    ]
