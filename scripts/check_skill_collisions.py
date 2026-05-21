#!/usr/bin/env python3
"""Detect duplicate skill `name:` or `triggers:` across bundle and host skills.

Adapted from wshobson/agents tools/check_agent_name_collisions.py (MIT)
with two changes:
  - glob target switched from plugins/*/agents/*.md to skills/*/SKILL.md and
    .agent/skills/*/SKILL.md
  - additionally detects duplicate trigger tokens across skills (more likely
    collision vector than name in this repo's skill ecosystem)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


FRONTMATTER_RE = re.compile(r"\A﻿?---\n(?P<frontmatter>.*?)\n---", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*(?P<name>.+?)\s*$", re.MULTILINE)
TRIGGERS_RE = re.compile(r"^triggers:\s*\[(?P<triggers>.+?)\]\s*$", re.MULTILINE)


def _read_frontmatter(path: Path) -> str | None:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    match = FRONTMATTER_RE.search(content)
    return match.group("frontmatter") if match else None


def _extract_name(frontmatter: str) -> str | None:
    match = NAME_RE.search(frontmatter)
    if not match:
        return None
    raw = match.group("name").split("#", 1)[0].strip()
    return raw.strip("\"'") or None


def _extract_triggers(frontmatter: str) -> list[str]:
    match = TRIGGERS_RE.search(frontmatter)
    if not match:
        return []
    items = match.group("triggers").split(",")
    return [item.strip().strip("\"'") for item in items if item.strip()]


def scan_skills(root: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Return (names_by_path, triggers_by_path) maps for collision analysis."""
    names: dict[str, list[Path]] = defaultdict(list)
    triggers: dict[str, list[Path]] = defaultdict(list)
    skill_paths = sorted(
        {
            *root.glob("skills/*/SKILL.md"),
            *root.glob(".agent/skills/*/SKILL.md"),
        }
    )
    for skill_path in skill_paths:
        frontmatter = _read_frontmatter(skill_path)
        if frontmatter is None:
            continue
        name = _extract_name(frontmatter)
        if name:
            names[name].append(skill_path)
        for trigger in _extract_triggers(frontmatter):
            triggers[trigger].append(skill_path)
    return names, triggers


def _report_duplicates(label: str, mapping: dict[str, list[Path]], root: Path) -> int:
    duplicates = {key: paths for key, paths in mapping.items() if len(paths) > 1}
    if not duplicates:
        return 0
    print(f"\n{len(duplicates)} duplicate {label}(s) found:")
    for key, paths in sorted(duplicates.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {key!r} ({len(paths)} files)")
        for path in paths:
            print(f"    - {path.relative_to(root)}")
    return len(duplicates)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect duplicate skill name: or triggers: across skills/*/SKILL.md "
            "and .agent/skills/*/SKILL.md"
        )
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Report duplicates but exit 0 (informational mode).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    names, triggers = scan_skills(root)

    dup_names = _report_duplicates("name", names, root)
    dup_triggers = _report_duplicates("trigger", triggers, root)

    if dup_names == 0 and dup_triggers == 0:
        print("OK: no skill name or trigger collisions")
        return 0

    if args.allow_duplicates:
        return 0
    print(
        "\nERROR: collisions found (use --allow-duplicates to make non-fatal)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
