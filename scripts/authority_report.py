#!/usr/bin/env python3
"""Validate that all tools use the same .agent/collaboration authority.

The operational authority is the `orquestador_de_agentes/` tree. Any other
`.agent/collaboration` copies are treated as historical or test fixtures and
must not be used by launchers, bridges or controllers.

Exit code:
  0: All checks passed, authority is canonical
  1: Split-brain detected, tools would diverge
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# Bootstrap: motor root on sys.path so bus.ticket_id is importable.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from bus.ticket_id import TICKET_ID_RE  # noqa: E402


def find_all_agent_dirs(root: Path) -> dict[str, str]:
    """Find all .agent/collaboration directories in tree.

    Returns a mapping of absolute path strings to ticket IDs.
    """
    found: dict[str, str] = {}
    try:
        for agent_collab in root.rglob(".agent/collaboration"):
            # Skip test artifacts and factories. Those are intentional fixtures
            # and do not represent an operational authority.
            path_str = str(agent_collab).lower()
            if (
                "test_runtime" in path_str
                or "factory" in path_str
                or "\\tests\\" in path_str
                or "/tests/" in path_str
            ):
                continue

            work_plan = agent_collab / "work_plan.md"
            if work_plan.exists():
                # Extract ticket ID from the active work_plan block.
                content = work_plan.read_text(encoding="utf-8", errors="ignore")
                ticket = extract_ticket_id(content)
                found[str(agent_collab)] = ticket
    except (OSError, ValueError, json.JSONDecodeError):
        return found
    return found


def extract_ticket_id(content: str) -> str:
    """Extract ticket ID from work_plan.md content.

    WT-2026-251a: uses TICKET_ID_RE (canonical, accepts WP, WT, 3-letter prefixes)
    instead of inline WP|WT-only pattern.
    """
    ticket = "UNKNOWN"
    for line in content.splitlines()[:60]:
        m = TICKET_ID_RE.search(line)
        if m:
            ticket = m.group(0)
            break
    return ticket


def is_canonical_authority(path: str | Path, canonical_root: Path) -> bool:
    """Check if the given path represents the canonical authority."""
    try:
        candidate = Path(path).resolve()
        canonical = canonical_root.resolve()
    except (OSError, ValueError, TypeError):
        return False
    return candidate == canonical


def detect_legacy_copies(copies: dict[str, str], canonical_path: str) -> dict[str, str]:
    """Identify legacy collaboration copies excluding tests."""
    return {
        path: ticket
        for path, ticket in copies.items()
        if path != canonical_path and "tests" not in path.lower().replace("\\", "/")
    }


def main() -> int:
    """Validate single authority."""
    root = Path(__file__).parent.parent
    canonical_root = root / ".agent" / "collaboration"

    # Find all copies
    copies = find_all_agent_dirs(root)

    print("[AUTHORITY] Scanning for .agent/collaboration copies...")
    print()

    for path, ticket in sorted(copies.items()):
        marker = (
            "[OK] CANONICAL"
            if is_canonical_authority(path, canonical_root)
            else "[!] LEGACY"
        )
        print(f"{marker}: {path}")
        print(f"         Active ticket: {ticket}")

    print()

    canonical = str(canonical_root)
    if canonical not in copies:
        print("[ERROR] No canonical orquestador_de_agentes found!")
        print(f"[DEBUG] Expected: {canonical}")
        print(f"[DEBUG] Scanned {len(copies)} directories")
        return 1

    legacy_copies = detect_legacy_copies(copies, canonical)

    if legacy_copies:
        print(f"[WARN] Found {len(legacy_copies)} legacy collaboration copies")
        for path, ticket in sorted(legacy_copies.items()):
            print(f"[LEGACY] {path}")
            print(f"         Active ticket: {ticket}")
        print()

    print(f"[OK] Single authority confirmed: {canonical}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
