#!/usr/bin/env python3
"""Check that all declared deliverables in work_plan.md exist on disk.

Exits 0 if all exist, 1 if any are missing.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


PROJECT_ROOT = resolve_project_root()
# Allow overriding PROJECT_ROOT for testing
if "TEST_PROJECT_ROOT" in os.environ:
    PROJECT_ROOT = Path(os.environ["TEST_PROJECT_ROOT"])

WORK_PLAN = PROJECT_ROOT / ".agent" / "collaboration" / "work_plan.md"


def looks_like_path(token: str) -> bool:
    """Determine if a token extracted from backticks looks like a file path candidate."""
    if not token or " " in token:
        return False
    # Exclude obvious non-paths like uppercase variables/constants
    if token.isupper() and "_" in token:
        return False
    # Must have a dot (file extension) or path slashes
    return "." in token or "/" in token or "\\" in token


def resolve_with_fallbacks(token: str) -> Path | None:
    """Resolve a token to a Path using relative, absolute, and common folders fallbacks."""
    p = Path(token)
    if not p.is_absolute():
        p = PROJECT_ROOT / p

    if p.exists():
        return p.resolve()

    # Fallback to search common directories
    name = p.name

    # 1. Check in .agent/collaboration
    collab_path = PROJECT_ROOT / ".agent" / "collaboration" / name
    if collab_path.exists():
        return collab_path.resolve()

    # 2. Check in scripts/
    scripts_path = PROJECT_ROOT / "scripts" / name
    if scripts_path.exists():
        return scripts_path.resolve()

    # 3. Check for hidden file (dot-prepended) in PROJECT_ROOT
    hidden_path = PROJECT_ROOT / f".{name}"
    if hidden_path.exists():
        return hidden_path.resolve()

    # 4. Check in skills/
    skills_dir = PROJECT_ROOT / "skills"
    if skills_dir.exists():
        # Check immediate subdirectories first
        for item in skills_dir.iterdir():
            if item.is_dir() and item.name == name:
                return item.resolve()
            # Check files within skill directories (e.g. SKILL.md)
            skill_file = item / name
            if skill_file.exists():
                return skill_file.resolve()

    return None


def _process_backtick_tokens(line: str, paths: set[Path]) -> None:
    """Extract and validate all backticked tokens from a line, adding them to paths."""
    tokens = re.findall(r"`([^`]+)`", line)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.endswith("/") or token.endswith("\\"):
            # Explicitly ignore directory trails
            continue
        if any(x in token for x in ["<", ">", "{", "}", "YYYY", "NNN"]):
            # Ignore placeholder paths
            continue
        token = token.rstrip(",").strip()

        if not looks_like_path(token):
            continue

        resolved = resolve_with_fallbacks(token)
        if resolved:
            paths.add(resolved)
        else:
            # If not found but looks like a path, add the default resolved path to missing list
            p = Path(token)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            paths.add(p.resolve())


def extract_paths_from_work_plan(content: str) -> set[Path]:
    paths = set()
    in_section = False

    # Sections to scan
    scan_keywords = {
        "deliverables",
        "files likely touched",
        "must create",
        "must modify",
    }
    # Sections to explicitly stop scanning
    stop_headers = {
        "## tareas",
        "## acceptance criteria",
        "## riesgos",
        "## plan de rollback",
        "## orden operativo",
    }

    def _heading_level(line: str) -> int:
        stripped = line.lstrip()
        return len(stripped) - len(stripped.lstrip("#"))

    for line in content.splitlines():
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # Check for section boundaries (any header starts with '#')
        if line_stripped.startswith("#"):
            # Check if this header stops the scanning
            if any(stop in line_lower for stop in stop_headers):
                in_section = False
                continue

            # Check if this header starts the scanning
            if any(kw in line_lower for kw in scan_keywords):
                in_section = True
                continue

            if in_section and _heading_level(line_stripped) > 2:
                continue

            # A new top-level/section header resets scanning.
            in_section = False

        # Also detect bold tags as section starters
        if any(f"**{kw}" in line_lower for kw in ["must create", "must modify"]):
            in_section = True

        # Only process list items when in the correct section
        if in_section and (
            line_stripped.startswith("-") or line_stripped.startswith("*")
        ):
            _process_backtick_tokens(line_stripped, paths)

    return paths


def main() -> int:
    if not WORK_PLAN.exists():
        print(
            f"[check-deliverables] Active work_plan.md not found at {WORK_PLAN}",
            file=sys.stderr,
        )
        return 0  # Fallback if no active plan

    content = WORK_PLAN.read_text(encoding="utf-8")
    declared_paths = extract_paths_from_work_plan(content)

    if not declared_paths:
        print(
            "[check-deliverables] No deliverables declared in work_plan.md",
            file=sys.stderr,
        )
        return 0

    missing = []
    print(f"[check-deliverables] Checking {len(declared_paths)} declared deliverables:")
    for path in sorted(declared_paths):
        try:
            rel_path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel_path = path

        if path.exists():
            print(f"  [OK] {rel_path}")
        else:
            print(f"  [MISSING] {rel_path}")
            missing.append(path)

    if missing:
        print(
            f"\n[check-deliverables] ERROR: {len(missing)} deliverable(s) are missing!",
            file=sys.stderr,
        )
        return 1

    print(
        "\n[check-deliverables] SUCCESS: All declared deliverables exist.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
