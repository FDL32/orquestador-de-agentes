#!/usr/bin/env python3
"""Tests for memory_consolidate.py."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.memory_consolidate import (
    ARCHIVE_DIR,
    DEDUPE_WINDOW_HOURS,
    MEMORY_DIR,
    MEMORY_MD,
    MEMORY_MD_LINE_CAP,
    OBS,
    REPORT,
    dedupe,
    is_noise,
    parse_entries,
    regen_memory_md,
    split_by_age,
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
    assert is_noise("WP-2026-083 completed successfully after implementation") is False


def test_dedupe_within_window() -> None:
    """Two identical entries within 24h should result in one (newest kept)."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=12)
    entries = [
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": older.isoformat(),
        },
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result, dropped = dedupe(entries)
    assert len(result) == 1
    assert dropped == 1
    assert result[0]["timestamp"] == now.isoformat()


def test_dedupe_outside_window() -> None:
    """Two identical entries > 24h apart should both be kept."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=48)
    entries = [
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": older.isoformat(),
        },
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result, dropped = dedupe(entries)
    assert len(result) == 2
    assert dropped == 0


def test_split_by_age() -> None:
    """Entries older than cutoff should be in archivable list."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=10)
    old = now - timedelta(days=45)
    entries = [
        {"signal": "Recent", "timestamp": recent.isoformat()},
        {"signal": "Old", "timestamp": old.isoformat()},
    ]
    recent_list, archivable = split_by_age(entries, days=30)
    assert len(recent_list) == 1
    assert recent_list[0]["signal"] == "Recent"
    assert len(archivable) == 1
    assert archivable[0]["signal"] == "Old"


def test_regen_memory_md() -> None:
    """MEMORY.md should be regenerated with proper structure."""
    now = datetime.now(timezone.utc)
    entries = [
        {
            "signal": "Test signal A",
            "topic": "test_topic",
            "timestamp": now.isoformat(),
            "source": "builder",
        },
        {
            "signal": "Test signal B",
            "topic": "test_topic",
            "timestamp": now.isoformat(),
            "source": "builder",
        },
    ]
    stats = {"kept": 2, "deduped": 0, "dropped": 1, "archived": 0}
    content = regen_memory_md(entries, stats)
    assert "# MEMORY" in content
    assert "Regenerated:" in content
    assert "Total observations: 2" in content
    assert "## test_topic" in content
    assert "Test signal A" in content
    assert "Test signal B" in content
    assert "kept=2" in content


def test_parse_entries_empty_file(tmp_path: Path) -> None:
    """Parse empty file returns empty list."""
    test_file = tmp_path / "empty.jsonl"
    test_file.write_text("", encoding="utf-8")
    result = parse_entries(test_file)
    assert result == []


def test_parse_entries_malformed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Malformed JSON lines are skipped with warning."""
    test_file = tmp_path / "malformed.jsonl"
    test_file.write_text(
        '{"valid": "entry"}\nnot json at all\n{"another": "valid"}\n',
        encoding="utf-8",
    )
    result = parse_entries(test_file)
    assert len(result) == 2
    captured = capsys.readouterr()
    assert "Warning: Skipping malformed JSON" in captured.out


def test_idempotency(tmp_path: Path) -> None:
    """Running dedupe twice on stable input produces same result."""
    now = datetime.now(timezone.utc)
    entries = [
        {
            "signal": "Unique signal A",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
        {
            "signal": "Unique signal B",
            "source": "manager",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result1, _ = dedupe(entries)
    result2, _ = dedupe(result1)
    assert len(result1) == len(result2)
    assert [e["signal"] for e in result1] == [e["signal"] for e in result2]


def test_dry_run_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run mode should not write any files."""
    test_obs = tmp_path / "observations.jsonl"
    original_content = '{"test": "entry"}\n'
    test_obs.write_text(original_content, encoding="utf-8")

    test_memory_md = tmp_path / "MEMORY.md"
    test_report = tmp_path / "REPORT.md"
    test_archive = tmp_path / "archive"

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", test_archive)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", test_memory_md)
    monkeypatch.setattr("scripts.memory_consolidate.REPORT", test_report)

    from scripts import memory_consolidate
    import sys

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py"])

    memory_consolidate.main()

    assert test_obs.read_text(encoding="utf-8") == original_content
    assert not test_memory_md.exists()
    assert test_report.exists()
    assert "DRY-RUN" in test_report.read_text(encoding="utf-8")


def test_regen_memory_md_line_cap() -> None:
    """MEMORY.md should be capped at MEMORY_MD_LINE_CAP (80) lines.

    Generates an artificially large number of entries to force the index
    to exceed the cap, then verifies truncation with visible marker.
    """
    now = datetime.now(timezone.utc)
    # Create enough entries to exceed 80 lines
    # Each entry in the output takes ~2 lines (topic header + signal)
    # Plus index and summary sections (~20 lines)
    # So we need ~100 entries to safely exceed the cap
    entries = [
        {
            "signal": f"Test signal {i} with enough text to be meaningful",
            "topic": f"topic_{i % 10}",  # 10 different topics
            "timestamp": now.isoformat(),
            "source": "builder",
        }
        for i in range(100)
    ]
    stats = {"kept": 100, "deduped": 0, "dropped": 0, "archived": 0}
    content = regen_memory_md(entries, stats)
    lines = content.split("\n")

    # Verify cap is enforced
    assert len(lines) <= MEMORY_MD_LINE_CAP, (
        f"MEMORY.md has {len(lines)} lines, exceeds cap of {MEMORY_MD_LINE_CAP}"
    )

    # Verify truncation marker is present when capped
    assert "[MEMORY.md truncated at" in content
    assert "Full history available in observations.jsonl" in content

    # Verify structure is still valid (header and index always present)
    assert "# MEMORY" in content
    assert "Regenerated:" in content
    assert "Total observations: 100" in content
