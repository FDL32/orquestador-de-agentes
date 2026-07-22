#!/usr/bin/env python3
"""WOT-2026-012b / WOT-2026-023o: fail-closed gate for the collaboration
backlog + bus-projection contract.

Turns the parseable live-queue contract that WOT-2026-012a fixed into an
executable barrier. Validates the active "Vista rapida" table of
repo_destino/.agent/collaboration/backlog.md (structure + closed Status /
Reactivation vocabulary) AND (WOT-2026-023o) the bus projection: STATE.md's
ACTIVE_TICKET must not be a ghost (no row in backlog.md nor the archive) nor an
archived ticket still declared active by a non-terminal STATUS.

Before: project_root MUST be given via --project-root or AGENT_PROJECT_ROOT.
    Unlike runtime.project_root.resolve_project_root(), this gate does NOT fall
    back to __file__ derivation: a backlog read relative to the motor cwd would
    be the wrong file (the motor seed, not the destino queue). Missing root is a
    fail-closed error, not a pass-open.
During: parse the markdown table under the "## Vista rapida" header (never HTML
    comments or free prose). For each live row validate: 8 columns, Status in the
    closed vocabulary, and a Reactivation value consistent with the Status.
    Validate that every "### WOT-..." / "### WT-..." ficha header is well formed.
After: exit 0 when the contract holds; exit non-zero with a diagnostic per
    violation otherwise. No mutation, ever.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


# WOT-2026-023o: terminality authority. STATE.md's STATUS uses the BUS vocabulary
# (TicketState.value, UPPERCASE) -- distinct from the backlog row vocabulary
# (LIVE_STATES, lowercase). NON_TERMINAL_STATES is the single source of truth
# (bus.state_machine; _is_state_terminal delegates to it). Terminal, by complement,
# is {COMPLETED, BLOCKED_FINAL, SUPERSEDED, UNKNOWN}. We import it rather than
# hardcode a list so this gate never drifts from the machine it audits.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bus.state_machine import NON_TERMINAL_STATES, TicketState


# WOT-2026-012a closed vocabulary for the LIVE queue. Terminal states
# (completed/done/closed/absorbed) must NOT appear here: they belong in history.
LIVE_STATES = (
    "pending",
    "blocked",
    "deferred",
    "ready-for-review",
    "awaiting-manager",
    "completed-partial",
)

# States that REQUIRE a structured Reactivation trigger (not "-").
REACTIVATION_REQUIRED = ("blocked", "deferred", "completed-partial")

# Structured Reactivation trigger prefixes (012a contract). "-" means "no
# trigger" and is only valid for active states without one.
REACTIVATION_PREFIXES = ("condition:", "commit:", "external:")
# A bare ticket id (WOT-YYYY-NNNx / WT-...) is also a valid trigger.
_TICKET_TRIGGER_RE = re.compile(r"^(?:WOT|WP|WT)-\d{4}-\w+$")

# Vocabulary that is NEVER a valid structured trigger (vague prose).
_VAGUE_REACTIVATION = {"n/a", "na", "pendiente", "pending", "tbd", "todo", "?"}

_VISTA_RAPIDA_HEADER = "## Vista rapida"
_TABLE_HEADER_COLS = (
    "Prioridad",
    "Ticket",
    "Titulo",
    "Scope",
    "Estado",
    "Depende de",
    "Origen",
    "Reactivation",
)
_FICHA_RE = re.compile(r"^### (WOT|WP|WT)-\d{4}-\w+(?:\s+-\s+.+)?$")

# WOT-2026-027t: a live-queue ticket row is a markdown table row whose SECOND
# cell (idx 2 after the leading empty split token) is a bare ticket id. The live
# table fragmented once (35 rows drifted under '## Fichas detalladas', invisible
# to _extract_active_table): the guard now fails closed if any such row appears
# OUTSIDE the Vista rapida table body, so the fragmentation cannot silently
# reappear. Cell-based (idx 2), never substring: a prose cell can cite a ticket
# id (e.g. 'Depende de'), which must NOT match.
_TICKET_ROW_CELL_RE = re.compile(r"^(?:WOT|WP|WT)-\d{4}-\w+$")

# WOT-2026-013j: a detailed ficha must NOT re-declare Files Likely Touched. The
# canonical FLT lives ONLY in the frozen contract (ticket_contracts.md) and then
# work_plan.md; a ficha that re-declares it drifts and forces manual packet
# reconcile (recurring in 013h/013i). We block a DECLARATIVE FLT bullet -- a list
# key like ``- **Files Likely Touched...:**`` -- not a prose mention of the term
# inside another bullet (e.g. ``- **Problema:** ... `Files Likely Touched` ...``),
# which only references the concept and is allowed. The ficha may summarize or
# point to the contract; it may not own the FLT.
_FLT_DECLARATION_RE = re.compile(r"^\s*[-*]\s*\*\*Files Likely Touched", re.IGNORECASE)


def resolve_destino_root(cli_value: str | None) -> tuple[Path | None, str | None]:
    """Resolve the destino root strictly. Returns (root, error).

    Precedence: --project-root, then AGENT_PROJECT_ROOT. NO __file__ fallback:
    a missing root is fail-closed (WOT-2026-012b binary criterion).
    """
    raw = (cli_value or "").strip() or os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if not raw:
        return None, (
            "fail-closed: no project root. Pass --project-root <repo_destino> or "
            "set AGENT_PROJECT_ROOT. This gate never reads backlog relative to cwd."
        )
    root = Path(raw).resolve()
    if not root.exists():
        return None, f"project root does not exist: {root}"
    return root, None


def _extract_active_table(content: str) -> tuple[list[str], str | None]:
    """Return the data rows of the table under '## Vista rapida'.

    Reads ONLY that table; stops at the next blank line after the table or the
    next header. Never consults HTML comments or prose.
    """
    lines = content.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip() == _VISTA_RAPIDA_HEADER
        )
    except StopIteration:
        return [], f"missing '{_VISTA_RAPIDA_HEADER}' section"

    # Find the table header row (starts with '| Prioridad').
    header_idx = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):  # next section before any table
            break
        if stripped.startswith("| Prioridad"):
            header_idx = i
            break
    if header_idx is None:
        return [], "no table header found under 'Vista rapida'"

    # Validate header columns.
    header_cells = [c.strip() for c in lines[header_idx].strip().strip("|").split("|")]
    if header_cells != list(_TABLE_HEADER_COLS):
        return [], (
            f"table header columns mismatch: expected {list(_TABLE_HEADER_COLS)}, "
            f"got {header_cells}"
        )

    # Data rows start two lines after the header (skip the |---|---| separator).
    rows: list[str] = []
    for i in range(header_idx + 2, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("## "):
            break
        if stripped.startswith("|"):
            rows.append(stripped)
    return rows, None


def _is_ticket_row(stripped: str) -> bool:
    """True iff ``stripped`` is a table row whose id cell (idx 2) is a bare id.

    Cell-based, never substring (the trap this guard exists for): a later cell
    such as 'Depende de' can hold another ticket's id as a dependency, and prose
    cells cite ids in running text; only a row whose SECOND cell IS a ticket id
    counts as a live-queue ticket row.
    """
    if not stripped.startswith("| "):
        return False
    cells = stripped.split("|")
    if len(cells) <= 3:
        return False
    return bool(_TICKET_ROW_CELL_RE.match(cells[2].strip()))


def _vista_rapida_body_span(lines: list[str]) -> range:
    """Return the line-index range of the Vista rapida table BODY (data rows).

    The span starts two lines after the '| Prioridad' header (skipping the
    |---| separator) and ends at the terminating blank line or next '## ' header
    -- exactly _extract_active_table's stop rule. Returns an empty range when the
    section or header is absent (those are reported by _extract_active_table).
    """
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip() == _VISTA_RAPIDA_HEADER
        )
    except StopIteration:
        return range(0)

    header_idx = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("| Prioridad"):
            header_idx = i
            break
    if header_idx is None:
        return range(0)

    body_start = header_idx + 2
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("## "):
            body_end = i
            break
    return range(body_start, body_end)


def _ticket_rows_outside_table(content: str) -> list[str]:
    """WOT-2026-027t: fail closed on any ticket row OUTSIDE the Vista rapida table.

    The live table fragmented once: 35 ticket rows drifted under a later section
    ('## Fichas detalladas'), where _extract_active_table never sees them, so the
    contract 'held' (exit 0) over an invisible half of the queue. This guard uses
    the Vista rapida table body's line span and reports every ticket row that
    lives elsewhere in the file. It does NOT re-parse those rows (that is
    _extract_active_table's job for the rows it legitimately owns); it only proves
    the queue is not fragmented, so the canonical table stays the single
    parseable source.
    """
    lines = content.splitlines()
    in_table = _vista_rapida_body_span(lines)
    errors: list[str] = []
    for i, line in enumerate(lines):
        if i in in_table:
            continue
        stripped = line.strip()
        if _is_ticket_row(stripped):
            ticket = stripped.split("|")[2].strip()
            errors.append(
                f"{ticket}: ticket row at line {i + 1} is OUTSIDE the "
                f"'{_VISTA_RAPIDA_HEADER}' table. The live queue must live in that "
                f"single table (fragmentation trap, WOT-2026-027t). Move the row "
                f"into the Vista rapida table."
            )
    return errors


def _validate_reactivation(status: str, reactivation: str) -> str | None:
    """Return an error string for an invalid (status, reactivation) pair."""
    react = reactivation.strip()
    if status in REACTIVATION_REQUIRED:
        if react == "-" or not react:
            return f"status '{status}' requires a structured Reactivation, got '-'"
        if react.lower() in _VAGUE_REACTIVATION:
            return f"vague Reactivation '{react}' for status '{status}'"
        if react.startswith(REACTIVATION_PREFIXES) or _TICKET_TRIGGER_RE.match(react):
            return None
        return (
            f"Reactivation '{react}' for status '{status}' is not structured "
            f"(expected one of {REACTIVATION_PREFIXES} or a ticket id)"
        )
    # Active states without a required trigger: '-' is fine; a structured
    # trigger is also allowed, but vague prose is not.
    if react and react != "-" and react.lower() in _VAGUE_REACTIVATION:
        return f"vague Reactivation '{react}' for status '{status}'"
    return None


def validate_backlog(backlog_path: Path) -> list[str]:
    """Return a list of contract violations (empty == valid)."""
    if not backlog_path.exists():
        return [f"backlog not found: {backlog_path}"]
    content = backlog_path.read_text(encoding="utf-8-sig")

    errors: list[str] = []
    rows, table_error = _extract_active_table(content)
    if table_error:
        return [table_error]
    if not rows:
        return ["active 'Vista rapida' table has no rows"]

    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) != len(_TABLE_HEADER_COLS):
            errors.append(f"row has {len(cells)} columns, expected 8: {row}")
            continue
        ticket, status, reactivation = cells[1], cells[4], cells[7]
        if status not in LIVE_STATES:
            errors.append(
                f"{ticket}: status '{status}' not in live vocabulary {LIVE_STATES}"
            )
        react_err = _validate_reactivation(status, reactivation)
        if react_err:
            errors.append(f"{ticket}: {react_err}")

    errors.extend(_ticket_rows_outside_table(content))
    errors.extend(_check_ficha_bodies(content))
    return errors


def _check_ficha_bodies(content: str) -> list[str]:
    """Validate ficha headers and that no ficha body re-declares FLT.

    WOT-2026-012b checked only that ``### WOT-...`` headers are well formed.
    WOT-2026-013j adds: a detailed ficha must not re-declare Files Likely Touched
    (owned by the frozen contract, never the backlog body). Tracks the current
    ficha so a violation names its owner ticket.
    """
    errors: list[str] = []
    current_ficha = "<before any ficha>"
    for line in content.splitlines():
        is_ticket_ficha = line.startswith("### ") and (
            "WOT-" in line or "WT-" in line or "WP-" in line
        )
        if is_ticket_ficha:
            current_ficha = line.rstrip().lstrip("# ").strip()
            if not _FICHA_RE.match(line.rstrip()):
                errors.append(f"malformed ficha header: {line.rstrip()!r}")
            continue
        if _FLT_DECLARATION_RE.match(line):
            errors.append(
                f"{current_ficha}: ficha re-declares 'Files Likely Touched' "
                f"({line.strip()!r}). The FLT is owned by the frozen contract "
                "(ticket_contracts.md/work_plan.md), not the backlog. Replace the "
                "declarative bullet with a reference to the contract."
            )
    return errors


# ---------------------------------------------------------------------------
# WOT-2026-023o: the bus projection must not declare an ACTIVE_TICKET that is a
# ghost (no row anywhere) or that is ARCHIVED while its STATUS is still active.
# The motivating incident: STATE.md said ACTIVE_TICKET WOT-2026-022i /
# READY_FOR_REVIEW over a ticket already archived as completed, and no gate saw
# it. A COMPLETED/terminal STATUS pointing only to the archive is the normal
# post-close residual and passes.
# ---------------------------------------------------------------------------

_ACTIVE_TICKET_RE = re.compile(r"^ACTIVE_TICKET:\s*(\S+)", re.MULTILINE)
_STATUS_RE = re.compile(r"^STATUS:\s*(\S+)", re.MULTILINE)


def _read_active_ticket(root: Path) -> tuple[str | None, str | None]:
    """Return (active_ticket, status) from STATE.md, or (None, None) if absent.

    STATE.md is the bus projection (written by bus/supervisor.py). Missing file
    or missing ACTIVE_TICKET means the check does not apply -- it never invents a
    violation from an absent projection.
    """
    state_path = root / ".agent" / "collaboration" / "STATE.md"
    if not state_path.exists():
        return None, None
    content = state_path.read_text(encoding="utf-8-sig")
    m = _ACTIVE_TICKET_RE.search(content)
    if not m:
        return None, None
    ticket = m.group(1).strip()
    status_m = _STATUS_RE.search(content)
    status = status_m.group(1).strip() if status_m else None
    return (ticket or None), status


def _status_is_non_terminal(status: str | None) -> bool:
    """True only for a KNOWN active (non-terminal) bus state.

    Terminality authority = bus.state_machine.NON_TERMINAL_STATES. An unknown or
    unparseable STATUS is NOT treated as non-terminal: this gate does not flag a
    malformed STATUS (a different concern); the ghost check still covers a missing
    row regardless of STATUS.
    """
    if not status:
        return False
    try:
        return TicketState(status) in NON_TERMINAL_STATES
    except ValueError:
        return False


def _ticket_has_row(ticket_id: str, path: Path) -> bool:
    """True if a markdown table row in ``path`` carries ``ticket_id`` as its ID.

    LAYOUT-ROBUST (WOT-2026-023o, the trap this ticket exists for): the ID lives
    in DIFFERENT columns across surfaces -- cell[1] in backlog.md (after the
    Prioridad column) and cell[0] in _archive/backlog_done.md (no Prioridad), plus
    the archive has a later ``| Ticket | Estado | Nota |`` section. In every known
    layout the ID is the FIRST or SECOND cell, so we match those two by EXACT token
    equality. We deliberately do NOT scan every cell: a later cell (e.g. 'Depende
    de') can hold another ticket's id as a dependency, which would false-match.
    """
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        head = cells[:2]  # ID is cell[0] (archive) or cell[1] (live backlog)
        if ticket_id in head:
            return True
    return False


def validate_active_ticket_state(root: Path) -> list[str]:
    """Return violations for STATE.md's ACTIVE_TICKET vs the scheduling surfaces."""
    ticket, status = _read_active_ticket(root)
    if not ticket:
        return []  # no projection to audit

    collab = root / ".agent" / "collaboration"
    in_live = _ticket_has_row(ticket, collab / "backlog.md")
    in_archive = _ticket_has_row(ticket, collab / "_archive" / "backlog_done.md")

    if not in_live and not in_archive:
        return [
            f"STATE.md ACTIVE_TICKET '{ticket}' (STATUS {status}) has NO row in "
            f"backlog.md nor _archive/backlog_done.md -- a ghost the bus projection "
            f"declares active that no scheduling surface knows."
        ]
    if not in_live and in_archive and _status_is_non_terminal(status):
        return [
            f"STATE.md ACTIVE_TICKET '{ticket}' has a NON-terminal STATUS "
            f"('{status}') but only exists in the archive (terminal history) -- the "
            f"bus projection declares active/in-progress a ticket already archived "
            f"(the WOT-2026-022i drift). Reconcile STATE.md or archive the row's real "
            f"live state."
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed gate for the live backlog contract (WOT-2026-012b)."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino root (or set AGENT_PROJECT_ROOT). No cwd fallback.",
    )
    args = parser.parse_args(argv)

    root, root_error = resolve_destino_root(args.project_root)
    if root_error:
        print(f"[backlog-contract] {root_error}", file=sys.stderr)
        return 2

    backlog = root / ".agent" / "collaboration" / "backlog.md"
    violations = validate_backlog(backlog)
    # WOT-2026-023o: also audit the bus projection (STATE.md ACTIVE_TICKET).
    violations = violations + validate_active_ticket_state(root)
    if violations:
        print(
            f"[backlog-contract] {len(violations)} violation(s) in {backlog}:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(f"[backlog-contract] OK: live queue contract holds in {backlog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
