from scripts.ticket_activity_monitor import _active_ticket_from_work_plan_content


def test_active_ticket_from_canonical_id_field() -> None:
    content = """
# Work Plan
- **ID:** WT-2026-234a
- **Estado:** DRAFT
"""

    assert _active_ticket_from_work_plan_content(content) == "WT-2026-234a"


def test_active_ticket_from_canonical_plan_id_field() -> None:
    content = """
# Work Plan
- **Plan ID:** WP-2026-123
- **Estado:** APPROVED
"""

    assert _active_ticket_from_work_plan_content(content) == "WP-2026-123"


def test_active_ticket_from_legacy_active_ticket_field() -> None:
    content = "- **Ticket activo:** WT-2026-208"

    assert _active_ticket_from_work_plan_content(content) == "WT-2026-208"


def test_active_ticket_returns_none_without_ticket_marker() -> None:
    assert _active_ticket_from_work_plan_content("- **Estado:** DRAFT") is None
