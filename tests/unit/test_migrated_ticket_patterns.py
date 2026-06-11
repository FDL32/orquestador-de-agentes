"""Unit tests for ticket-ID regex patterns in migrated consumers.

WT-2026-251a: these modules were migrated from inline ``(?:WP|WT)-`` patterns
to canonical imports from bus.ticket_id.  Each test covers a 2-letter prefix
ticket (``WT-2026-248b``) and a 3-letter prefix ticket (``WOT-2026-001a``)
per the minimum matrix defined in the ticket specification.

[NON-REVERSE-CLASSICAL: coverage matrix for migrated imports — the pattern
already exists in source; these tests validate the new prefix range.]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Ensure motor root is importable ──────────────────────────────────────────
_MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))


# ── Minimum test matrix ───────────────────────────────────────────────────────
TICKET_2_LETTER = "WT-2026-248b"  # 2-letter prefix + alpha suffix
TICKET_3_LETTER = "WOT-2026-001a"  # 3-letter prefix + alpha suffix
TICKET_3_NUMERIC = "CTL-2026-001"  # 3-letter prefix + pure-numeric suffix


# ---------------------------------------------------------------------------
# archive_execution_log.SECTION_RE
# ---------------------------------------------------------------------------


def _load_archive_execution_log():
    spec = importlib.util.spec_from_file_location(
        "archive_execution_log",
        _MOTOR_ROOT / "scripts" / "archive_execution_log.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestArchiveExecutionLogSectionRE:
    """SECTION_RE must match 2-letter and 3-letter ticket headings."""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_archive_execution_log()

    def test_matches_two_letter_prefix(self, mod):
        line = f"### {TICKET_2_LETTER} - some description"
        assert mod.SECTION_RE.search(line), (
            f"SECTION_RE must match 2-letter prefix ticket: {TICKET_2_LETTER}"
        )

    def test_matches_three_letter_prefix(self, mod):
        line = f"### {TICKET_3_LETTER} - some description"
        assert mod.SECTION_RE.search(line), (
            f"SECTION_RE must match 3-letter prefix ticket: {TICKET_3_LETTER}"
        )

    def test_does_not_match_plain_heading(self, mod):
        line = "### Some heading without ticket ID"
        assert not mod.SECTION_RE.search(line), (
            "SECTION_RE must not match plain headings"
        )


# ---------------------------------------------------------------------------
# graph_context.extract_active_ticket_id
# ---------------------------------------------------------------------------


class TestGraphContextExtractTicketId:
    """extract_active_ticket_id must parse 2-letter and 3-letter prefixes."""

    @pytest.fixture(scope="class")
    def extract_fn(self):
        from scripts.graph_context import extract_active_ticket_id

        return extract_active_ticket_id

    def test_extracts_two_letter(self, extract_fn):
        content = f"**ID:** {TICKET_2_LETTER}"
        result = extract_fn(content)
        assert result == TICKET_2_LETTER, (
            f"extract_active_ticket_id returned {result!r}, expected {TICKET_2_LETTER!r}"
        )

    def test_extracts_three_letter(self, extract_fn):
        content = f"**ID:** {TICKET_3_LETTER}"
        result = extract_fn(content)
        assert result == TICKET_3_LETTER, (
            f"extract_active_ticket_id returned {result!r}, expected {TICKET_3_LETTER!r}"
        )

    def test_returns_none_for_no_match(self, extract_fn):
        assert extract_fn("No ticket here") is None


# ---------------------------------------------------------------------------
# migrate_observations._extract_ticket_from_source
# ---------------------------------------------------------------------------


def _load_migrate_observations():
    spec = importlib.util.spec_from_file_location(
        "migrate_observations",
        _MOTOR_ROOT / "scripts" / "migrate_observations.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrateObservationsExtractTicket:
    """_extract_ticket_from_source must accept 2-letter and 3-letter prefixes."""

    @pytest.fixture(scope="class")
    def fn(self):
        mod = _load_migrate_observations()
        return mod._extract_ticket_from_source

    def test_two_letter_in_source_string(self, fn):
        result = fn(f"human_audit_{TICKET_2_LETTER}")
        assert result == TICKET_2_LETTER, f"Got {result!r}"

    def test_three_letter_in_source_string(self, fn):
        result = fn(f"human_audit_{TICKET_3_LETTER}")
        assert result == TICKET_3_LETTER, f"Got {result!r}"

    def test_no_ticket_returns_empty(self, fn):
        assert fn("no_ticket_here") == ""


# ---------------------------------------------------------------------------
# session_closeout.TICKET_RE and _resolve_active_ticket
# ---------------------------------------------------------------------------


def _load_session_closeout():
    spec = importlib.util.spec_from_file_location(
        "session_closeout",
        _MOTOR_ROOT / "scripts" / "session_closeout.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Must register before exec_module so dataclass resolution can find the module
    sys.modules.setdefault("session_closeout", mod)
    spec.loader.exec_module(mod)
    return mod


class TestSessionCloseoutTicketRE:
    """TICKET_RE must match 2-letter and 3-letter prefix tickets."""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_session_closeout()

    def test_matches_two_letter(self, mod):
        m = mod.TICKET_RE.search(TICKET_2_LETTER)
        assert m is not None, f"TICKET_RE must match {TICKET_2_LETTER}"
        assert m.group(0) == TICKET_2_LETTER

    def test_matches_three_letter(self, mod):
        m = mod.TICKET_RE.search(TICKET_3_LETTER)
        assert m is not None, f"TICKET_RE must match {TICKET_3_LETTER}"
        assert m.group(0) == TICKET_3_LETTER

    def test_resolve_active_ticket_two_letter(self, mod, tmp_path):
        wp = tmp_path / "work_plan.md"
        wp.write_text(f"- **ID:** {TICKET_2_LETTER}\n", encoding="utf-8")
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            f"- **ID:** {TICKET_2_LETTER}\n", encoding="utf-8"
        )
        result = mod._resolve_active_ticket(tmp_path)
        assert result == TICKET_2_LETTER, f"Got {result!r}"

    def test_resolve_active_ticket_three_letter(self, mod, tmp_path):
        collab = tmp_path / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        (collab / "work_plan.md").write_text(
            f"- **ID:** {TICKET_3_LETTER}\n", encoding="utf-8"
        )
        result = mod._resolve_active_ticket(tmp_path)
        assert result == TICKET_3_LETTER, f"Got {result!r}"


# ---------------------------------------------------------------------------
# ticket_activity_monitor._active_ticket_from_work_plan_content
# ---------------------------------------------------------------------------


class TestTicketActivityMonitorContent:
    """_active_ticket_from_work_plan_content must accept 2-letter and 3-letter."""

    @pytest.fixture(scope="class")
    def fn(self):
        spec = importlib.util.spec_from_file_location(
            "ticket_activity_monitor",
            _MOTOR_ROOT / "scripts" / "ticket_activity_monitor.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._active_ticket_from_work_plan_content

    def test_two_letter_id_field(self, fn):
        content = f"- **ID:** {TICKET_2_LETTER}"
        assert fn(content) == TICKET_2_LETTER

    def test_three_letter_id_field(self, fn):
        content = f"- **ID:** {TICKET_3_LETTER}"
        assert fn(content) == TICKET_3_LETTER

    def test_two_letter_plan_activo_field(self, fn):
        content = f"- **Ticket activo:** {TICKET_2_LETTER}"
        assert fn(content) == TICKET_2_LETTER

    def test_three_letter_plan_activo_field(self, fn):
        content = f"- **Ticket activo:** {TICKET_3_LETTER}"
        assert fn(content) == TICKET_3_LETTER


# ---------------------------------------------------------------------------
# validate_authority.extract_ticket_id
# ---------------------------------------------------------------------------


class TestValidateAuthorityExtractTicket:
    """extract_ticket_id must accept 2-letter and 3-letter prefix tickets."""

    @pytest.fixture(scope="class")
    def fn(self):
        spec = importlib.util.spec_from_file_location(
            "validate_authority",
            _MOTOR_ROOT / "scripts" / "validate_authority.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.extract_ticket_id

    def test_two_letter_in_content(self, fn):
        content = f"**ID:** {TICKET_2_LETTER}\n"
        assert fn(content) == TICKET_2_LETTER

    def test_three_letter_in_content(self, fn):
        content = f"**ID:** {TICKET_3_LETTER}\n"
        assert fn(content) == TICKET_3_LETTER

    def test_returns_unknown_when_no_match(self, fn):
        assert fn("no ticket here\n") == "UNKNOWN"
