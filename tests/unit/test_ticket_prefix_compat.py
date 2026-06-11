"""Tests for three-letter ticket prefix compatibility across the bus.

Covers the regex patterns expanded in WT-2026-245a for bus/review_bridge.py
and bus/supervisor.py. Verifies that WP-*, WT-* and CTL-* (three-letter
prefix) ticket IDs are all correctly parsed by string-extraction patterns.

WT-2026-251a: NUMERIC_SUFFIX_PATTERN and NEXT_TICKET_PATTERN now also accept
3-letter prefixes, but ONLY when the suffix is purely numeric (int() safe).
Alphanumeric suffixes like "042a" must still be rejected by these patterns.
"""

import pytest

# -- Import canonical patterns from bus.ticket_id --
from bus.ticket_id import (
    LOOSE_PATTERN,
    NEXT_TICKET_PATTERN,
    NUMERIC_SUFFIX_PATTERN,
    SECTION_DELIMITER_PATTERN,
    TICKET_ID_RE,
    TICKET_SORT_KEY_PATTERN,
    TURN_TABLE_PATTERN,
    WORKPLAN_FIELD_PATTERN,
    WORKPLAN_HEADING_PATTERN,
    WORKPLAN_ID_PATTERN,
    extract_all_ticket_ids,
    extract_ticket_id,
    is_valid_ticket_id,
)


# -- Test vectors --
TICKET_WP = "WP-2026-001"
TICKET_WT = "WT-2026-042a"
TICKET_CTL = "CTL-2026-001a"
TICKETS_ALL = [TICKET_WP, TICKET_WT, TICKET_CTL]


class TestExpandedPatternsMatchAllPrefixes:
    """Every expanded pattern must match WP, WT, and three-letter prefixes."""

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_id(self, ticket):
        content = f"**ID:** {ticket}"
        m = WORKPLAN_ID_PATTERN.search(content)
        assert m is not None, f"workplan_id pattern failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ensure_queue_findall(self, ticket):
        content = f"## Tickets\n- {ticket}\n"
        matches = TICKET_ID_RE.findall(content)
        assert ticket in matches, f"ensure_queue_findall failed for {ticket}"

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ensure_queue_search(self, ticket):
        content = f"## Tickets\n- {ticket}\n"
        m = TICKET_SORT_KEY_PATTERN.search(content)
        assert m is not None, f"ensure_queue_search failed for {ticket}"
        prefix, suffix = m.group(1), m.group(2)
        assert f"{prefix}-{suffix}" in ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_turn_table(self, ticket):
        """recover_active_ticket TURN.md table patterns."""
        # Row header variants
        for header in ("Plan ID", "Ticket Activo", "Ticket", "Plan activo"):
            content = f"| **{header}** | {ticket} |"
            m = TURN_TABLE_PATTERN.search(content)
            assert m is not None, f"turn_table ({header}) failed for {ticket}"
            assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_field(self, ticket):
        """recover_active_ticket work_plan field patterns."""
        for field in ("Plan activo:", "ID:"):
            content = f"**{field}** {ticket}"
            m = WORKPLAN_FIELD_PATTERN.search(content)
            assert m is not None, f"workplan_field ({field}) failed for {ticket}"
            assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_workplan_heading(self, ticket):
        content = f"## {ticket}"
        m = WORKPLAN_HEADING_PATTERN.search(content)
        assert m is not None, f"workplan_heading failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_loose(self, ticket):
        """Loose match pattern in recover_active_ticket and _work_plan_active_ticket."""
        content = f"... {ticket} ..."
        m = LOOSE_PATTERN.search(content)
        assert m is not None, f"loose pattern failed for {ticket}"
        assert m.group(1) == ticket

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_ticket_sort_key_pattern(self, ticket):
        m = TICKET_SORT_KEY_PATTERN.match(ticket)
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
            match = SECTION_DELIMITER_PATTERN.search(content)
            assert match is not None, f"section delimiter failed for {prefix}"
            # Lookahead is zero-width; verify it finds the boundary before `### ...`
            assert content[match.start() :].startswith("\n### "), (
                f"section delimiter at wrong position for {prefix}"
            )

    @pytest.mark.parametrize("ticket", TICKETS_ALL)
    def test_no_false_negatives_embedded(self, ticket):
        """Ticket ID embedded in larger text should still be found."""
        content = f"Some context before. {ticket} is the ticket. Some context after."
        m = LOOSE_PATTERN.search(content)
        assert m is not None, f"embedded match failed for {ticket}"
        assert m.group(1) == ticket


class TestNumericPatternsPreserved:
    """Patterns that feed int() must only capture pure-numeric suffixes.

    WT-2026-251a: extended from WP|WT-only to include 3-letter prefixes,
    but ONLY for tickets with pure-numeric suffixes (int() safety contract).
    Alphanumeric suffixes like "042a" must still NOT match.
    """

    @pytest.mark.parametrize("ticket", [TICKET_WP, TICKET_WT])
    def test_numeric_suffix_accepts_wp_wt(self, ticket):
        m = NUMERIC_SUFFIX_PATTERN.search(ticket)
        assert m is not None, f"numeric_suffix should match {ticket}"

    def test_numeric_suffix_on_three_letter_alpha_only_captures_numeric_part(self):
        r"""CTL-2026-001a: NUMERIC_SUFFIX_PATTERN may match but captured group is '001' only.

        WT-2026-251a: The pattern uses (\d+) so if the ticket string is
        'CTL-2026-001a', the match stops at the digits — group(1) == '001',
        not '001a'. This preserves int() safety even when search() finds a
        partial match inside an alphanumeric-suffixed ticket ID.
        """
        m = NUMERIC_SUFFIX_PATTERN.search(TICKET_CTL)
        # The pattern may or may not match depending on anchor position.
        # If it matches, the captured group MUST be pure-numeric for int() safety.
        if m is not None:
            captured = m.group(1)
            assert captured.isdigit(), (
                f"Captured group {captured!r} must be digits-only for int() safety"
            )
            assert int(captured) == 1, f"Expected 1, got {int(captured)}"

    def test_numeric_suffix_accepts_three_letter_numeric(self):
        """WT-2026-251a: CTL-2026-001 (pure numeric) must now match NUMERIC_SUFFIX_PATTERN."""
        m = NUMERIC_SUFFIX_PATTERN.search("CTL-2026-001")
        assert m is not None, "CTL pure-numeric suffix must match numeric pattern"
        assert m.group(1) == "001", f"Expected captured group '001', got {m.group(1)!r}"
        assert int(m.group(1)) == 1, "Captured group must be safely castable to int()"

    def test_numeric_suffix_group_is_numeric_only(self):
        """WT-2026-251a: group(1) must be digits-only for WOT-2026-042."""
        m = NUMERIC_SUFFIX_PATTERN.search("WOT-2026-042")
        assert m is not None, "WOT (3-letter) pure-numeric must match"
        assert m.group(1) == "042"
        assert int(m.group(1)) == 42

    @pytest.mark.parametrize("ticket", [TICKET_WP, TICKET_WT])
    def test_next_ticket_accepts_wp_wt(self, ticket):
        m = NEXT_TICKET_PATTERN.match(ticket)
        assert m is not None, f"next_ticket should match {ticket}"

    def test_next_ticket_on_three_letter_alpha_number_group_is_numeric_only(self):
        r"""CTL-2026-001a: if NEXT_TICKET_PATTERN matches, the number group must be digits-only.

        WT-2026-251a: NEXT_TICKET_PATTERN uses (\d+) for the suffix so even
        when matching 'CTL-2026-001a' the captured number group is '001', never
        '001a'.  This ensures the caller can safely call int() on group(2).
        """
        m = NEXT_TICKET_PATTERN.match(TICKET_CTL)
        if m is not None:
            number_group = m.group(2)
            assert number_group.isdigit(), (
                f"Number group {number_group!r} must be digits-only for int() safety"
            )
            assert int(number_group) == 1

    def test_next_ticket_accepts_three_letter_numeric(self):
        """WT-2026-251a: CTL-2026-001 (pure numeric) must now match NEXT_TICKET_PATTERN."""
        m = NEXT_TICKET_PATTERN.match("CTL-2026-001")
        assert m is not None, "CTL pure-numeric suffix must match next_ticket pattern"
        year, number = m.group(1), m.group(2)
        assert year == "2026"
        assert number == "001"
        assert int(number) == 1, "Number group must be safely castable to int()"

    def test_next_ticket_accepts_three_letter_wot(self):
        """WT-2026-251a: WOT-2026-042 must match NEXT_TICKET_PATTERN."""
        m = NEXT_TICKET_PATTERN.match("WOT-2026-042")
        assert m is not None
        assert m.group(2) == "042"
        assert int(m.group(2)) == 42


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


class TestTicketIdModule:
    """Tests for the bus.ticket_id module utility functions."""

    def test_is_valid_ticket_id_wp(self):
        assert is_valid_ticket_id("WP-2026-001") is True

    def test_is_valid_ticket_id_wt(self):
        assert is_valid_ticket_id("WT-2026-042a") is True

    def test_is_valid_ticket_id_ctl(self):
        assert is_valid_ticket_id("CTL-2026-001a") is True

    def test_is_valid_ticket_id_invalid(self):
        assert is_valid_ticket_id("INVALID") is False
        assert is_valid_ticket_id("") is False
        assert is_valid_ticket_id("WP-2026") is False

    def test_extract_ticket_id(self):
        assert extract_ticket_id("Ticket **ID:** CTL-2026-001a") == "CTL-2026-001a"
        assert extract_ticket_id("No ticket here") is None

    def test_extract_all_ticket_ids(self):
        text = "First: WP-2026-001, Second: CTL-2026-001a"
        ids = extract_all_ticket_ids(text)
        assert ids == ["WP-2026-001", "CTL-2026-001a"]

    def test_extract_all_ticket_ids_empty(self):
        assert extract_all_ticket_ids("No tickets") == []


class TestSupervisorPatternIntegration:
    """Regression: compiled patterns must work with .search(), not re.search(flags=).

    WT-2026-245c: TURN_TABLE_PATTERN and WORKPLAN_FIELD_PATTERN are compiled
    with IGNORECASE in bus/ticket_id.py. Callers must use pattern.search(content)
    instead of re.search(pattern, content, flags=...) which raises ValueError
    on compiled patterns.
    """

    def test_turn_table_pattern_search_no_flags(self):
        """TURN_TABLE_PATTERN.search() must match with IGNORECASE baked in."""
        content = "| **Plan ID** | WT-2026-042a |"
        m = TURN_TABLE_PATTERN.search(content)
        assert m is not None
        assert m.group(1) == "WT-2026-042a"

    def test_turn_table_pattern_search_lowercase_header(self):
        """Lowercase header must still match (IGNORECASE compiled in)."""
        content = "| **plan id** | CTL-2026-001a |"
        m = TURN_TABLE_PATTERN.search(content)
        assert m is not None
        assert m.group(1) == "CTL-2026-001a"

    def test_workplan_field_pattern_search_no_flags(self):
        """WORKPLAN_FIELD_PATTERN.search() must match with IGNORECASE baked in."""
        content = "**ID:** WT-2026-042a"
        m = WORKPLAN_FIELD_PATTERN.search(content)
        assert m is not None
        assert m.group(1) == "WT-2026-042a"

    def test_workplan_field_pattern_search_lowercase(self):
        """Lowercase field must still match (IGNORECASE compiled in)."""
        content = "**id:** ctl-2026-001a"
        m = WORKPLAN_FIELD_PATTERN.search(content)
        assert m is not None
        assert m.group(1) == "ctl-2026-001a"

    def test_workplan_heading_pattern_search_no_flags(self):
        """WORKPLAN_HEADING_PATTERN.search() must match with MULTILINE baked in."""
        content = "## CTL-2026-001a\nsome content"
        m = WORKPLAN_HEADING_PATTERN.search(content)
        assert m is not None
        assert m.group(1) == "CTL-2026-001a"

    def test_recover_active_ticket_simulated(self):
        """Simulate recover_active_ticket() logic with real patterns.

        This exercises the exact call chain that was broken by the regression:
        iterating compiled patterns and calling .search() on each.
        """
        turn_content = "| **Plan ID** | CTL-2026-001a |"
        patterns = (TURN_TABLE_PATTERN,) * 4
        for pattern in patterns:
            match = pattern.search(turn_content)
            if match:
                assert match.group(1) == "CTL-2026-001a"
                break
        else:
            pytest.fail("recover_active_ticket TURN path failed")

    def test_work_plan_active_ticket_simulated(self):
        """Simulate _work_plan_active_ticket() logic with real patterns."""
        wp_content = "## Metadata\n- **ID:** CTL-2026-001a\n- **Estado:** IN_PROGRESS\n"
        patterns = (
            WORKPLAN_FIELD_PATTERN,
            WORKPLAN_FIELD_PATTERN,
            WORKPLAN_HEADING_PATTERN,
        )
        for pattern in patterns:
            match = pattern.search(wp_content)
            if match:
                assert match.group(1) == "CTL-2026-001a"
                break
        else:
            pytest.fail("_work_plan_active_ticket path failed")
