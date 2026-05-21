#!/usr/bin/env python3
"""
Skill Discovery System â€” Finds and indexes skills with triggers.

Generates trigger_map for orquestador.py (v2.4+) and external agents (Goose, Claw).
"""

import json
import sys
from pathlib import Path
from typing import Any


def extract_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from SKILL.md"""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return {}

        _, fm, _ = content.split("---", 2)
        data: dict[str, Any] = {}

        for line in fm.strip().split("\n"):
            if ": " in line:
                key, val = line.split(": ", 1)
                key = key.strip()
                val = val.strip()

                # Parse arrays (triggers: [/impl, implement])
                if val.startswith("[") and val.endswith("]"):
                    val = [t.strip() for t in val[1:-1].split(",")]

                data[key] = val

        return data
    except Exception:
        return {}


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

    # Gather all triggers defined by host skills to enforce trigger-level precedence
    host_triggers = set()
    for skill in host_skills.values():
        host_triggers.update(skill["triggers"])

    # Filter bundle skills: remove triggers overridden by the host
    filtered_bundle_skills = {}
    for name, skill in bundle_skills.items():
        # Keep only triggers that are not defined by any host skill
        remaining_triggers = [t for t in skill["triggers"] if t not in host_triggers]
        if remaining_triggers:
            skill["triggers"] = remaining_triggers
            filtered_bundle_skills[name] = skill

    # Merge skills: host skills take precedence over homonymous or trigger-overlapping bundle skills
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


def main() -> None:
    """CLI entry point."""

    result = discover_skills()

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
    elif "--goose" in sys.argv:
        # Format for .goosehints consumption
        print("# Available Triggers for Goose\n")
        for trigger, path in sorted(result["trigger_map"].items()):
            print(f"- **{trigger}** -> {path}")
    else:
        # Table format
        print("\nSKILL DISCOVERY RESULTS\n")
        print(f"Total Skills: {result['total_skills']}")
        print(f"Total Triggers: {result['total_triggers']}\n")

        if result["skills"]:
            print("| Skill | Triggers | Version |")
            print("|-------|----------|---------|")
            for skill in result["skills"]:
                triggers_str = (
                    ", ".join(skill["triggers"]) if skill["triggers"] else "â€”"
                )
                print(f"| {skill['name']} | {triggers_str} | {skill['version']} |")
        else:
            print("No skills found in skills/ directory")


if __name__ == "__main__":
    main()
