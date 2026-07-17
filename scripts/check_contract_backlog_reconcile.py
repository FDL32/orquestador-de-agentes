#!/usr/bin/env python3
"""WOT-2026-024e: fail-closed gate for ORPHAN FROZEN contracts.

A frozen contract in ticket_contracts.md with no row in the live backlog NOR the
archive is a formal (often DEC-accepted) decision that the batch -- which reads
only backlog.md -- can never execute. This gate lists such orphans and exits
non-zero. It is the vector that left WOT-2026-021a / WOT-2026-016a invisible to
scheduling.

Scope (WOT-2026-024e, CF-audit precise): a block is FROZEN iff its body carries a
``**status:** frozen`` marker (matched by word, some use a suffix). Blocks marked
only ``**Frozen at HEAD:**`` -- operational flight registrations that DO carry a
live row -- are OUT of scope by design; they are not DEC-frozen decisions pending
scheduling.

Identity: ``ticket_id:`` is the PRIMARY authority for a block's ticket; the
``## ... WOT-YYYY-NNNx`` header is a FALLBACK only when ticket_id is absent. The
body is never enumerated for WOT ids (that would match dependencies/citations).

Row resolution reuses check_backlog_contract._ticket_has_row -- the single source
of the two-layout (cell[0] archive / cell[1] live) exact-token scan.

Before: project root via --project-root or AGENT_PROJECT_ROOT (no cwd fallback).
During: parse ticket_contracts.md, cross-reference frozen ids vs backlog+archive.
After: exit 0 when zero orphans; exit 1 listing every orphan otherwise. Read-only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_backlog_contract import _ticket_has_row, resolve_destino_root


# A block is frozen if its body declares `**status:** frozen` (value may carry a
# suffix, e.g. "frozen (adopted 020s)"), so match the word, not the whole cell.
_STATUS_FROZEN_RE = re.compile(r"\*\*status:\*\*\s*frozen", re.IGNORECASE)
_TICKET_ID_RE = re.compile(r"ticket_id:\s*\**\s*(WOT-\d{4}-\w+)", re.IGNORECASE)
_WOT_RE = re.compile(r"WOT-\d{4}-\w+")


def _extract_ticket_id(block: str) -> str | None:
    """Primary: the block's ``ticket_id:`` field. Fallback: the WOT id in the
    block's header line only. NEVER the body (dependencies would false-match)."""
    m = _TICKET_ID_RE.search(block)
    if m:
        return m.group(1)
    first_line = block.splitlines()[0] if block.splitlines() else ""
    hm = _WOT_RE.search(first_line)
    return hm.group(0) if hm else None


def find_frozen_ids(contracts_text: str) -> list[str]:
    """Return the ticket ids of every FROZEN contract block (deduped, ordered)."""
    ids: list[str] = []
    seen: set[str] = set()
    # Split on markdown H2 headers; each chunk is one contract block.
    for block in re.split(r"(?m)^## ", contracts_text):
        if not _STATUS_FROZEN_RE.search(block):
            continue
        tid = _extract_ticket_id(block)
        if tid and tid not in seen:
            seen.add(tid)
            ids.append(tid)
    return ids


def find_orphans(root: Path) -> list[str]:
    """Frozen contract ids that have no row in backlog.md nor the archive."""
    contracts = root / ".agent" / "planning" / "ticket_contracts.md"
    if not contracts.exists():
        return []
    frozen = find_frozen_ids(contracts.read_text(encoding="utf-8-sig"))
    collab = root / ".agent" / "collaboration"
    backlog = collab / "backlog.md"
    archive = collab / "_archive" / "backlog_done.md"
    return [
        tid
        for tid in frozen
        if not _ticket_has_row(tid, backlog) and not _ticket_has_row(tid, archive)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed gate for orphan frozen contracts (WOT-2026-024e)."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino root (or set AGENT_PROJECT_ROOT). No cwd fallback.",
    )
    args = parser.parse_args(argv)

    root, root_error = resolve_destino_root(args.project_root)
    if root_error:
        print(f"[contract-reconcile] {root_error}", file=sys.stderr)
        return 2

    orphans = find_orphans(root)
    if orphans:
        print(
            f"[contract-reconcile] {len(orphans)} frozen contract(s) with NO "
            f"scheduling row (batch can never execute them):",
            file=sys.stderr,
        )
        for tid in orphans:
            print(f"  - {tid}", file=sys.stderr)
        print(
            "  Materialize a backlog.md row for each (human action; this gate never "
            "auto-writes the backlog).",
            file=sys.stderr,
        )
        return 1

    print("[contract-reconcile] OK: every frozen contract has a scheduling row")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
