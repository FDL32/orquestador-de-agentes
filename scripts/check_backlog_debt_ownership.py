#!/usr/bin/env python3
"""Barrier: declared-but-ownerless backlog debt must have a LIVE owner or be
grandfathered in a frozen baseline (WOT-2026-068y).

A backlog row's prose can declare a norm or a policy debt without binding it
to any ticket -- that declaration bounds the debt only while SOMEONE is still
tracking it. The sibling guard (`check_guard_wiring.py`) already catches this
exact disease for GUARDS (`known_unwired` + `wired_baseline`); this module is
the same mechanism applied to a DIFFERENT universe: backlog rows, registered
by hand in `scripts/backlog_debt_policy.yaml` (never auto-detected from prose
-- WOT-2026-068y's own census was a one-off MANUAL audit, not a live
classifier, and inventing a prose heuristic risks either a no-op guard or a
noisy false-positive one; populating the registry is a separate, explicit
triage step, same as `known_unwired` entries are).

Before:
    - `scripts/backlog_debt_policy.yaml` (`declared_debt: {ticket_id: owner}`,
      owner optional/absent for still-ownerless debt). Starts EMPTY on ship --
      see module docstring above.
    - `tests/fixtures/backlog_debt_baseline.yaml` (`debt_baseline: [ids]`), a
      FROZEN literal list. "New" is membership, never a date or a count
      (WOT-2026-024t).
    - A resolvable repo_destino whose live backlog says which tickets (debt
      rows AND owners) are still alive.

During:
    For every `declared_debt` entry:
    1. ROW liveness: is the debt-declaring ticket itself still a LIVE row? If
       not, the debt it declared is moot (the ticket closed) -- FAIL, the
       registry entry is stale and must be removed.
    2. If the row is live and has a valid owner (a ticket, or a reasoned
       `BY-DESIGN:` string): a ticket owner must ALSO still be live -- FAIL if
       archived. `BY-DESIGN:` never fails (no ticket to archive).
    3. If the row is live with NO valid owner: grandfathered (in the frozen
       baseline) -> WARN, visible but not blocking; NOT grandfathered -> FAIL,
       this is the actual barrier against NEW undeclared debt.

After:
    `debt_findings(policy, baseline, live)` returns `(fails, warns)`, pure and
    side-effect-free. `main()` wires it to a CLI. `prepush_check.py`'s
    `run_backlog_debt_ownership_check` (WOT-2026-068y DoD-f) imports these pure
    functions and wires them into the closeout, right where
    `run_guard_wiring_orphan_check` already runs the same kind of
    destino-dependent check (same reason stated there: no destino is
    resolvable from the portable pre-commit hook).

NON-GOALS (WOT-2026-068y, explicit): does not triage the backlog to populate
`declared_debt` (a human/future session decides which rows belong there, the
same way `known_unwired` entries are added by hand); does not touch
`guard_wiring_policy.yaml` or its loader; does not derive an owner from any
backlog cell -- an owner is ALWAYS an explicit registry value.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from scripts.check_guard_wiring import _BY_DESIGN, _TICKET, _resolve_destino_root
except ImportError:  # pragma: no cover - mirrors check_guard_wiring's own fallback
    from check_guard_wiring import (  # type: ignore[no-redef]
        _BY_DESIGN,
        _TICKET,
        _resolve_destino_root,
    )
try:
    from scripts.backlog_reconcile import _COL_TICKET, _extract_vista_rapida_rows
except ImportError:  # pragma: no cover
    from backlog_reconcile import (  # type: ignore[no-redef]
        _COL_TICKET,
        _extract_vista_rapida_rows,
    )

MOTOR_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = MOTOR_ROOT / "scripts" / "backlog_debt_policy.yaml"
BASELINE_PATH = MOTOR_ROOT / "tests" / "fixtures" / "backlog_debt_baseline.yaml"

_EXPECTED_COLS = 8


def _load_debt_policy(path: Path | None = None) -> dict[str, str]:
    """Read `declared_debt` (ticket_id -> owner, owner may be missing)."""
    path = path or POLICY_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return data.get("declared_debt") or {}


def _load_debt_baseline(path: Path | None = None) -> list[str]:
    """Read the FROZEN literal list of grandfathered ownerless-debt ids."""
    path = path or BASELINE_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return list(data.get("debt_baseline") or [])


def _strict_live_ticket_ids(dest_root: Path) -> tuple[set[str] | None, str | None]:
    """Own-row ticket IDs from the LIVE backlog's '## Vista rapida' table ONLY.

    Before: `dest_root` is a resolved repo_destino.
    During: reads `.agent/collaboration/backlog.md`, parses ONLY the Vista
        rapida table (`backlog_reconcile._extract_vista_rapida_rows`) and
        takes column `_COL_TICKET` (the row's OWN id) of every well-formed
        8-cell row. Deliberately STRICTER than `check_guard_wiring._live_owner_tickets`,
        which scrapes every ticket-shaped substring anywhere in the file
        (including a CITATION inside another row's prose) -- that laxer scrape
        counted 111 archived tickets as "live" because they were merely
        MENTIONED by a live row, not because they HAD a live row of their own
        (measured, WOT-2026-068y). Reading errors mirror `_live_owner_tickets`
        exactly (`errors="replace"` would turn an unreadable backlog into an
        indistinguishable empty set -- the same disease this ticket closes).
    After: `(set, None)`, or `(None, reason)` so the caller SKIPS explicitly
        instead of inventing orphans out of a parse failure. Never raises.
    """
    backlog = dest_root / ".agent" / "collaboration" / "backlog.md"
    try:
        content = backlog.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        return None, f"cannot read {backlog}: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{backlog} is not valid UTF-8 ({exc.reason}); refusing to guess"
    rows, err = _extract_vista_rapida_rows(content)
    if err:
        return None, f"{backlog}: {err}"
    ids = {
        cells[_COL_TICKET]
        for cells in rows
        if len(cells) == _EXPECTED_COLS and _TICKET.match(cells[_COL_TICKET])
    }
    if not ids:
        return None, f"{backlog}: Vista rapida table has no canonical ticket id"
    return ids, None


def debt_findings(
    policy: dict[str, str], baseline: list[str], live: set[str]
) -> tuple[list[str], list[str]]:
    """Classify every `declared_debt` entry into (fails, warns).

    Before: `policy` is `{ticket_id: owner}` (owner may be `""`/missing,
        meaning still ownerless); `baseline` is the frozen grandfather list;
        `live` is the destino's LIVE ticket ids (`_strict_live_ticket_ids`).
    During: per entry, row-liveness is checked FIRST (a debt row that closed
        makes the whole entry moot, regardless of its owner) -- then, only for
        still-live rows, the owner is checked (a ticket owner must be live,
        BY-DESIGN never fails) or, if ownerless, the entry is graded by
        baseline membership (WOT-2026-068y DoD b/c/d).
    After: `(fails, warns)`, both sorted, pure and side-effect-free. `fails`
        is the actual barrier (new undeclared debt, a dead owner, or a
        grandfathered entry whose row itself closed); `warns` is visible but
        never blocks (a baseline entry that is still, honestly, ownerless).
        Never raises.
    """
    baseline_set = set(baseline)
    fails: list[str] = []
    warns: list[str] = []
    for ticket_id, owner in sorted(policy.items()):
        if ticket_id not in live:
            fails.append(
                f"{ticket_id}: registry entry's own row is no longer live "
                "(archived/closed) -- stale, remove it from backlog_debt_policy.yaml"
            )
            continue
        owner_str = str(owner) if owner else ""
        if owner_str.startswith(_BY_DESIGN):
            continue
        if _TICKET.match(owner_str):
            if owner_str not in live:
                fails.append(f"{ticket_id}: owner {owner_str} is archived (stale)")
            continue
        # no valid owner declared
        if ticket_id in baseline_set:
            warns.append(
                f"{ticket_id}: declared debt, no owner yet (grandfathered baseline)"
            )
        else:
            fails.append(
                f"{ticket_id}: declared debt, no owner, NOT in the frozen baseline"
            )
    return sorted(fails), sorted(warns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "--project-root", default=None, help="repo_destino (backlog owner)"
    )
    parser.add_argument(
        "--workspace-root", default=None, help="workspace holding the link"
    )
    args = parser.parse_args(argv)

    dest_root, dest_err = _resolve_destino_root(args.project_root, args.workspace_root)
    if dest_root is None:
        print(f"[backlog-debt-ownership] SKIP: {dest_err}")
        return 0

    live, err = _strict_live_ticket_ids(dest_root)
    if live is None:
        print(f"[backlog-debt-ownership] SKIP: {err}")
        return 0

    policy = _load_debt_policy()
    baseline = _load_debt_baseline()
    fails, warns = debt_findings(policy, baseline, live)
    for w in warns:
        print(f"[backlog-debt-ownership] WARN: {w}")
    if fails:
        for f in fails:
            print(f"[backlog-debt-ownership] FAIL: {f}")
        print(f"[backlog-debt-ownership] VEREDICTO: FALLO ({len(fails)} entrada(s))")
        return 1
    print(
        f"[backlog-debt-ownership] OK: {len(policy)} entrada(s), todas con dueno o baseline"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
