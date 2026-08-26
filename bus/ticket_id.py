"""
Canonical ticket ID pattern for the motor.

WT-2026-245c: Single source of truth for the ticket ID regex pattern
``(?:WP|WT|[A-Z]{3})-\\d{4}-[A-Za-z0-9]+``.

All Python consumers (review_bridge, supervisor, etc.) MUST import from this
module instead of repeating the pattern inline. PowerShell consumers maintain
their own local copy via ``$script:TicketIdPattern``.
"""

from __future__ import annotations

import re
from pathlib import Path


# ── Canonical ticket ID pattern ──────────────────────────────────────────────
# Matches WP-XXXX-XXX, WT-XXXX-XXX, and three-letter-prefix tickets like
# CTL-XXXX-XXX. The prefix is exactly 2 or 3 uppercase letters.
# The year is exactly 4 digits. The suffix is alphanumeric (letters and digits).
TICKET_ID_PATTERN = r"(?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+"

# ── Compiled regex for direct use ────────────────────────────────────────────
TICKET_ID_RE = re.compile(TICKET_ID_PATTERN)

# ── Pattern for matching **ID:** fields in markdown ──────────────────────────
WORKPLAN_ID_PATTERN = re.compile(r"\*\*ID:\*\*\s*(" + TICKET_ID_PATTERN + r")")

# ── Pattern for matching markdown table rows with ticket IDs ─────────────────
# Compiled with IGNORECASE because callers match against user-authored markdown
# where header casing may vary (e.g. "Plan ID" vs "plan id").
TURN_TABLE_PATTERN = re.compile(
    r"\|\s*\*\*(?:Ticket Activo|Plan ID|Ticket|Plan activo)\*\*\s*\|\s*"
    r"(" + TICKET_ID_PATTERN + r")\s*\|",
    re.IGNORECASE,
)

# ── Pattern for matching **Plan activo:** or **ID:** fields ──────────────────
# Compiled with IGNORECASE because callers match against user-authored markdown
# where field casing may vary.
WORKPLAN_FIELD_PATTERN = re.compile(
    r"\*\*(?:Plan activo|ID):\*\*\s*(" + TICKET_ID_PATTERN + r")",
    re.IGNORECASE,
)

# ── Pattern for matching markdown headings with ticket IDs ───────────────────
WORKPLAN_HEADING_PATTERN = re.compile(
    r"^\s*##\s+(" + TICKET_ID_PATTERN + r")\b",
    re.MULTILINE,
)

# ── Loose match pattern (finds ticket ID anywhere in text) ───────────────────
LOOSE_PATTERN = re.compile(r"(" + TICKET_ID_PATTERN + r")")

# ── Section delimiter for execution_log.md extraction ────────────────────────
SECTION_DELIMITER_PATTERN = re.compile(r"(?=\n### " + TICKET_ID_PATTERN + r")")

# ── Numeric-only patterns (feed int()) ──────────────────────────────────────
# WT-2026-251a: Extended from WP|WT to include 3-letter prefixes (e.g. WOT).
# The captured group is always the numeric suffix (\d+) so callers can safely
# call int() on it. Alphanumeric suffixes like "042a" do NOT match these
# patterns — only the pure-numeric portion prefix triggers a match,
# ensuring int() safety downstream (bus/supervisor.py:468,624).
NUMERIC_SUFFIX_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-\d{4}-(\d+)")
NEXT_TICKET_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-(\d+)")

# ── Sort key pattern (accepts all prefixes, extracts year + suffix) ──────────
TICKET_SORT_KEY_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-([A-Za-z0-9]+)")


def is_valid_ticket_id(ticket_id: str) -> bool:
    """Return True if the string is a valid ticket ID.

    Before: Requires a string.
    During: Matches against the canonical TICKET_ID_PATTERN.
    After: Returns True for valid IDs like WP-2026-001, WT-2026-042a,
           CTL-2026-001a. Returns False for invalid strings.
    """
    return bool(TICKET_ID_RE.fullmatch(ticket_id))


def extract_ticket_id(text: str) -> str | None:
    """Extract the first ticket ID found in text, or None.

    Before: Requires a string.
    During: Searches for the canonical ticket ID pattern.
    After: Returns the first match or None.
    """
    m = LOOSE_PATTERN.search(text)
    return m.group(1) if m else None


def extract_all_ticket_ids(text: str) -> list[str]:
    """Extract all ticket IDs found in text.

    Before: Requires a string.
    During: Finds all matches of the canonical ticket ID pattern.
    After: Returns a list of matched ticket IDs (may be empty).
    """
    return LOOSE_PATTERN.findall(text)


# ── Next-free-ID allocation helpers (WOT-2026-040f) ──────────────────────────
# Pattern for the canonical assignment form <PREFIX>-<YEAR>-NNNx used by
# `orchestrator_pipeline.md:0.d`: three-digit number + OPTIONAL single trailing
# letter. Pure-numeric suffixes (WT-2026-251a legacy) also match, feeding int()
# safely on the number group. The letter group is optional so `-040` and `-040f`
# both parse: max is (number, letter-ord).
_CANONICAL_ID_RE = re.compile(r"([A-Z]{2,4})-(\d{4})-(\d{3,})([a-z]?)")


def collect_surface_ticket_ids(collab_dir: Path) -> set[str]:
    """Return the ticket IDs present in BOTH live-backlog and archive surfaces.

    Before: ``collab_dir`` resolves to a ``.agent/collaboration`` directory
        containing ``backlog.md`` (live queue) and ``_archive/backlog_done.md``
        (terminal archive). Missing files are tolerated (empty contribution).
    During: reads both files, extracts every canonical ticket ID from each via
        ``extract_all_ticket_ids``, unions the two sets. No mutation.
    After: returns the set of IDs found across BOTH surfaces. This is the
        single shared implementation of "which IDs exist" used by the
        assignment helper and by the memory-dedupe sweep
        (``scripts/find_similar_signals.py``).
    """
    found: set[str] = set()
    for rel in ("backlog.md", "_archive/backlog_done.md"):
        path = collab_dir / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(extract_all_ticket_ids(text))
    return found


def next_free_ticket_id(prefix: str, year: int, collab_dir: Path) -> str:
    """Return the next free ticket ID for a prefix/year scanning both surfaces.

    Before: ``collab_dir`` is a live ``.agent/collaboration`` directory with
        ``backlog.md`` and ``_archive/backlog_done.md``; ``prefix`` is the
        canon ticket prefix (e.g. ``WOT``); ``year`` the operative year.
    During: collects the canonical IDs of BOTH surfaces
        (``collect_surface_ticket_ids``), parses each matching
        ``<PREFIX>-<YEAR>-NNNx`` into ``(number, letter)``, and takes the
        global maximum. Allocation policy (WOT-2026-040f, declared): NO
        gap-filling -- always the successor of the global max (number, letter)
        across live + archive. Successor rules: same number with next letter
        (``400x`` -> ``400y``); ``z`` or pure-numeric suffix advances the
        number with letter ``a`` (``400z`` -> ``401a``). No prior IDs of the
        prefix/year -> ``<PREFIX>-<YEAR>-001a``.
    After: returns the successor as ``<PREFIX>-<YEAR>-NNNx`` (3-digit number).
        Never returns an ID present in either surface by construction.
    """
    existing = collect_surface_ticket_ids(collab_dir)
    max_key: tuple[int, int] | None = None
    for tid in existing:
        m = _CANONICAL_ID_RE.fullmatch(tid)
        if not m:
            continue
        pfx, yr, num, letter = m.groups()
        if pfx != prefix or int(yr) != year:
            continue
        key = (int(num), ord(letter) if letter else 0)
        if max_key is None or key > max_key:
            max_key = key
    if max_key is None:
        return f"{prefix}-{year:04d}-001a"
    num, letter_ord = max_key
    if letter_ord == 0 or letter_ord == ord("z"):
        return f"{prefix}-{year:04d}-{num + 1:03d}a"
    return f"{prefix}-{year:04d}-{num:03d}{chr(letter_ord + 1)}"
