#!/usr/bin/env python3
"""Tests for session_close_observations.py."""

from __future__ import annotations

import sys
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


# =============================================================================
# Tests para load_candidates_from_file (WP-2026-136)
# =============================================================================

def test_load_candidates_from_file_valid_json(tmp_path: Path) -> None:
    """load_candidates_from_file returns list of dicts with valid JSON."""
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        '[{"signal": "Test signal 1", "category": "fact"}, '
        '{"signal": "Test signal 2", "category": "decision"}]',
        encoding="utf-8"
    )

    import scripts.session_close_observations as sco
    result = sco.load_candidates_from_file(str(candidates_file))

    assert len(result) == 2
    assert result[0]["signal"] == "Test signal 1"
    assert result[1]["category"] == "decision"


def test_load_candidates_from_file_file_not_found() -> None:
    """load_candidates_from_file raises FileNotFoundError when file absent."""
    import scripts.session_close_observations as sco

    with pytest.raises(FileNotFoundError, match="Candidates file not found"):
        sco.load_candidates_from_file("/nonexistent/path/candidates.json")


def test_load_candidates_from_file_invalid_json(tmp_path: Path) -> None:
    """load_candidates_from_file raises ValueError with corrupt JSON."""
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text('{"invalid": json, broken}', encoding="utf-8")

    import scripts.session_close_observations as sco

    with pytest.raises(ValueError, match="JSON decode error"):
        sco.load_candidates_from_file(str(candidates_file))


def test_load_candidates_from_file_top_level_not_list(tmp_path: Path) -> None:
    """load_candidates_from_file raises ValueError if top-level is not list."""
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text('{"not": "a list"}', encoding="utf-8")

    import scripts.session_close_observations as sco

    with pytest.raises(ValueError, match="Expected list, got"):
        sco.load_candidates_from_file(str(candidates_file))


def test_load_candidates_from_file_skips_non_dict_elements(tmp_path: Path, capsys) -> None:
    """load_candidates_from_file skips non-dict elements with warning."""
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        '[{"signal": "Valid"}, "string element", 123, null, {"signal": "Also valid"}]',
        encoding="utf-8"
    )

    import scripts.session_close_observations as sco
    result = sco.load_candidates_from_file(str(candidates_file))

    assert len(result) == 2
    assert result[0]["signal"] == "Valid"
    assert result[1]["signal"] == "Also valid"

    captured = capsys.readouterr()
    assert "Warning: Skipping element" in captured.out


def test_main_mutually_exclusive_args(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    """argparse enforces mutual exclusion between --ticket and --candidates."""
    import scripts.session_close_observations as sco

    # Both flags should raise SystemExit due to mutually_exclusive_group(required=True)
    monkeypatch.setattr(sys, "argv", ["session_close_observations.py", "--ticket", "WP-2026-001", "--candidates", "file.json"])

    with pytest.raises(SystemExit):
        sco.main()

    # No flags should also raise SystemExit
    monkeypatch.setattr(sys, "argv", ["session_close_observations.py"])

    with pytest.raises(SystemExit):
        sco.main()


def test_main_with_candidates_flag_does_not_call_extract_from_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() with --candidates does not call extract_candidates_from_ticket."""
    import scripts.session_close_observations as sco

    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        '[{"timestamp": "2026-05-25T12:00:00Z", "signal": "This is a valid signal with enough length", '
        '"category": "fact", "source_ticket": "WP-2026-136", "topic": "test", "source": "test"}]',
        encoding="utf-8"
    )

    # Patch extract_candidates_from_ticket to verify it's NOT called
    called = {"count": 0}
    original_extract = sco.extract_candidates_from_ticket

    def patched_extract(ticket_id: str) -> list:
        called["count"] += 1
        return original_extract(ticket_id)

    monkeypatch.setattr(sco, "extract_candidates_from_ticket", patched_extract)
    monkeypatch.setattr(sys, "argv", [
        "session_close_observations.py",
        "--candidates", str(candidates_file),
        "--dry-run",
        "--verbose"
    ])

    # Patch MEMORY_DIR to use tmp_path
    monkeypatch.setattr(sco, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(sco, "OBS_FILE", tmp_path / "observations.jsonl")
    monkeypatch.setattr(sco, "REPORT_FILE", tmp_path / "report.md")

    exit_code = sco.main()

    assert exit_code == 0
    assert called["count"] == 0  # extract_candidates_from_ticket was NOT called


def test_load_candidates_from_file_invalid_utf8(tmp_path: Path) -> None:
    """load_candidates_from_file raises ValueError for invalid UTF-8 bytes (strict mode)."""
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_bytes(b'[{"signal": "ok"}' + b"\xff\xfe" + b"]")

    import scripts.session_close_observations as sco

    with pytest.raises(ValueError, match="UTF-8 decode error"):
        sco.load_candidates_from_file(str(candidates_file))


def test_main_empty_candidates_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() with --candidates pointing to an empty list exits 0 (not an error)."""
    import scripts.session_close_observations as sco

    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "session_close_observations.py",
        "--candidates", str(candidates_file),
        "--dry-run",
    ])
    monkeypatch.setattr(sco, "OBS_FILE", tmp_path / "observations.jsonl")
    monkeypatch.setattr(sco, "REPORT_FILE", tmp_path / "report.md")

    exit_code = sco.main()

    assert exit_code == 0
