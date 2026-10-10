"""Contract tests for scripts/check_promotion_provenance.py (WOT-2026-041g).

Verifies that the provenance guard correctly:
1. Passes (exit 0) when all entries have valid promoted_via.
2. Fails (exit != 0) when an entry is missing promoted_via.
3. Fails (exit != 0) when an entry has an invalid promoted_via value.

Mutation-verify: three cases as required by WOT-2026-041g DoD (d):
(i) A canonically-promoted entry passes.
(ii) A directly-injected entry (without going through writer functions) fails.
(iii) An entry with an invented promoted_via value fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_promotion_provenance.py"
)

ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")

EXIT_OK = 0
EXIT_PROVENANCE_INVALID = 4


def _make_archive_dir(tmp_path: Path) -> Path:
    """Create a minimal git repo with an archive directory on tmp_path."""
    archive = tmp_path / ARCHIVE_DIR_REL
    archive.mkdir(parents=True)
    # Make it a git repo (required by the guard)
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    (tmp_path / "README").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return archive


def _write_entries(archive: Path, month: str, entries: list[dict]) -> None:
    """Write entries to an archive file for the given month."""
    path = archive / f"observations.{month}.jsonl"
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in entries),
        encoding="utf-8",
        newline="\n",
    )


def _run_provenance(root: Path) -> subprocess.CompletedProcess:
    """Run the provenance guard against a root directory."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--motor-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_entry(
    topic: str = "test-topic",
    ticket: str = "WOT-2026-999x",
    promoted_via: str | None = None,
) -> dict:
    """Create a minimal observation entry."""
    entry: dict = {
        "id": f"obs-test-{topic}-{ticket}",
        "timestamp": "2026-07-12T10:00:00Z",
        "topic": topic,
        "signal": f"signal for {topic}",
        "source_ticket": ticket,
        "applies_to": "all",
        "confidence": 0.9,
        "domain": "testing",
        "recommended_followup": "n/a",
    }
    if promoted_via is not None:
        entry["promoted_via"] = promoted_via
    return entry


def test_exit_0_when_all_entries_have_valid_promoted_via(tmp_path: Path) -> None:
    """All entries have valid promoted_via -> exit 0."""
    archive = _make_archive_dir(tmp_path)
    entries = [
        _make_entry("via-1", "WOT-2026-999a", "reconcile_curated"),
        _make_entry("via-2", "WOT-2026-999b", "reconcile_batch"),
        _make_entry("via-3", "WOT-2026-999c", "memory_consolidate_auto"),
        _make_entry("via-4", "WOT-2026-999d", "legacy_backfill"),
    ]
    _write_entries(archive, "2026-07", entries)

    result = _run_provenance(tmp_path)
    assert result.returncode == EXIT_OK, (
        f"Expected exit 0 but got {result.returncode}. stderr: {result.stderr}"
    )


def test_exit_nonzero_when_entry_missing_promoted_via(tmp_path: Path) -> None:
    """Entry without promoted_via -> exit != 0, naming the id."""
    archive = _make_archive_dir(tmp_path)
    entries = [
        _make_entry("clean", "WOT-2026-998a", "reconcile_curated"),
        _make_entry("missing", "WOT-2026-998b", None),
    ]
    _write_entries(archive, "2026-07", entries)

    result = _run_provenance(tmp_path)
    assert result.returncode != EXIT_OK, (
        f"Expected non-zero exit but got {result.returncode}"
    )
    assert "falta promoted_via" in result.stderr, (
        f"Expected 'falta promoted_via' in stderr but got: {result.stderr}"
    )
    assert "WOT-2026-998b" in result.stderr, (
        f"Expected ticket ID in stderr but got: {result.stderr}"
    )


def test_exit_nonzero_when_entry_has_invented_promoted_via(tmp_path: Path) -> None:
    """Entry with invented promoted_via value -> exit != 0."""
    archive = _make_archive_dir(tmp_path)
    entries = [
        _make_entry("valid", "WOT-2026-997a", "reconcile_curated"),
        _make_entry("invented", "WOT-2026-997b", "lo-que-sea"),
    ]
    _write_entries(archive, "2026-07", entries)

    result = _run_provenance(tmp_path)
    assert result.returncode != EXIT_OK, (
        f"Expected non-zero exit but got {result.returncode}"
    )
    assert "lo-que-sea" in result.stderr, (
        f"Expected invented value in stderr but got: {result.stderr}"
    )


def test_no_archive_files_returns_ok(tmp_path: Path) -> None:
    """No archive files -> exit 0 (not a finding)."""
    _make_archive_dir(tmp_path)

    result = _run_provenance(tmp_path)
    assert result.returncode == EXIT_OK, (
        f"Expected exit 0 but got {result.returncode}. stderr: {result.stderr}"
    )


def test_mutate_injected_entry_fails(tmp_path: Path) -> None:
    """Entry injected DIRECTLY into archive (without writer function) -> guard FAILS.

    This reproduces case (ii) from WOT-2026-041g DoD (d): an entry written
    directly to disk, bypassing the promotion path, is detected.
    """
    archive = _make_archive_dir(tmp_path)
    # Entry written directly to archive without promoted_via
    entry = _make_entry("injected", "WOT-2026-996a", None)
    _write_entries(archive, "2026-07", [entry])

    result = _run_provenance(tmp_path)
    assert result.returncode != EXIT_OK, (
        f"Expected guard to FAIL for directly-injected entry, got {result.returncode}"
    )
    assert "WOT-2026-996a" in result.stderr, (
        f"Expected entry ID in stderr: {result.stderr}"
    )


def test_three_promoted_via_values_are_distinct() -> None:
    """The three writer promoted_via values are distinct."""
    from scripts.memory_consolidate import PROMOTED_VIA_ARCHIVE_AUTO
    from scripts.reconcile_portable_memory import (
        PROMOTED_VIA_ACCEPTED,
        PROMOTED_VIA_BATCH,
        PROMOTED_VIA_CURATED,
    )

    assert PROMOTED_VIA_CURATED != PROMOTED_VIA_BATCH, (
        "reconcile_curated and reconcile_batch must be distinct"
    )
    assert PROMOTED_VIA_CURATED != PROMOTED_VIA_ARCHIVE_AUTO, (
        "reconcile_curated and memory_consolidate_auto must be distinct"
    )
    assert PROMOTED_VIA_BATCH != PROMOTED_VIA_ARCHIVE_AUTO, (
        "reconcile_batch and memory_consolidate_auto must be distinct"
    )
    assert PROMOTED_VIA_CURATED in PROMOTED_VIA_ACCEPTED
    assert PROMOTED_VIA_BATCH in PROMOTED_VIA_ACCEPTED
    assert PROMOTED_VIA_ARCHIVE_AUTO in PROMOTED_VIA_ACCEPTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
