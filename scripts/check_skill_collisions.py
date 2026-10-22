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
TRIGGERS_LIST_RE = re.compile(r"^triggers:\s*\[(?P<triggers>.+?)\]\s*$", re.MULTILINE)
# Revisor finding (WOT-2026-118a, Codex): a scalar `triggers: foo` (no [...])
# bypassed TRIGGERS_LIST_RE entirely, so a malformed scalar trigger reached
# discover_skills.py's trigger_map while this guard silently saw zero
# triggers for that skill. discover_skills.py's _parse_fm_lines() treats a
# bare (non-bracketed) value as a single-item list; this regex mirrors that.
TRIGGERS_SCALAR_RE = re.compile(
    r"^triggers:\s*(?P<trigger>[^\[\n][^\n]*?)\s*$", re.MULTILINE
)

# [D1] .agent/rules/common/skill_trigger_governance.md -- closed FORMAT
# vocabulary for a trigger (not a fixed word list): a kebab-case lowercase
# token with an optional leading "/". Verified non-disruptive against every
# live skills/*/SKILL.md trigger before adoption (WOT-2026-118a).
TRIGGER_FORMAT_RE = re.compile(r"^/?[a-z][a-z0-9-]*$")

# [D2] closed vocabulary for conflict_policy. "deny-wins" is the historical
# default (any duplicate trigger blocks); "host-wins" formalizes mechanically
# the host-first precedence discover_skills.py already applies at runtime.
CONFLICT_POLICIES = ("deny-wins", "host-wins")
DEFAULT_CONFLICT_POLICY = "deny-wins"


def _is_host_path(path: Path) -> bool:
    """True when *path* lives under a `.agent/skills/` tree (host layer).

    Revisor finding (WOT-2026-118a, Codex): checking membership of ".agent"
    and "skills" independently anywhere in `path.parts` false-positives when
    the REPO ROOT itself happens to sit under a directory literally named
    ".agent" (e.g. a checkout under a `.agent` ancestor dir with its own
    unrelated `skills/` subfolder). Require the contiguous pair instead --
    the actual `.agent/skills/` shape `discover_skills.py`'s
    `host_skills_dir` resolves against.
    """
    parts = path.parts
    return any(
        parts[i] == ".agent" and parts[i + 1] == "skills" for i in range(len(parts) - 1)
    )


def _invalid_trigger_formats(
    triggers_by_path: dict[str, list[Path]],
) -> list[tuple[str, list[Path]]]:
    """[D1] Return (trigger, paths) for every trigger violating TRIGGER_FORMAT_RE.

    A malformed trigger is always an error, independent of conflict_policy:
    it can never be resolved deterministically (see D1).
    """
    return [
        (trigger, paths)
        for trigger, paths in sorted(triggers_by_path.items())
        if not TRIGGER_FORMAT_RE.match(trigger)
    ]


def resolve_conflict(paths: list[Path], policy: str) -> bool:
    """[D2]/[D3] Return True if *paths* (sharing one trigger) stay denied under *policy*.

    Before: ``paths`` is the full set of SKILL.md files declaring the same
        trigger (len >= 2, duplicates already established by the caller);
        ``policy`` is one of CONFLICT_POLICIES.
    During: ``deny-wins`` never resolves anything -- always denied.
        ``host-wins`` resolves ONLY a 1:1 bundle/host pair (exactly one path
        under a `.agent/skills/` tree and one that is not). This is a
        deliberately CONSERVATIVE subset of what discover_skills.py's
        host-first precedence resolves at runtime (which also covers 1:N/N:1
        host-vs-multiple-bundle cases) -- see D2's correction note in
        .agent/rules/common/skill_trigger_governance.md. Any other shape
        (same-layer duplicate, 3+ files) stays denied here even though the
        runtime may resolve it.
    After: True (still a conflict, contributes to exit code) or False
        (resolved, reported as info only). Depends only on path structure,
        never on discovery order (D3: deterministic across runs).
    """
    if policy == "host-wins":
        host_count = sum(1 for p in paths if _is_host_path(p))
        if len(paths) == 2 and host_count == 1:
            return False
    return True


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
    list_match = TRIGGERS_LIST_RE.search(frontmatter)
    if list_match:
        items = list_match.group("triggers").split(",")
        return [item.strip().strip("\"'") for item in items if item.strip()]
    scalar_match = TRIGGERS_SCALAR_RE.search(frontmatter)
    if scalar_match:
        value = scalar_match.group("trigger").strip().strip("\"'")
        return [value] if value else []
    return []


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


def _report_trigger_conflicts(
    triggers: dict[str, list[Path]], root: Path, policy: str
) -> int:
    """[D2]/[D3] Report trigger duplicates, applying *policy* to each.

    A duplicate resolved by `resolve_conflict()` under *policy* is still
    printed (D3: resolution is informational, never silent) but does not
    count toward the returned denied-conflict total.
    """
    duplicates = {key: paths for key, paths in triggers.items() if len(paths) > 1}
    if not duplicates:
        return 0
    denied = 0
    for trigger, paths in sorted(
        duplicates.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        still_denied = resolve_conflict(paths, policy)
        verdict = "DENIED" if still_denied else f"RESOLVED by {policy}"
        print(f"\ntrigger {trigger!r} ({len(paths)} files) -- {verdict}:")
        for path in paths:
            tag = "host" if _is_host_path(path) else "bundle"
            print(f"    - [{tag}] {path.relative_to(root)}")
        if still_denied:
            denied += 1
    return denied


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
    parser.add_argument(
        "--conflict-policy",
        choices=CONFLICT_POLICIES,
        default=DEFAULT_CONFLICT_POLICY,
        help=(
            "[D2] How a duplicate trigger is resolved: 'deny-wins' (default, "
            "any duplicate blocks) or 'host-wins' (a 1:1 bundle/host pair "
            "resolves the way discover_skills.py already resolves it at "
            "runtime; any other shape still blocks)."
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    names, triggers = scan_skills(root)

    dup_names = _report_duplicates("name", names, root)
    denied_triggers = _report_trigger_conflicts(triggers, root, args.conflict_policy)
    invalid_format = _invalid_trigger_formats(triggers)
    if invalid_format:
        print(f"\n{len(invalid_format)} trigger(s) violate the closed format [D1]:")
        for trigger, paths in invalid_format:
            print(f"  {trigger!r}")
            for path in paths:
                print(f"    - {path.relative_to(root)}")

    if dup_names == 0 and denied_triggers == 0 and not invalid_format:
        print("OK: no skill name or trigger collisions")
        return 0

    # [D1] Revisor finding (WOT-2026-118a, Codex): --allow-duplicates is a
    # waiver for DUPLICATES (dup_names/denied_triggers), never for a malformed
    # trigger -- D1 declares format violations "SIEMPRE un error". A skill
    # with an invalid trigger and zero duplicates must still exit 1 even with
    # --allow-duplicates.
    if args.allow_duplicates and not invalid_format:
        return 0
    print(
        "\nERROR: collisions found (use --allow-duplicates to make non-fatal)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
