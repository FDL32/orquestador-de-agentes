#!/usr/bin/env python3
"""Tests for session_close_observations.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts.session_close_observations import (
    VALID_CATEGORIES,
    is_duplicate,
    is_noise,
    parse_timestamp,
    process_candidates,
    validate_schema,
)


def test_is_noise_tool_called() -> None:
    """Tool X called patterns should be dropped."""
    assert is_noise("Tool view_file called") is True
    assert is_noise("Tool bash called") is True
    assert is_noise("  Tool edit called  ") is True


def test_is_noise_short_entry() -> None:
    """Entries < 30 chars should be dropped."""
    assert is_noise("Short signal") is True
    assert is_noise("x" * 29) is True
    assert is_noise("x" * 30) is False


def test_is_noise_valid_entry() -> None:
    """Valid entries should not be marked as noise."""
    assert is_noise("This is a valid observation signal with enough length") is False
    assert is_noise("WP-2026-132 completed successfully after implementation") is False


def test_validate_schema_missing_field() -> None:
    """Schema validation should fail with missing required field."""
    entry = {
        "timestamp": "2026-05-25T12:00:00Z",
        "signal": "Test signal",
        # Missing: category, source_ticket, topic, source
    }
    is_valid, errors = validate_schema(entry)
    assert is_valid is False
    assert any("Campo requerido ausente" in e for e in errors)


def test_validate_schema_invalid_category() -> None:
    """Schema validation should fail with invalid category."""
    entry = {
        "timestamp": "2026-05-25T12:00:00Z",
        "signal": "This is a valid signal with enough length",
        "category": "opinion",  # Invalid
        "source_ticket": "WP-2026-132",
        "topic": "test",
        "source": "session-close"
    }
    is_valid, errors = validate_schema(entry)
    assert is_valid is False
    assert any("Categoria invalida" in e for e in errors)


def test_validate_schema_valid() -> None:
    """Schema validation should pass with valid entry."""
    entry = {
        "timestamp": "2026-05-25T12:00:00Z",
        "signal": "This is a valid observation signal with enough length",
        "category": "fact",
        "source_ticket": "WP-2026-132",
        "topic": "test",
        "source": "session-close"
    }
    is_valid, errors = validate_schema(entry)
    assert is_valid is True
    assert errors == []


def test_validate_schema_short_signal() -> None:
    """Schema validation should fail with signal < 30 chars."""
    entry = {
        "timestamp": "2026-05-25T12:00:00Z",
        "signal": "Short",
        "category": "fact",
        "source_ticket": "WP-2026-132",
        "topic": "test",
        "source": "session-close"
    }
    is_valid, errors = validate_schema(entry)
    assert is_valid is False
    assert any("Signal muy corto" in e for e in errors)


def test_is_duplicate_exact_match() -> None:
    """Exact duplicate within 24h should be detected."""
    now = datetime.now(timezone.utc)
    existing = [
        {
            "timestamp": now.isoformat(),
            "signal": "Test signal",
            "category": "fact",
            "source_ticket": "WP-2026-132",
            "topic": "test",
            "source": "builder"
        }
    ]

    candidate = {
        "timestamp": (now + timedelta(hours=1)).isoformat(),
        "signal": "Test signal",
        "category": "fact",
        "source_ticket": "WP-2026-133",
        "topic": "test",
        "source": "session-close"
    }

    assert is_duplicate(candidate, existing) is True


def test_is_duplicate_different_signal() -> None:
    """Different signal should not be duplicate."""
    now = datetime.now(timezone.utc)
    existing = [
        {
            "timestamp": now.isoformat(),
            "signal": "Test signal A",
            "category": "fact",
            "source_ticket": "WP-2026-132",
            "topic": "test",
            "source": "builder"
        }
    ]

    candidate = {
        "timestamp": (now + timedelta(hours=1)).isoformat(),
        "signal": "Test signal B",
        "category": "fact",
        "source_ticket": "WP-2026-133",
        "topic": "test",
        "source": "session-close"
    }

    assert is_duplicate(candidate, existing) is False


def test_is_duplicate_outside_window() -> None:
    """Duplicate outside 24h window should not be detected."""
    now = datetime.now(timezone.utc)
    existing = [
        {
            "timestamp": now.isoformat(),
            "signal": "Test signal",
            "category": "fact",
            "source_ticket": "WP-2026-132",
            "topic": "test",
            "source": "builder"
        }
    ]

    candidate = {
        "timestamp": (now + timedelta(hours=48)).isoformat(),
        "signal": "Test signal",
        "category": "fact",
        "source_ticket": "WP-2026-133",
        "topic": "test",
        "source": "session-close"
    }

    assert is_duplicate(candidate, existing) is False


def test_process_candidates_filters_invalid() -> None:
    """Process should filter out invalid candidates."""
    candidates = [
        {
            "timestamp": "2026-05-25T12:00:00Z",
            "signal": "Short",  # Too short
            "category": "fact",
            "source_ticket": "WP-2026-132",
            "topic": "test",
            "source": "session-close"
        }
    ]
    existing = []

    appended, rejected_reasons = process_candidates(candidates, existing)
    assert len(appended) == 0
    assert len(rejected_reasons) > 0


def test_process_candidates_accepts_valid() -> None:
    """Process should accept valid candidates."""
    candidates = [
        {
            "timestamp": "2026-05-25T12:00:00Z",
            "signal": "This is a valid observation with enough length",
            "category": "fact",
            "source_ticket": "WP-2026-132",
            "topic": "test",
            "source": "session-close"
        }
    ]
    existing = []

    appended, rejected_reasons = process_candidates(candidates, existing)
    assert len(appended) == 1
    assert len(rejected_reasons) == 0


def test_parse_timestamp_with_z() -> None:
    """Parse timestamp with Z suffix."""
    ts = parse_timestamp("2026-05-25T12:00:00Z")
    assert ts.tzinfo is not None


def test_parse_timestamp_with_offset() -> None:
    """Parse timestamp with timezone offset."""
    ts = parse_timestamp("2026-05-25T12:00:00+00:00")
    assert ts.tzinfo is not None


def test_valid_categories() -> None:
    """Test that VALID_CATEGORIES contains expected values."""
    assert {"convention", "decision", "fact", "pattern"} == VALID_CATEGORIES


def test_extract_candidates_from_ticket_unknown_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Extract candidates returns empty list when ticket ID not found in work_plan."""
    fake_plan = tmp_path / "work_plan.md"
    fake_plan.write_text("# Work Plan - WP-2026-001\n## Metadata\n- **ID:** WP-2026-001\n", encoding="utf-8")

    import scripts.session_close_observations as sco
    monkeypatch.setattr(sco, "AGENT_DIR", tmp_path)

    candidates = sco.extract_candidates_from_ticket("WP-2026-999")
    assert len(candidates) == 0
