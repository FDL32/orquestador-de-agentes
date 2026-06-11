#!/usr/bin/env python3
"""
Skill Discovery System — Finds and indexes skills with triggers.

Generates trigger_map for orquestador.py (v2.4+) and external agents (Goose, Claw).

Supports --check-contract for bidirectional prompt<->skill contract validation.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any


def extract_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from SKILL.md.

    Returns empty dict on any error (legacy behavior for backward compat).
    Use parse_frontmatter() for tri-state distinction.
    """
    data, _ = parse_frontmatter(path)
    return data


def _parse_fm_lines(fm_text: str) -> dict[str, Any]:
    """Parse key:value lines from frontmatter text block."""
    data: dict[str, Any] = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ": " in line:
            key, val = line.split(": ", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                val = [t.strip() for t in val[1:-1].split(",")]
            data[key] = val
        elif ":" in line and not line.startswith("#"):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                val = [t.strip() for t in val[1:-1].split(",")]
            data[key] = val
    return data


def _validate_yaml(fm_text: str) -> str | None:
    """Validate frontmatter text as YAML. Returns error string or None."""
    try:
        import yaml

        yaml.safe_load(fm_text)
    except ImportError:
        return None
    except Exception as e:
        return f"YAML_INVALIDO: {e}"
    return None


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Parse YAML frontmatter from a markdown file.

    Returns (data, error) where:
      - error is None: valid frontmatter parsed
      - error == "NO_FRONTMATTER": file has no frontmatter block
      - error is a string: YAML parsing error description
      - data is empty dict on any error
    """
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {}, f"IO_ERROR: {e}"

    if not content.startswith("---"):
        return {}, "NO_FRONTMATTER"

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, "NO_FRONTMATTER"

    fm_text = parts[1].strip()
    if not fm_text:
        return {}, "NO_FRONTMATTER"

    yaml_error = _validate_yaml(fm_text)
    if yaml_error:
        return {}, yaml_error

    return _parse_fm_lines(fm_text), None


def _scan_skills_dir(directory: Path | None) -> dict[str, dict[str, Any]]:
    discovered = {}
    if not directory or not directory.exists() or not directory.is_dir():
        return discovered
    for skill_dir in sorted(directory.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm = extract_frontmatter(skill_file)
        if not fm:
            continue
        skill_name = fm.get("name", skill_dir.name)
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]

        discovered[skill_dir.name] = {
            "name": skill_name,
            "path": str(skill_dir),
            "skill_file": skill_file,
            "triggers": triggers,
            "version": fm.get("version", "1.0.0"),
            "description": fm.get("description", ""),
        }
    return discovered


def discover_skills(
    skills_dir: Path | None = None,
    host_skills_dir: Path | None = None,
) -> dict[str, Any]:
    """Discover all skills and their triggers.

    If host_skills_dir is provided (or auto-discovered under CWD/.agent/skills or bundle_root.parent/.agent/skills),
    host-defined skills override homonymous bundle-defined skills (host-first precedence).
    """
    bundle_root = Path(__file__).resolve().parent.parent
    if skills_dir is None:
        skills_dir = bundle_root / "skills"

    if host_skills_dir is None:
        candidate1 = bundle_root.parent / ".agent" / "skills"
        if candidate1.exists() and candidate1.is_dir():
            host_skills_dir = candidate1
        else:
            candidate2 = Path.cwd() / ".agent" / "skills"
            if candidate2.exists() and candidate2.is_dir():
                host_skills_dir = candidate2

    bundle_skills = _scan_skills_dir(skills_dir)
    host_skills = _scan_skills_dir(host_skills_dir)

    host_triggers = set()
    for skill in host_skills.values():
        host_triggers.update(skill["triggers"])

    filtered_bundle_skills = {}
    for name, skill in bundle_skills.items():
        remaining_triggers = [t for t in skill["triggers"] if t not in host_triggers]
        if remaining_triggers:
            skill["triggers"] = remaining_triggers
            filtered_bundle_skills[name] = skill

    merged_skills = {**filtered_bundle_skills, **host_skills}

    skills: list[dict[str, Any]] = []
    trigger_map: dict[str, str] = {}

    for name in sorted(merged_skills.keys()):
        skill_entry = merged_skills[name]
        skill_file = skill_entry.pop("skill_file")
        skills.append(skill_entry)

        for trigger in skill_entry["triggers"]:
            trigger_map[trigger] = str(skill_file)

    return {
        "skills": skills,
        "trigger_map": trigger_map,
        "total_skills": len(skills),
        "total_triggers": len(trigger_map),
    }


def _get_bundle_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_skill_path(source_prompt: str, bundle_root: Path) -> Path | None:
    """Resolve source_prompt relative to bundle_root (repo_motor).

    Returns None if the path is absolute or not portable (resolves outside bundle_root).
    """
    candidate = (bundle_root / source_prompt).resolve()
    try:
        candidate.relative_to(bundle_root.resolve())
    except ValueError:
        return None
    return candidate


def _error(message: str) -> list[str]:
    return [message]


def _validate_frontmatter_contract_opt_in(
    skill_file: Path, bundle_root: Path
) -> tuple[dict[str, Any] | None, str | None]:
    """Return parsed frontmatter for opted-in role skills or a terminal error."""
    fm, fm_error = parse_frontmatter(skill_file)
    if fm_error == "NO_FRONTMATTER":
        return None, None
    if fm_error:
        rel = skill_file.relative_to(bundle_root).as_posix()
        return None, f"{rel}: YAML invalido ({fm_error})"

    role = fm.get("role", "")
    if role not in ("manager", "builder"):
        return None, None

    source_prompt = fm.get("source_prompt", "")
    contract_id = fm.get("contract_id", "")
    if not (source_prompt or contract_id):
        return None, None

    return fm, None


def _validate_prompt_binding(
    rel_skill_path: str, source_prompt: str, contract_id: str, bundle_root: Path
) -> list[str]:
    """Validate prompt existence, portability, reverse anchor, and contract_id."""
    prompt_path = _resolve_skill_path(source_prompt, bundle_root)
    if prompt_path is None:
        return _error(
            f"{rel_skill_path}: source_prompt '{source_prompt}' no es portable contra repo_motor"
        )
    if not prompt_path.exists():
        return _error(f"{rel_skill_path}: source_prompt '{source_prompt}' no existe")

    prompt_content = prompt_path.read_text(encoding="utf-8")
    expected_anchor = f"Skill canonica: {rel_skill_path}"
    if expected_anchor not in prompt_content:
        return _error(
            f"{rel_skill_path}: prompt '{source_prompt}' no contiene '{expected_anchor}'"
        )

    prompt_contract_pattern = re.compile(
        rf"^contract_id:\s*{re.escape(contract_id)}\s*$", re.MULTILINE
    )
    if not prompt_contract_pattern.search(prompt_content):
        return _error(
            f"{rel_skill_path}: prompt '{source_prompt}' no contiene contract_id '{contract_id}'"
        )

    return []


def _validate_skill_contract(skill_file: Path, bundle_root: Path) -> list[str]:
    """Validate contract for a single skill file.

    Role skills opt into this contract once they declare either
    `source_prompt:` or `contract_id`. From that point onward the contract is
    strict and partial metadata is rejected.
    """
    fm, terminal_error = _validate_frontmatter_contract_opt_in(skill_file, bundle_root)
    if terminal_error:
        return _error(terminal_error)
    if fm is None:
        return []

    rel_skill_path = skill_file.relative_to(bundle_root).as_posix()
    source_prompt = fm.get("source_prompt", "")
    contract_id = fm.get("contract_id", "")

    if not source_prompt:
        return _error(f"{rel_skill_path}: falta source_prompt")

    if not contract_id:
        return _error(f"{rel_skill_path}: falta contract_id")

    return _validate_prompt_binding(
        rel_skill_path, source_prompt, contract_id, bundle_root
    )


def _check_contract() -> int:
    """Validate bidirectional prompt<->skill contract for all skills with role: manager|builder.

    Returns 0 if all contracts are valid, 1 otherwise.
    """
    bundle_root = _get_bundle_root()
    skills_dir = bundle_root / "skills"

    if not skills_dir.exists():
        print("ERROR: skills/ directory not found", file=sys.stderr)
        return 1

    all_errors: list[str] = []

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        errors = _validate_skill_contract(skill_file, bundle_root)
        all_errors.extend(errors)

    if all_errors:
        for e in all_errors:
            print(e, file=sys.stderr)
        return 1

    return 0


def main() -> None:
    """CLI entry point."""

    if "--check-contract" in sys.argv:
        raise SystemExit(_check_contract())

    result = discover_skills()

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
    elif "--goose" in sys.argv:
        print("# Available Triggers for Goose\n")
        for trigger, path in sorted(result["trigger_map"].items()):
            print(f"- **{trigger}** -> {path}")
    else:
        print("\nSKILL DISCOVERY RESULTS\n")
        print(f"Total Skills: {result['total_skills']}")
        print(f"Total Triggers: {result['total_triggers']}\n")

        if result["skills"]:
            print("| Skill | Triggers | Version |")
            print("|-------|----------|---------|")
            for skill in result["skills"]:
                triggers_str = (
                    ", ".join(skill["triggers"]) if skill["triggers"] else "\u2014"
                )
                print(f"| {skill['name']} | {triggers_str} | {skill['version']} |")
        else:
            print("No skills found in skills/ directory")


if __name__ == "__main__":
    main()
