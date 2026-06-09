"""Tests for three-letter ticket prefix compatibility across the bus.

Covers the regex patterns expanded in WT-2026-245a for bus/review_bridge.py
and bus/supervisor.py. Verifies that WP-*, WT-* and CTL-* (three-letter
prefix) ticket IDs are all correctly parsed by string-extraction patterns,
while patterns that feed int() remain limited to WP|WT + numeric suffix.
"""

import re

import pytest


# ── Expanded patterns (must accept WP, WT, and three-letter prefixes) ──

# Pattern from review_bridge.py _get_active_ticket_id (both copies)
PATTERN_WORKPLAN_ID = re.compile(
    r"\*\*ID:\*\*\s*((?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+)"
)

# Pattern from supervisor.py ensure_ticket_queue:450 (re.findall)
PATTERN_ENSURE_QUEUE_FINDALL = re.compile(r"(?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+")

# Pattern from supervisor.py ensure_ticket_queue:453 (re.search)
PATTERN_ENSURE_QUEUE_SEARCH = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-([A-Za-z0-9]+)")

# Patterns from supervisor.py recover_active_ticket TURN.md table (lines 634-637)
PATTERN_TURN_TABLE = re.compile(
    r"\|\s*\*\*(?:Ticket Activo|Plan ID|Ticket|Plan activo)\*\*\s*\|\s*"
    r"((?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+)\s*\|"
)

# Patterns from supervisor.py recover_active_ticket work_plan fields (lines 650-652)
PATTERN_WORKPLAN_FIELD = re.compile(
    r"\*\*(?:Plan activo|ID):\*\*\s*((?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+)"
)

# Patterns from supervisor.py recover_active_ticket work_plan heading (line 652)
PATTERN_WORKPLAN_HEADING = re.compile(
    r"^\s*##\s+((?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+)\b",
    re.MULTILINE,
)

# Loose match patterns from supervisor.py (lines 643, 658, 680)
PATTERN_LOOSE = re.compile(r"((?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+)")

# Pattern from supervisor.py _ticket_sort_key (line 701)
PATTERN_TICKET_SORT_KEY = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-([A-Za-z0-9]+)")

# Section delimiter from review_bridge.py _extract_ticket_section (line 660)
PATTERN_SECTION_DELIMITER = re.compile(r"(?=\n### (?:WP|WT|[A-Z]{3})-)")

# ── Numeric-only patterns (preserved — feed int()) ──
PATTERN_NUMERIC_SUFFIX = re.compile(r"(?:WP|WT)-\d{4}-(\d+)")
PATTERN_NEXT_TICKET = re.compile(r"(?:WP|WT)-(\d{4})-(\d+)")

# Test vectors
TICKET_WP = "WP-2026-001"
TICKET_WT = "WT-2026-042a"
TICKET_CTL = "CTL-2026-001a"
TICKETS_ALL = [TICKET_WP, TICKET_WT, TICKET_CTL]


class TestExpandedPatternsMatchAllPrefixes:
    """Every expanded pattern must match WP, WT, and three-letter prefixes."""

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_id(self, ticket):
        content = f"**ID:** {ticket}"
        m = PATTERN_WORKPLAN_ID.search(content)
        assert m is not None, f"workplan_id pattern failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ensure_queue_findall(self, ticket):
        content = f"## Tickets\n- {ticket}\n"
        matches = PATTERN_ENSURE_QUEUE_FINDALL.findall(content)
        assert ticket in matches, f"ensure_queue_findall failed for {ticket}"

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ensure_queue_search(self, ticket):
        content = f"## Tickets\n- {ticket}\n"
        m = PATTERN_ENSURE_QUEUE_SEARCH.search(content)
        assert m is not None, f"ensure_queue_search failed for {ticket}"
        prefix, suffix = m.group(1), m.group(2)
        assert f"{prefix}-{suffix}" in ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_turn_table(self, ticket):
        """recover_active_ticket TURN.md table patterns."""
        # Row header variants
        for header in ("Plan ID", "Ticket Activo", "Ticket", "Plan activo"):
            content = f"| **{header}** | {ticket} |"
            m = PATTERN_TURN_TABLE.search(content)
            assert m is not None, f"turn_table ({header}) failed for {ticket}"
            assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_field(self, ticket):
        """recover_active_ticket work_plan field patterns."""
        for field in ("Plan activo:", "ID:"):
            content = f"**{field}** {ticket}"
            m = PATTERN_WORKPLAN_FIELD.search(content)
            assert m is not None, f"workplan_field ({field}) failed for {ticket}"
            assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_heading(self, ticket):
        content = f"## {ticket}"
        m = PATTERN_WORKPLAN_HEADING.search(content)
        assert m is not None, f"workplan_heading failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_loose(self, ticket):
        """Loose match pattern in recover_active_ticket and _work_plan_active_ticket."""
        content = f"... {ticket} ..."
        m = PATTERN_LOOSE.search(content)
        assert m is not None, f"loose pattern failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ticket_sort_key_pattern(self, ticket):
        m = PATTERN_TICKET_SORT_KEY.match(ticket)
        assert m is not None, f"sort_key pattern failed for {ticket}"
        year, suffix = m.group(1), m.group(2)
        assert len(year) == 4
        assert len(suffix) >= 1

    def test_section_delimiter(self):
        """_extract_ticket_section delimiter — ensures next-section boundary with three-letter prefix."""
        for prefix in ("WP", "WT", "CTL", "ABC"):
            content = (
                f"### some_ticket\nsome content\n### {prefix}-2026-999\nother content"
            )
            match = PATTERN_SECTION_DELIMITER.search(content)
            assert match is not None, f"section delimiter failed for {prefix}"
            # Lookahead is zero-width; verify it finds the boundary before `### ...`
            assert content[match.start() :].startswith("\n### "), (
                f"section delimiter at wrong position for {prefix}"
            )

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_no_false_negatives_embedded(self, ticket):
        """Ticket ID embedded in larger text should still be found."""
        content = f"Some context before. {ticket} is the ticket. Some context after."
        m = PATTERN_LOOSE.search(content)
        assert m is not None, f"embedded match failed for {ticket}"
        assert m.group(1) == ticket


class TestNumericPatternsPreserved:
    """Patterns that feed int() must remain limited to WP|WT + numeric suffix."""

    @pytest.mark.parametrize("ticket", [TICKET_WP, TICKET_WT])
    def test_numeric_suffix_accepts_wp_wt(self, ticket):
        m = PATTERN_NUMERIC_SUFFIX.search(ticket)
        assert m is not None, f"numeric_suffix should match {ticket}"

    def test_numeric_suffix_rejects_three_letter_alpha(self):
        """CTL-2026-001a has alphanumeric suffix; numeric pattern must reject it."""
        m = PATTERN_NUMERIC_SUFFIX.search(TICKET_CTL)
        assert m is None, "CTL alphanumeric suffix must NOT match numeric pattern"

    @pytest.mark.parametrize("ticket", [TICKET_WP, TICKET_WT])
    def test_next_ticket_accepts_wp_wt(self, ticket):
        m = PATTERN_NEXT_TICKET.match(ticket)
        assert m is not None, f"next_ticket should match {ticket}"

    def test_next_ticket_rejects_three_letter_with_alpha(self):
        m = PATTERN_NEXT_TICKET.match(TICKET_CTL)
        assert m is None, "CTL must NOT match next_ticket pattern (int() guard)"


class TestSortKeyIntegration:
    """Integration test for Supervisor._ticket_sort_key with CTL prefix."""

    def test_sort_key_ctl(self):
        from bus.supervisor import SequentialTicketSupervisor

        key = SequentialTicketSupervisor._ticket_sort_key("CTL-2026-001a")
        assert key[0] == 2026, f"Expected year 2026, got {key[0]}"
        assert key[1] == 1, f"Expected numeric_suffix 1, got {key[1]}"
        assert key[2] == "001a", f"Expected raw suffix '001a', got {key[2]}"

    def test_sort_key_wp(self):
        from bus.supervisor import SequentialTicketSupervisor

        key = SequentialTicketSupervisor._ticket_sort_key("WP-2026-001")
        assert key[0] == 2026
        assert key[1] == 1
        assert key[2] == "001"

    def test_sort_key_wt_with_alpha_suffix(self):
        from bus.supervisor import SequentialTicketSupervisor

        key = SequentialTicketSupervisor._ticket_sort_key("WT-2026-042a")
        assert key[0] == 2026
        assert key[1] == 42
        assert key[2] == "042a"

    def test_sort_key_none_ticket_id(self):
        from bus.supervisor import SequentialTicketSupervisor

        key = SequentialTicketSupervisor._ticket_sort_key(None)
        assert key == (-1, -1, ""), f"Unexpected {key}"
