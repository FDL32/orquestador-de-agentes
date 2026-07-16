#!/usr/bin/env python3
"""
Configuration validator for agent system.

Validates:
- .agent_allowlist.json structure
- .agent_denylist.json structure
- Skill trigger uniqueness (no duplicates)
- Skill frontmatter validity
- agents.json of the MOTOR, including the ensemble_* keys (WOT-2026-019o).
  The schema itself lives ONCE in .agent/agents_config.py::_validate_config
  (single-layer rule); this script only invokes it as a CLI gate. Resolution
  is MOTOR-EXPLICIT (M9): the motor root is derived from THIS file's location,
  independent of AGENT_PROJECT_ROOT (whose priority-1 resolution would point
  at a workspace whose agents.json has no ensemble_* keys).

Exit codes: 0 (valid), 1 (invalid)
"""

import json
import sys
from pathlib import Path


# Import skill discovery utilities
try:
    from discover_skills import discover_skills, extract_frontmatter
except ImportError:
    from scripts.discover_skills import discover_skills, extract_frontmatter

# Motor-explicit root (M9): the repo that owns THIS script, never the env.
MOTOR_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = MOTOR_ROOT / ".agent"
# APPEND, never insert(0): with .agent up front, `runtime` would resolve to
# `.agent/runtime/` instead of `<motor>/runtime/` (pytest-collection hazard
# documented in AGENTS.md).
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import AgentsConfigError, load_agents_config  # noqa: E402


# Default configurations (used when files are missing or invalid)
DEFAULT_ALLOWLIST = {
    "write_roots": [".", "src/", "tests/", ".agent/", "changelog/", "tools/"],
    "protected_paths": ["privada/", "data/sectors/", ".env"],
}
DEFAULT_DENYLIST = {
    "blocked_patterns": ["^privada/.*", ".*/.env", "^data/sectors/.*", ".*/.git/.*"],
    "blocked_commands": ["rm -rf", "git push --force", "pip install --upgrade-all"],
}


def load_allowlist() -> dict:
    """Load .agent_allowlist.json, fallback to defaults."""
    path = Path(".agent_allowlist.json")
    if not path.exists():
        return DEFAULT_ALLOWLIST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return DEFAULT_ALLOWLIST
        if "write_roots" not in data or "protected_paths" not in data:
            return DEFAULT_ALLOWLIST
        return data
    except (json.JSONDecodeError, OSError):
        return DEFAULT_ALLOWLIST


def load_denylist() -> dict:
    """Load .agent_denylist.json, fallback to defaults."""
    path = Path(".agent_denylist.json")
    if not path.exists():
        return DEFAULT_DENYLIST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return DEFAULT_DENYLIST
        if "blocked_patterns" not in data or "blocked_commands" not in data:
            return DEFAULT_DENYLIST
        return data
    except (json.JSONDecodeError, OSError):
        return DEFAULT_DENYLIST


def validate_trigger_uniqueness() -> list[str]:
    """Check that all triggers in skills/ are unique. Return list of duplicate triggers."""
    result = discover_skills()
    trigger_map = result.get("trigger_map", {})
    triggers = list(trigger_map.keys())
    seen = {}
    duplicates = []
    for t in triggers:
        if t in seen:
            duplicates.append(t)
        else:
            seen[t] = 1
    return duplicates


def validate_skill_frontmatter() -> list[str]:
    """Validate all SKILL.md files have valid required frontmatter. Return list of errors."""
    errors = []
    skills_dir = Path("skills")
    if not skills_dir.exists():
        return errors  # No skills dir is not an error

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm = extract_frontmatter(skill_file)
        if not fm:
            errors.append(f"{skill_file}: missing or invalid frontmatter")
            continue
        if "name" not in fm:
            errors.append(f"{skill_file}: missing 'name' field")
        if "triggers" not in fm:
            errors.append(f"{skill_file}: missing 'triggers' field")
        # triggers must be non-empty list
        elif not isinstance(fm["triggers"], list) and not isinstance(
            fm["triggers"], str
        ):
            errors.append(f"{skill_file}: 'triggers' must be list or string")
    return errors


def validate_motor_agents_config() -> str | None:
    """CLI gate over the motor's agents.json (WOT-2026-019o).

    Before: MOTOR_ROOT/.agent/config/agents.json exists (the motor's own
        versioned config, resolved from this file's location -- M9: never via
        AGENT_PROJECT_ROOT, whose priority-1 resolution points at a workspace
        that has, and will keep having, 0 ensemble_* keys).
    During: invokes agents_config.load_agents_config(project_root=MOTOR_ROOT),
        the SINGLE validation layer (schema_version, backends, roles,
        ensemble_profiles/pipelines/private_roots, credential-literal ban).
        This function re-declares NO schema of its own.
    After: returns None if valid; returns the error message string if invalid
        (the caller prints it and exits 1).
    """
    try:
        load_agents_config(project_root=MOTOR_ROOT)
    except AgentsConfigError as exc:
        return str(exc)
    return None


def main() -> int:
    # 1. Load configurations (always succeeds due to defaults)
    load_allowlist()
    load_denylist()

    # 2. Validate trigger uniqueness
    duplicates = validate_trigger_uniqueness()
    if duplicates:
        print(f"Validation FAILED: Duplicate triggers detected: {duplicates}")
        return 1

    # 3. Validate skill frontmatter
    frontmatter_errors = validate_skill_frontmatter()
    if frontmatter_errors:
        print("Validation FAILED: Frontmatter errors:")
        for err in frontmatter_errors:
            print(f"  - {err}")
        return 1

    # 4. Validate the motor's agents.json (single layer: agents_config.py)
    agents_error = validate_motor_agents_config()
    if agents_error:
        print(f"Validation FAILED: agents.json invalid: {agents_error}")
        return 1

    print("Configuration valid — all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
