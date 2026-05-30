#!/usr/bin/env python3
"""Tests for memory_consolidate.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts.memory_consolidate import (
    MEMORY_MD_LINE_CAP,
    dedupe,
    generate_memory_profile_md,
    generate_memory_rules_md,
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

    import sys

    from scripts import memory_consolidate

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py"])

    memory_consolidate.main()

    assert test_obs.read_text(encoding="utf-8") == original_content
    assert not test_memory_md.exists()
    assert test_report.exists()
    assert "DRY-RUN" in test_report.read_text(encoding="utf-8")


def test_dry_run_flag_alias_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run should be accepted as an explicit CLI alias."""
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

    import sys

    from scripts import memory_consolidate

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py", "--dry-run"])

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


# =============================================================================
# Tests WP-2026-178: L2 memory rules generation
# =============================================================================


def test_generate_memory_rules_md_empty() -> None:
    """Empty entries produce L2 header with no rules."""
    content = generate_memory_rules_md([])
    assert "# Memory Rules (L2)" in content
    assert "Total rules: 0" in content
    assert "No rules extracted yet" in content


def test_generate_memory_rules_md_with_rules() -> None:
    """Entries with rule-like signals produce parseable L2 rules."""
    entries = [
        {
            "signal": "When refactoring a method return type from None to bool, "
            "always use 'is False' guards in callers rather than truthiness (AP-05).",
            "topic": "testing",
            "source_ticket": "WP-2026-137",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "human_audit",
        },
        {
            "signal": "Security gates must fail closed (exit 2 / raise) on invalid "
            "or unknown config. Silent permissive fallback is dangerous (AP-11).",
            "topic": "security",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "human_audit",
            "domain": "security-gates",
        },
        {
            "signal": "Short signal",  # Too short, should be skipped
            "topic": "general",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "builder",
        },
    ]
    content = generate_memory_rules_md(entries)

    # L2 header present
    assert "# Memory Rules (L2)" in content
    assert "Total rules: 2" in content  # Short signal filtered out

    # Parseable domain sections
    assert "## Domain: security-gates" in content
    assert "## Domain: testing" in content

    # Rule IDs present
    assert "### R-001:" in content
    assert "### R-002:" in content

    # Source tickets present
    assert "WP-2026-154" in content
    assert "WP-2026-137" in content

    # Short signal excluded
    assert "Short signal" not in content


def test_generate_memory_rules_md_deterministic() -> None:
    """Two runs on same data produce identical L2 rules."""
    entries = [
        {
            "signal": "Always use 'is False' guards when return type changes from None to bool. "
            "This avoids silent breakage with monkeypatched mocks in tests.",
            "topic": "testing",
            "source_ticket": "WP-2026-137",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "human_audit",
        },
        {
            "signal": "Security gates must fail closed. Silent fallback on unknown "
            "config is more dangerous than explicit block.",
            "topic": "security",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "human_audit",
            "domain": "security-gates",
        },
    ]
    content1 = generate_memory_rules_md(entries)
    content2 = generate_memory_rules_md(entries)
    assert content1 == content2


def test_generate_memory_rules_md_allows_explicit_domain() -> None:
    """Entries with explicit 'domain' field qualify even without rule keywords."""
    entries = [
        {
            "signal": "A longer signal that has no rule keywords but carries a domain. "
            "Domain fields make any entry rule-eligible regardless of style.",
            "topic": "architecture",
            "domain": "bus-architecture",
            "source_ticket": "WP-2026-178",
            "timestamp": "2026-05-30T10:00:00Z",
            "source": "test",
        },
    ]
    content = generate_memory_rules_md(entries)
    assert "Total rules: 1" in content
    assert "## Domain: bus-architecture" in content


# =============================================================================
# Tests WP-2026-178: L3 memory profile generation
# =============================================================================


def test_generate_memory_profile_md_empty() -> None:
    """Empty entries produce L3 header with zero counts."""
    content = generate_memory_profile_md([])
    assert "# Memory Profile (L3)" in content
    assert "Total observations: 0" in content
    assert "Active Domains" in content


def test_generate_memory_profile_md_with_entries() -> None:
    """Entries produce profile with domains, tickets, and recent signals."""
    entries = [
        {
            "signal": "First rule about testing.",
            "topic": "testing",
            "source_ticket": "WP-2026-100",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "audit",
        },
        {
            "signal": "Security finding with longer signal text.",
            "topic": "security",
            "domain": "security-gates",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "audit",
        },
        {
            "signal": "Architecture decision recorded.",
            "topic": "architecture",
            "source_ticket": "WP-2026-175",
            "timestamp": "2026-05-29T10:00:00Z",
            "source": "session-close",
        },
    ]
    content = generate_memory_profile_md(entries)

    # Header
    assert "# Memory Profile (L3)" in content
    assert "Total observations: 3" in content

    # Active Domains section
    assert "## Active Domains" in content

    # Active Tickets Referenced section
    assert "## Active Tickets Referenced" in content
    assert "WP-2026-100" in content
    assert "WP-2026-154" in content
    assert "WP-2026-175" in content

    # Recent Signals section
    assert "## Recent Signals" in content
    # Most recent entry should appear
    assert "Architecture decision recorded" in content or "session-close" in content
