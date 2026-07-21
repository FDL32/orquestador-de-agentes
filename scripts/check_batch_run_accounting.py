#!/usr/bin/env python3
"""GSR-subset check for autonomous batch_run reports (WOT-2026-025k).

Contract: in a `batch_run_<ts>.json` written by the autonomous ticket batch,
`tickets{}` is the CANONICAL index of terminal states. `group_stop_reports`
(GSR) must never reference a ticket ABSENT from `tickets{}`.

Origin (F1, 2026-07-16): PREDICATE #3 (`contabilidad_completa`) self-declared
PASS while `tickets{}` was incomplete. An auditor re-deriving the universe
SOLELY from `tickets{}` loses any ticket that reached a terminal state only
via a GSR entry -- a silent false green. This check makes that gap explicit
and fails closed.

Scope is deliberately minimal: GSR-subset-of-tickets, nothing else. `tickets`
may be a dict keyed by ticket-id, a list of `{id, ...}` objects, or absent
(empty universe); the check tolerates all three shapes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _ticket_index(payload: dict[str, Any]) -> set[str]:
    """Before: parsed batch_run payload. During: normalize `tickets` (dict keyed
    by id, list of {id,...}, or absent) into a flat id set. After: set of ticket
    ids that count as present in the canonical index (empty if absent/malformed).
    """
    tickets = payload.get("tickets")
    if tickets is None:
        return set()
    if isinstance(tickets, dict):
        return {str(key) for key in tickets}
    if isinstance(tickets, list):
        ids: set[str] = set()
        for entry in tickets:
            if isinstance(entry, dict) and entry.get("id") is not None:
                ids.add(str(entry["id"]))
        return ids
    return set()


def check_batch_run_accounting(batch_run_path: Path) -> list[str]:
    """Before: `batch_run_path` points to an existing batch_run JSON report.
    During: builds the `tickets{}` index (dict|list|absent-tolerant) and scans
    `group_stop_reports` for any `ticket` value missing from that index.
    After: returns the sorted list of orphan ticket ids (empty list = clean).
    Raises OSError/json.JSONDecodeError if the file is unreadable or malformed
    JSON; the caller (CLI) is responsible for surfacing that as a hard failure.
    """
    payload = json.loads(Path(batch_run_path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {batch_run_path}")

    index = _ticket_index(payload)
    reports = payload.get("group_stop_reports") or []
    if not isinstance(reports, list):
        reports = []

    orphans: list[str] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        ticket = report.get("ticket")
        if ticket is None:
            continue
        ticket_str = str(ticket)
        if ticket_str not in index and ticket_str not in orphans:
            orphans.append(ticket_str)
    return orphans


def build_parser() -> argparse.ArgumentParser:
    """Before: none. During: define CLI. After: parser accepting a positional
    path or --file, both resolving to the same batch_run.json target."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "batch_run",
        nargs="?",
        default=None,
        help="Path to batch_run_<ts>.json (positional).",
    )
    parser.add_argument(
        "--file",
        dest="file",
        default=None,
        help="Path to batch_run_<ts>.json (alternative to the positional arg).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv optional. During: resolve target path, run the GSR-subset
    check. After: exit 0 if every GSR ticket is present in tickets{}; exit 1
    printing each orphan ticket by name otherwise; exit 2 on missing/invalid
    path or malformed JSON (usage error, not an accounting failure)."""
    args = build_parser().parse_args(argv)
    target = args.file or args.batch_run
    if not target:
        print("[check-batch-run-accounting] ERROR: no batch_run path given.")
        return 2

    path = Path(target)
    if not path.exists():
        print(f"[check-batch-run-accounting] ERROR: file not found: {path}")
        return 2

    try:
        orphans = check_batch_run_accounting(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[check-batch-run-accounting] ERROR: unreadable/invalid JSON: {exc}")
        return 2

    if orphans:
        print(
            "[check-batch-run-accounting] ERROR: orphan GSR ticket(s) absent "
            "from tickets{}:"
        )
        for ticket in orphans:
            print(f"    {ticket}")
        return 1

    print("[check-batch-run-accounting] OK: every GSR ticket is in tickets{}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
