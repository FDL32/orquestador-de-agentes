#!/usr/bin/env python3
"""CLI wrapper for bootstrap and memory context loading.

WT-2026-191: Proporciona un comando ejecutable determinista para cargar
contexto de memoria L3/L2/L1, reemplazando la dependencia de prosa en
session_bootstrap.md.

Usage:
    python scripts/memory_context.py --bootstrap
        Print bootstrap context (L3 -> L2 -> L1 fallback)

    python scripts/memory_context.py --compact
        Print compact context (L3 + L2 combined)

    python scripts/memory_context.py --status
        Show which memory tiers are available

    python scripts/memory_context.py --recall [--query <keyword>] [--limit N]
        Recall raw observations (optional keyword filter)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Bootstrap project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bus.memory_loader import (  # noqa: E402
    get_bootstrap_context,
    get_compact_context,
    get_memory_tier_status,
    recall_observations,
)


def _format_status() -> str:
    """Format memory tier status as human-readable string."""
    status = get_memory_tier_status()
    parts: list[str] = ["# Memory Tier Status", ""]
    for tier in ("l3", "l2", "l1"):
        label = {
            "l3": "L3 (memory_profile.md)",
            "l2": "L2 (memory_rules.md)",
            "l1": "L1 (observations.jsonl)",
        }[tier]
        status_icon = "yes" if status[tier] else "no"
        parts.append(f"- {label}: {status_icon}")
    parts.append("")
    parts.append("Loading order: L3 → L2 → L1")
    return "\n".join(parts)


def _ensure_utf8_stdout() -> None:
    """Ensure stdout uses UTF-8 encoding to avoid UnicodeEncodeError."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, AttributeError):
        pass


def main() -> int:  # noqa: C901
    """Main entry point for memory_context CLI."""
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Memory context: bootstrap, compact, recall, status"
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Print bootstrap context (L3 -> L2 -> L1 fallback)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact context (L3 + L2 combined)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show which memory tiers are available",
    )
    parser.add_argument(
        "--recall",
        action="store_true",
        help="Recall raw observations (use with --query and --limit)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Keyword filter for --recall",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max observations to return (default: 15)",
    )

    args = parser.parse_args()

    # Determine mode from flags
    mode = "bootstrap" if args.bootstrap else ""

    if args.compact:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "compact"

    if args.status:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "status"

    if args.recall:
        if mode:
            print("Error: Use only one mode flag at a time", file=sys.stderr)
            return 1
        mode = "recall"

    # Default mode
    if not mode:
        mode = "bootstrap"

    # Execute mode
    if mode == "bootstrap":
        ctx = get_bootstrap_context()
        if ctx:
            print(ctx)
        else:
            print("# Bootstrap Context\n\nNo memory files found.", file=sys.stderr)
            return 1

    elif mode == "compact":
        ctx = get_compact_context()
        if ctx:
            print(ctx)
        else:
            print("# Compact Context\n\nNo memory files found.", file=sys.stderr)
            return 1

    elif mode == "status":
        print(_format_status())

    elif mode == "recall":
        observations = recall_observations(query=args.query, limit=args.limit)
        if not observations:
            print("No observations found.", file=sys.stderr)
            return 1
        for obs in observations:
            ts = str(obs.get("timestamp") or "")[:19]
            topic = obs.get("topic", "general")
            signal = str(obs.get("signal") or "")[:150]
            source = obs.get("source", "unknown")
            print(f"- [{ts}] **{topic}**: {signal} ({source})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
