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
TURN_TABLE_PATTERN = re.compile(
    r"\|\s*\*\*(?:Ticket Activo|Plan ID|Ticket|Plan activo)\*\*\s*\|\s*"
    r"(" + TICKET_ID_PATTERN + r")\s*\|"
)

# ── Pattern for matching **Plan activo:** or **ID:** fields ──────────────────
WORKPLAN_FIELD_PATTERN = re.compile(
    r"\*\*(?:Plan activo|ID):\*\*\s*(" + TICKET_ID_PATTERN + r")"
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

# ── Numeric-only patterns (preserved — feed int()) ───────────────────────────
# These MUST remain limited to WP|WT + numeric suffix because they feed int().
NUMERIC_SUFFIX_PATTERN = re.compile(r"(?:WP|WT)-\d{4}-(\d+)")
NEXT_TICKET_PATTERN = re.compile(r"(?:WP|WT)-(\d{4})-(\d+)")

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
