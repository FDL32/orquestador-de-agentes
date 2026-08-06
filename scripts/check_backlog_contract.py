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
from collections import Counter
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

# WOT-2026-027t: a live-queue ticket row is a Prioridad-led markdown table row
# whose Ticket cell (RAW split index 2: empty token, Prioridad, Ticket) is a bare
# ticket id. The live table fragmented once (35 rows drifted under '## Fichas
# detalladas', invisible
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
# WOT-2026-043t: ticket id SEARCHED inside a line (the constants above are anchored
# with ^...$ for whole-cell matches and cannot find an id embedded in prose).
_TICKET_ID_IN_TEXT_RE = re.compile(r"\b((?:WOT|WP|WT)-\d{4}-\w+)\b")


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
    """True iff ``stripped`` is a Prioridad-led table row whose id cell is a bare id.

    The id lives at RAW split index 2: ``"| Alta | WOT-... |".split("|")`` yields
    ``['', ' Alta ', ' WOT-... ', ...]`` -- index 0 is the empty token before the
    first pipe, index 1 is the Prioridad column, index 2 is the Ticket column.
    Cell-based, never substring (the trap this guard exists for): a later cell
    such as 'Depende de' can hold another ticket's id as a dependency, and prose
    cells cite ids in running text; only a row whose Ticket cell IS a ticket id
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
    # Una tabla SIN filas es el estado terminal legitimo de un proyecto que
    # acabo su cola, no una violacion: `--session-close` la deja asi a
    # proposito. Lo que si es defecto -- seccion ausente o ilegible -- ya lo
    # devuelve `_extract_active_table` como `table_error` mas arriba, asi que
    # exigir >=1 fila solo prohibia terminar (medido en el cierre real del
    # destino LEA, 2026-08-02: rc=1 por haber cumplido el objetivo).

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
    errors.extend(_check_ficha_pointers(content, rows))
    return errors


def _check_ficha_pointers(content: str, rows: list[str]) -> list[str]:
    """A row that DELEGATES its detail to a ficha must have that ficha reachable.

    WOT-2026-043t/fase-3. Compressing a fat row to "pointer + invariant criterion"
    turns the pointer into part of the CONTRACT, not a convenience: if the ficha is
    deleted, renamed or never created, the row keeps a criterion it can no longer
    justify and NOTHING notices -- the row still parses, so every other check here
    stays green. Both adversarial lenses of loop L4500 raised this independently,
    and it is the same family as WOT-2026-044p: a guard that reports OK about a
    surface it never looked at.

    Detects the delegation by the literal the compression emits (``ver ficha`` +
    the row's own ticket id), so a row that merely MENTIONS another ticket's ficha
    is not dragged in.

    Before: ``content`` is the whole backlog; ``rows`` the live-table rows.
    During: pure string parsing -- collects ``### <TICKET>`` headers, then checks
        every delegating row against them. No disk, no git.
    After: one error per row whose ficha is missing or duplicated.
    """
    errors: list[str] = []
    headers: dict[str, int] = {}
    for line in content.splitlines():
        if not line.startswith("### "):
            continue
        m = _TICKET_ID_IN_TEXT_RE.search(line)
        if m:
            headers[m.group(1)] = headers.get(m.group(1), 0) + 1

    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) != len(_TABLE_HEADER_COLS):
            continue
        ticket_cell, desc = cells[1], cells[2]
        m = _TICKET_ID_IN_TEXT_RE.search(ticket_cell)
        if not m:
            continue
        ticket = m.group(1)
        # Only a row delegating ITS OWN detail counts; a row citing someone
        # else's ficha is not making a claim about its own completeness.
        if "ver ficha" not in desc or ticket not in desc:
            continue
        n = headers.get(ticket, 0)
        if n == 0:
            errors.append(
                f"{ticket}: the row delegates its detail to ficha '### {ticket}' "
                "but no such ficha exists -- the pointer is dangling, so the "
                "criterion it defers to is unreachable"
            )
        elif n > 1:
            errors.append(
                f"{ticket}: {n} fichas '### {ticket}' exist -- an ambiguous "
                "pointer cannot say which one carries the evidence"
            )
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

# Valores que STATE.md usa para decir "no hay ticket activo". El motor escribe
# `-` al cerrar sesion; los demas son formas equivalentes que puede dejar una
# proyeccion o una plantilla. Ninguno es un identificador de ticket.
_NO_ACTIVE_TICKET_SENTINELS = frozenset({"-", "--", "none", "None", "NONE", "N/A"})

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
    # `-` es el CENTINELA de "ninguno" que escribe el propio motor al cerrar
    # sesion (`.agent/agent_controller.py`, "tras cerrar la sesion ya no hay
    # ticket activo"). El regex captura `\S+`, asi que sin esta excepcion se
    # leia como un ticket llamado "-" y se denunciaba como fantasma: un
    # cierre correcto producia rc=1 por su propia escritura (medido en el
    # destino LEA, 2026-08-02). Tratarlo como ausencia devuelve el par
    # (None, None), que es justo el contrato de "el check no aplica".
    if ticket in _NO_ACTIVE_TICKET_SENTINELS:
        return None, None
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


# ---------------------------------------------------------------------------
# WOT-2026-027i: an id that appears BOTH as a live-queue row and an archived row
# (or TWICE inside the archive) lies in both directions -- the reader of the queue
# thinks it is pending, the reader of the archive thinks it is closed. Cell-based
# (the id is the FIRST or SECOND cell across every known layout, same convention
# as _ticket_has_row), never substring: a 'Depende de' cell cites other ids.
# ---------------------------------------------------------------------------


def _row_ticket_id(stripped: str) -> str | None:
    """Return the ticket id of a Prioridad-led queue row, or None otherwise.

    SCOPE (WOT-2026-027i, matched to its authoritative premise probe): a
    scheduling-surface ticket row is Prioridad-led -- ``| Prioridad | Ticket |
    ...`` -- so the id is at RAW split index 2 (index 0 is the empty token before
    the first pipe, index 1 is Prioridad). This is the SAME position 027t's
    _is_ticket_row uses, and it deliberately does NOT match:
      - the archive's compact ``| Ticket | Estado | Nota |`` closure-log rows (id
        at raw index 1) -- those are terminal notes, not queue rows, and a ticket
        legitimately appears in BOTH a closure-log and an archived queue-snapshot;
      - CREDITS / skills reference rows that merely start with a ticket id;
      - a later 'Depende de' cell citing another id (never at index 2).
    Cell-based, never substring.
    """
    if not stripped.startswith("| "):
        return None
    cells = stripped.split("|")
    if len(cells) <= 3:
        return None
    candidate = cells[2].strip()
    return candidate if _TICKET_ROW_CELL_RE.match(candidate) else None


def _ticket_row_ids(path: Path) -> list[str]:
    """Every ticket id that has a table row in ``path`` (WITH multiplicity)."""
    if not path.exists():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        tid = _row_ticket_id(line.strip())
        if tid:
            ids.append(tid)
    return ids


def validate_live_archive_integrity(root: Path) -> list[str]:
    """Return violations for duplicate ids across / within the scheduling surfaces.

    (a) An id present as a LIVE row AND an ARCHIVE row: it lies in both directions.
    (b) An id present TWICE inside the archive: the archive contradicts itself
        (measured: WOT-2026-011b with `pending` and `completed` rows at once).

    DECLARED SCOPE (027i governance loop): both checks count only Prioridad-led
    rows (id at raw index 2), never the archive's compact `| Ticket | Estado |`
    closure-log rows (id at index 1). This is deliberate: a ticket MUST appear in
    a closure-log to be closed, and it legitimately also appears in an archived
    Prioridad-led snapshot -- counting the compact row would turn that normal
    layering into a false positive. Consequence (verified against the real
    archive: 0 compact-only internal dups today): a contradiction that existed
    ONLY between two compact rows would be out of scope. The motivating bug
    (011b) and every real contradiction are Prioridad-led, which this covers.
    """
    collab = root / ".agent" / "collaboration"
    live_ids = set(_ticket_row_ids(collab / "backlog.md"))
    archive_all = _ticket_row_ids(collab / "_archive" / "backlog_done.md")
    archive_ids = set(archive_all)

    errors: list[str] = [
        f"{tid}: appears BOTH as a live-queue row in backlog.md AND an archived "
        f"row in _archive/backlog_done.md -- it lies in both directions "
        f"(WOT-2026-027i). Keep exactly one: remove the archived row if the "
        f"ticket is still live, or the live row if it is closed."
        for tid in sorted(live_ids & archive_ids)
    ]
    errors.extend(
        f"{tid}: appears {n} times inside _archive/backlog_done.md -- the "
        f"archive contradicts itself (WOT-2026-027i). Keep exactly one "
        f"archived row for the ticket."
        for tid, n in sorted(Counter(archive_all).items())
        if n > 1
    )
    return errors


# ---------------------------------------------------------------------------
# WOT-2026-026z: a Prioridad-led row in _archive/backlog_done.md must have the
# canonical 8-cell arity. A row broken by an UNESCAPED pipe in its text gains
# extra cells and its terminal commit: cell drifts OUT of the table -- the row is
# archived WITHOUT its landing evidence, the exact datum the archive exists to
# keep. The archive legitimately mixes arities (compact | Ticket | Estado | Nota |
# sections and other schemas), so the guard scopes ONLY to Prioridad-led rows
# (id at raw index 2, same position as _row_ticket_id). It does NOT demand arity
# of the historical debt: the 17 known-broken rows measured 2026-07-21 are a
# DECLARED baseline; a NEW Prioridad-led row with arity != 8 fails naming it.
# The fix for a break is to REMOVE the pipe from the cell text, never to escape
# it: the real consumer (check_backlog_commits_landed) splits on the RAW pipe.
# ---------------------------------------------------------------------------

# Declared legacy baseline (CENSUS anchored 2026-07-21/23, WOT-2026-026z): every
# Prioridad-led archive row that does NOT have the canonical 8-cell arity TODAY.
# The archive census measured: 255 rows at 8 cells (the norm), 3 at 7 cells (an
# older pre-Reactivation 7-column section: 250c/008e/008j), and 17 broken by an
# unescaped pipe (15 at 9 cells, 2 at 10). All 20 non-8 rows are anchored here as
# declared debt -- evidence, not criterion (WOT-2026-024t) -- so the guard NEVER
# demands arity of history. Any ticket id NOT in this mapping must archive as a
# clean 8-cell row. A future cleanup may repair a row and remove its entry;
# nothing may ADD an entry to silence a FRESH break (pinned by
# test_archive_arity_baseline_is_pinned).
#
# The exemption is anchored to the PAIR (id, measured arity), NOT to the id alone
# (governance loop 2026-07-23). An id-only frozenset exempted a baseline ticket
# FOREVER: replacing a legacy row with a brand-new broken one under the same id
# passed the guard silently (measured: a fresh 9-cell row for WOT-2026-014a
# returned 0 violations). Keyed by arity, a baseline id is exempt ONLY at the
# arity actually censused; any OTHER arity for that same id is a fresh break and
# fails like any other row.
_ARCHIVE_ARITY_LEGACY_BASELINE: dict[str, int] = {
    # 17 pipe-break rows: 15 at 9 cells, 2 at 10.
    "WOT-2026-004b": 10,
    "WOT-2026-010h": 10,
    "WOT-2026-013b": 9,
    "WOT-2026-011i": 9,
    "WOT-2026-011h": 9,
    "WOT-2026-013c": 9,
    "WOT-2026-014c": 9,
    "WOT-2026-014a": 9,
    "WOT-2026-014b": 9,
    "WOT-2026-014d": 9,
    "WOT-2026-014e": 9,
    "WOT-2026-014f": 9,
    "WOT-2026-014g": 9,
    "WOT-2026-014h": 9,
    "WOT-2026-014i": 9,
    "WOT-2026-015n": 9,
    "WOT-2026-021i": 9,
    # 3 rows of the older 7-column (pre-Reactivation) archive section.
    "WT-2026-250c": 7,
    "WOT-2026-008e": 7,
    "WOT-2026-008j": 7,
}


def validate_archive_row_arity(root: Path) -> list[str]:
    """Return violations for NEW broken Prioridad-led rows in the archive (026z).

    CANONICAL arity is 8 (the current schema). The archive's non-8 rows -- 3 of an
    older 7-column section and 17 broken by an unescaped pipe -- are anchored in
    _ARCHIVE_ARITY_LEGACY_BASELINE as DECLARED debt (the DoD's "ancla el censo
    actual como baseline declarada"; the guard mira lo que se AÑADE). A NEW
    Prioridad-led row -- any ticket id not in that baseline -- must have exactly 8
    cells; a mismatch is a fresh break, almost always an unescaped pipe pushing the
    terminal commit: cell out of the table. The fix is always to REMOVE the pipe
    (the real consumer splits on the raw pipe), never to escape it.

    The baseline exempts the PAIR (id, censused arity), not the id: a baseline
    ticket whose row appears at ANY other arity is a fresh break and fails.

    DECLARED SCOPE: a pipe break located BEFORE the Ticket cell shifts the id out
    of raw index 2, so _row_ticket_id returns None and the row falls outside this
    guard entirely. Verified against the real archive today (20/20 censused rows
    are detected), but it is a structural blind spot, not full coverage.
    """
    archive = root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    if not archive.exists():
        return []
    # DECLARED COUPLING (027i/026z governance loop): the archive's Prioridad-led
    # 8-column sections carry the SAME columns as the live Vista rapida table, so
    # the canonical arity reuses _TABLE_HEADER_COLS. Verified identical today. If
    # the archive schema ever diverges from the live table, derive `want` from the
    # archive's own header instead -- this reuse assumes they stay in lockstep.
    want = len(_TABLE_HEADER_COLS)
    errors: list[str] = []
    for line in archive.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        tid = _row_ticket_id(stripped)
        if tid is None:
            continue
        n = len(stripped.strip("|").split("|"))
        # Exempt by the PAIR (id, censused arity), never by id alone: a baseline
        # ticket is forgiven ONLY at the arity actually measured, so a fresh break
        # under a baseline id still fails.
        if _ARCHIVE_ARITY_LEGACY_BASELINE.get(tid) == n:
            continue
        if n != want:
            errors.append(
                f"{tid}: archived row has {n} cells, expected {want} "
                f"(WOT-2026-026z). Almost certainly an unescaped '|' in the row "
                f"text pushed its terminal 'commit:' cell out of the table. REMOVE "
                f"the pipe from the cell text (do NOT escape it: the real consumer "
                f"splits on the raw pipe)."
            )
    return errors


# ---------------------------------------------------------------------------
# WOT-2026-026t (fase estado): una fila ARCHIVADA con estado NO-TERMINAL es
# trabajo pendiente que desaparecio de la cola viva. Nadie la ve: este gate
# validaba la cola viva y no el archivo, asi que la transicion
# `pending -> archivado` no tenia barrera.
#
# MEDIDO 2026-08-04 sobre el archivo real: 18 filas con estado NO-TERMINAL
# archivadas y AUSENTES de la cola viva. Ninguna era trabajo perdido -- 17 tenian
# commit ancestro de HEAD que las cerraba y `015i` habia hecho su trabajo sin citar
# el id -- pero durante semanas fueron INVISIBLES en las dos superficies: la cola no
# las lista y el archivo las declara pendientes. La fuga es de ETIQUETADO, y esta
# barrera la cierra por construccion.
#
# Las 18 salieron en DOS tandas, y la segunda solo aparecio tras una pasada
# adversarial externa: las 9 primeras eran filas de 8 celdas; las otras 9 estan
# ROTAS por un pipe sin escapar (arity 9) o pertenecen a la seccion historica de 7
# columnas, y la primera version de este guard las SALTABA por heredar el scope de
# `validate_archive_row_arity`. Reportaba OK sobre una superficie que no miraba --
# el mismo falso verde que viene a cerrar. De ahi que la lectura del estado sea
# ARITY-INDEPENDIENTE (ver `_archive_row_state`).
#
# VOCABULARIO TERMINAL: lista blanca, NO complemento de LIVE_STATES.
#
# La primera version derivaba "terminal" por COMPLEMENTO ("todo lo que no sea
# LIVE_STATES") con el argumento de que enumerar caducaria. Un probe propio la
# REFUTO antes de commitear: inyectada la errata `competed` (typo de `completed`)
# en una fila Prioridad-led, el gate devolvia exit 0 -- una errata tipografica
# pasaba como estado terminal valido, que es justo el falso verde que este guard
# viene a cerrar.
#
# El censo del archivo real desmonta el argumento del complemento: hay SEIS
# etiquetas terminales distintas y cuatro concentran 269 de 271 filas
# (`completed` 250, `done` 15, `absorbed` 2, `superseded` 2, mas dos formas de un
# solo uso). El vocabulario ES enumerable, asi que la lista blanca no caduca en la
# practica; y si algun dia hace falta una etiqueta nueva, anadirla aqui es una
# linea con dueno -- muy preferible a que cualquier cadena arbitraria valga.
#
# Las dos formas de un solo uso quedan como BASELINE DECLARADO (evidencia fechada,
# no criterio -- WOT-2026-024t), no como vocabulario recomendado: se aceptan porque
# existen en la historia, no porque debieran repetirse.
# ---------------------------------------------------------------------------

# Etiquetas de cierre canonicas para una fila archivada.
ARCHIVE_TERMINAL_STATES = frozenset(
    {
        "completed",
        "done",
        "closed",
        "absorbed",
        "superseded",
        # Cierres NEGATIVOS: el ticket termina sin entregarse, y eso es un final
        # legitimo, no un pendiente. `blocked-final` es ademas terminal en el
        # vocabulario del bus (bus.state_machine, por complemento de
        # NON_TERMINAL_STATES); `not-pursued` es la decision explicita de no
        # hacerlo. Ambos censados en el archivo real 2026-08-04.
        "blocked-final",
        "not-pursued",
    }
)

# Formas historicas de un solo uso, censadas 2026-08-04. Se toleran porque ya
# estan escritas; NO son vocabulario a imitar. Nada debe ANADIR entradas aqui para
# silenciar un cierre nuevo: usa ARCHIVE_TERMINAL_STATES.
_ARCHIVE_TERMINAL_LEGACY = frozenset({"completed-via-010n", "resuelto-por-workflow"})


def _archive_row_state(cells: list[str]) -> str:
    """Locate the Estado cell of an archived row, tolerating pipe-shifted rows.

    Position alone is NOT enough (measured 2026-08-04): the canonical index is 4,
    but an unescaped pipe INSIDE the Titulo cell splits it in two and shifts every
    later column one slot right -- `WOT-2026-015n` and `WOT-2026-021i` keep their
    real `completed` at index 5, while index 4 holds the Scope (`motor/...`).
    Reading index 4 blindly reported those as UNKNOWN states, i.e. accused two
    correctly-closed rows.

    The canonical index 4 has PRIORITY and the fallback is NARROW, because the two
    failure modes must not be conflated (regression caught by mutation while
    building this): a SHIFTED column and a TYPO look alike at index 4 -- both hold
    something that is not a state. If the fallback simply scanned for any known
    state, the typo `competed` would be silently skipped in favour of the real
    `completed` sitting one slot right, and the guard would stop catching exactly
    the misspelling it exists for.

    The discriminator is what index 4 CONTAINS. A shifted row leaves the Scope
    there, and Scope has a recognisable shape (`motor/...`, `ci/...`: a slug with a
    slash, never a state word). So: read index 4; if it is a known state, done. If
    it looks like a Scope slug, the row is shifted -- look one slot right. Anything
    else at index 4 is reported as-is, which is how a typo stays visible.
    """
    known = ARCHIVE_TERMINAL_STATES | _ARCHIVE_TERMINAL_LEGACY | set(LIVE_STATES)
    candidate = cells[4].lower()
    if candidate in known:
        return candidate
    # Scope-shaped cell at the Estado slot => the row is pipe-shifted, not mistyped.
    if "/" in candidate and len(cells) > 5:
        shifted = cells[5].lower()
        if shifted in known:
            return shifted
    return candidate


def _compact_closure_log_states(archive: Path) -> list[str]:
    """Audit the archive's COMPACT closure-log rows (``| Ticket | Estado | Nota |``).

    The Prioridad-led check above deliberately ignores these rows: the id sits at a
    different index and they are closure NOTES, not queue snapshots -- counting them
    in the duplicate-id checks would turn normal layering into false positives.

    But "not a queue row" does not mean "may declare pending work". A compact row
    saying `| WOT-... | pending | ...` claims live work inside history exactly like
    a Prioridad-led one, and the Prioridad-led guard would never see it. An
    adversarial pass raised this as an open hole; measured 2026-08-04 there are 124
    compact rows and ZERO carry a live state, so this closes the door BEFORE anyone
    walks through it rather than after (the 18 rows the sibling check found were
    only visible once someone looked).

    Scope note: only the state VOCABULARY is audited here. Unknown labels are NOT
    reported for compact rows -- their Nota column is free prose and a two-cell
    layout gives no reliable way to tell a typo from an abbreviation.
    """
    live = set(LIVE_STATES)
    errors: list[str] = []
    for line in archive.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped.startswith("| "):
            continue
        raw = stripped.split("|")
        # Compact layout: id at raw index 1 (no Prioridad column). A Prioridad-led
        # row has its id at index 2 and is handled by the caller.
        if len(raw) <= 2 or not _TICKET_ROW_CELL_RE.match(raw[1].strip()):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) <= 1:
            continue
        state = cells[1].lower()
        if state in live:
            errors.append(
                f"{raw[1].strip()}: compact closure-log row declares the "
                f"NON-terminal state '{state}'. The closure log records how a "
                f"ticket ENDED; a live state there hides pending work inside "
                f"history just like an archived queue row does."
            )
    return errors


def validate_archive_states(root: Path) -> list[str]:
    """Return violations for archived rows still carrying a LIVE (non-terminal) state.

    Before: ``root`` is the destino root; the archive may or may not exist.
    During: reads only Prioridad-led rows (id at raw index 2, same convention as
        _row_ticket_id) -- the archive's compact ``| Ticket | Estado | Nota |``
        closure-log rows use a different layout and are not queue snapshots.
        Cross-references the live queue so the diagnostic can say whether the
        ticket is merely mislabeled or has vanished from both surfaces.
    After: one error per archived row whose state belongs to LIVE_STATES. No
        mutation.
    """
    collab = root / ".agent" / "collaboration"
    archive = collab / "_archive" / "backlog_done.md"
    if not archive.exists():
        return []

    live_ids = set(_ticket_row_ids(collab / "backlog.md"))
    errors: list[str] = []
    errors.extend(_compact_closure_log_states(archive))
    for line in archive.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        tid = _row_ticket_id(stripped)
        if tid is None:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # ARITY-INDEPENDIENTE (hallazgo del bucle L800, Codex): la primera version
        # hacia `continue` cuando la arity no era 8, heredando el scope de
        # validate_archive_row_arity. Eso dejaba INVISIBLES 9 filas MAS -- las
        # rotas por un pipe sin escapar (`014a/b/d/e/f/g/h/i`, arity 9) y una de
        # la seccion historica de 7 columnas (`WT-2026-250c`) -- todas con estado
        # LIVE. El guard daba OK sobre una superficie que nunca miraba, que es
        # justo el falso verde que viene a cerrar.
        # La arity es competencia de validate_archive_row_arity; AQUI solo importa
        # que la celda de Estado exista y se pueda leer. En las tres layouts
        # censadas (7, 8 y 9+ celdas) el Estado sigue en el indice 4, porque el
        # pipe que rompe la fila aparece DESPUES, en el texto del titulo.
        if len(cells) <= 4:
            continue  # sin celda de Estado que auditar
        state = _archive_row_state(cells)
        if state in ARCHIVE_TERMINAL_STATES or state in _ARCHIVE_TERMINAL_LEGACY:
            continue
        if state in LIVE_STATES:
            where = (
                "it also has a live row (so the archived copy is the stale one)"
                if tid in live_ids
                else "and it has NO live row -- the ticket is invisible in BOTH surfaces"
            )
            errors.append(
                f"{tid}: archived row still declares the NON-terminal state "
                f"'{state}' {where}. A row in _archive/backlog_done.md is HISTORY: "
                f"it must carry a terminal state "
                f"({'/'.join(sorted(ARCHIVE_TERMINAL_STATES))}). Close it with its "
                f"landing evidence (commit:<sha>) or move it back to the live queue "
                f"-- do not leave pending work filed as history."
            )
        else:
            # Ni terminal ni live: casi siempre una ERRATA (`competed`) que el
            # complemento de LIVE_STATES habria aceptado como terminal.
            errors.append(
                f"{tid}: archived row has the UNKNOWN state '{state}' -- it is "
                f"neither a terminal state "
                f"({'/'.join(sorted(ARCHIVE_TERMINAL_STATES))}) nor a live one. "
                f"Almost certainly a typo: an unrecognised label must NOT pass as "
                f"'closed' just because it is not a live state."
            )
    return errors


def _terminal_ticket_states(archive: Path) -> dict[str, str]:
    """Map ticket id -> terminal state for every archived Prioridad-led row.

    Before: ``archive`` exists and is readable.
    During: reads only rows whose id is parseable by ``_row_ticket_id``; skips
        rows without a readable Estado cell. Arity-INDEPENDIENTE a proposito
        (ver validate_archive_states): gatear por arity==8 escondio 9 filas.
    After: returns the mapping; no mutation. Rows in a live state are omitted,
        so a lookup miss means "not closed" (or "not archived").
    """
    terminal: dict[str, str] = {}
    for line in archive.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        tid = _row_ticket_id(stripped)
        if tid is None:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) <= 4:
            continue
        state = _archive_row_state(cells)
        if state in ARCHIVE_TERMINAL_STATES or state in _ARCHIVE_TERMINAL_LEGACY:
            terminal[tid] = state
    return terminal


def validate_live_dependencies(root: Path) -> list[str]:
    """Return violations for LIVE rows whose ``Depende de`` cites a TERMINAL ticket.

    Before: ``root`` is the destino root; ``backlog.md`` may or may not exist and
        the archive may be absent (a fresh destino has no closures yet).
    During: reads the ``Depende de`` cell (raw index 5) of every Prioridad-led row
        in the LIVE queue and resolves each cited id against the archive's
        terminal states. A cell may cite SEVERAL ids separated by commas
        (precedent: ``WOT-2026-013b`` -> ``WOT-2026-011e, WOT-2026-010m``), so
        each is resolved independently. ``-`` and empty mean "no dependency".
        Arity-INDEPENDIENTE by deliberate design: the sibling
        validate_archive_states documents that gating on arity==8 hid 9 rows
        broken by an unescaped pipe. The dependency cell keeps index 5 across the
        censused layouts because the extra pipe appears LATER, inside the title.
    After: one error per live row blocked by an already-closed ticket. No mutation.

    WOT-2026-049c (barrera del bucle de gobierno): `049g` quedo `pending` con
    `Depende de: WOT-2026-049c` DESPUES de que `049c` se cerrara con
    `commit:4199f17`. El contrato salia rc=0 porque la celda `Depende de` solo se
    nombraba para EXCLUIRLA del matching de ids (`:76`, `:89`, `:469-470`,
    `:517`) -- se conocia la celda y se evitaba a proposito, pero NADA validaba
    el ESTADO del ticket citado. Es el patron del denominador: el guard corre,
    sale verde, y el objeto no esta en su universo. Un bloqueo que apunta a un
    difunto es indistinguible de un bloqueo real, y congela al heredero.
    """
    collab = root / ".agent" / "collaboration"
    backlog = collab / "backlog.md"
    archive = collab / "_archive" / "backlog_done.md"
    if not backlog.exists() or not archive.exists():
        return []

    terminal = _terminal_ticket_states(archive)
    errors: list[str] = []
    for line in backlog.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        tid = _row_ticket_id(stripped)
        if tid is None:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) <= 5:
            continue
        raw = cells[5]
        if raw in {"", "-"}:
            continue
        for dep in (d.strip() for d in raw.split(",")):
            state = terminal.get(dep)
            if state is not None:
                errors.append(
                    f"{tid}: 'Depende de' cita {dep}, que ya esta CERRADO "
                    f"(estado '{state}' en _archive/backlog_done.md). Un bloqueo "
                    f"que apunta a un ticket terminal congela la fila sin motivo: "
                    f"pon '-' si la dependencia ya no aplica."
                )
    return errors


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
    # WOT-2026-027i: duplicate ids across / within the scheduling surfaces.
    violations = violations + validate_live_archive_integrity(root)
    # WOT-2026-026z: arity of NEW Prioridad-led rows in the archive.
    violations = violations + validate_archive_row_arity(root)
    # WOT-2026-026t: archived rows must not keep a non-terminal (live) state.
    violations = violations + validate_archive_states(root)
    # WOT-2026-049c: una fila VIVA no puede depender de un ticket ya cerrado.
    violations = violations + validate_live_dependencies(root)
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
