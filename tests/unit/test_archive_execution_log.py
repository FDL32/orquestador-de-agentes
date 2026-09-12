"""Tests for scripts/archive_execution_log.py — idempotency + keep boundary."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location(
    "archive_execution_log",
    PROJECT_ROOT / "scripts" / "archive_execution_log.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _build_log(n: int) -> str:
    """Build an execution_log with N WP sections (oldest first, newest last)."""
    header = "# Execution Log - orquestador_de_agentes\n\n**Estado:** TEST\n\n"
    sections = [
        f"### WP-2026-{i:03d} - test ticket {i}\n**Estado:** COMPLETED\nbody line {i}\n\n---\n\n"
        for i in range(1, n + 1)
    ]
    return header + "".join(sections)


def test_below_keep_threshold_no_archive(tmp_path: Path) -> None:
    log = tmp_path / "execution_log.md"
    log.write_text(_build_log(5), encoding="utf-8")
    archived = mod.archive_execution_log(log, keep_sections=10, dry_run=False)
    assert archived == 0
    assert not (tmp_path / "archive").exists() or not any(
        (tmp_path / "archive").iterdir()
    )


def test_keeps_boundary_correctly(tmp_path: Path) -> None:
    log = tmp_path / "execution_log.md"
    log.write_text(_build_log(12), encoding="utf-8")
    archived = mod.archive_execution_log(log, keep_sections=10, dry_run=False)
    assert archived == 2
    remaining = log.read_text(encoding="utf-8")
    # The 10 newest must survive in the active log
    for i in range(3, 13):
        assert f"### WP-2026-{i:03d}" in remaining, f"missing WP-{i:03d} in active log"
    # The 2 oldest must NOT be in the active log
    for i in (1, 2):
        assert f"### WP-2026-{i:03d}" not in remaining, (
            f"WP-{i:03d} should have been archived"
        )
    # And must be in the archive file
    archive_files = list((tmp_path / "archive").glob("execution_log_*.md"))
    assert len(archive_files) == 1
    archive_content = archive_files[0].read_text(encoding="utf-8")
    assert "### WP-2026-001" in archive_content
    assert "### WP-2026-002" in archive_content


def test_idempotent_second_run_archives_zero(tmp_path: Path) -> None:
    log = tmp_path / "execution_log.md"
    log.write_text(_build_log(12), encoding="utf-8")
    first = mod.archive_execution_log(log, keep_sections=10, dry_run=False)
    second = mod.archive_execution_log(log, keep_sections=10, dry_run=False)
    assert first == 2
    assert second == 0


def test_dry_run_does_not_modify_disk(tmp_path: Path) -> None:
    log = tmp_path / "execution_log.md"
    original = _build_log(15)
    log.write_text(original, encoding="utf-8")
    would_archive = mod.archive_execution_log(log, keep_sections=10, dry_run=True)
    assert would_archive == 5
    # File must not be modified
    assert log.read_text(encoding="utf-8") == original
    # No archive dir created
    assert not (tmp_path / "archive").exists()


# --------------------------------------------------------------------------- #
# WOT-2026-068d — the archiver publishes its DENOMINATOR (protocol D1/D2).
#
# These tests drive the REAL CLI (`main()`) because the protocol is emitted on
# stdout there; the return value and disk effects stay covered above.
# --------------------------------------------------------------------------- #

SCRIPT = PROJECT_ROOT / "scripts" / "archive_execution_log.py"

# Format-blind log: the real shape (H1 title + H2 ticket + H3 subsection), none
# recognized by SECTION_RE (which requires `### <TICKET>`).
FORMAT_BLIND = "# Execution Log\n## WOT-2026-068d\n### Bootstrap\n"

# Positive control: TWO recognized sections + two duplicated non-ticket H2.
TWO_SECTIONS = (
    "# Execution Log\n"
    "### WP-2026-001 - old\n"
    "old body\n"
    "## Nota\n"
    "## Nota\n"
    "### WP-2026-002 - new\n"
    "new body\n"
)


def _run_cli(log: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--execution-log", str(log), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_denominator_visible_when_no_section_recognized(tmp_path: Path) -> None:
    """D5: the format-blind no-op publishes recognized=0 / present>0."""
    log = tmp_path / "execution_log.md"
    log.write_text(FORMAT_BLIND, encoding="utf-8")
    result = _run_cli(log)
    assert result.returncode == 0, result.stderr
    assert "COUNTS archived=0 recognized=0 present=3" in result.stdout
    assert 'SKIPPED ["# Execution Log", "## WOT-2026-068d", "### Bootstrap"]' in (
        result.stdout
    )
    assert "CONTENT state=nonempty" in result.stdout


def test_positive_control_reports_effect_and_skipped(tmp_path: Path) -> None:
    """D1: when it DOES archive, the counts and the skipped list are correct."""
    log = tmp_path / "execution_log.md"
    log.write_text(TWO_SECTIONS, encoding="utf-8")
    result = _run_cli(log, "--keep", "1")
    assert result.returncode == 0, result.stderr
    assert "COUNTS archived=1 recognized=2 present=5" in result.stdout
    assert 'SKIPPED ["# Execution Log", "## Nota", "## Nota"]' in result.stdout
    assert "CONTENT state=nonempty" in result.stdout
    archived = next((tmp_path / "archive").glob("execution_log_*.md"))
    assert "### WP-2026-001" in archived.read_text(encoding="utf-8")
    assert "### WP-2026-002" in log.read_text(encoding="utf-8")


def test_dry_run_publishes_zero_effect_and_keeps_bytes(tmp_path: Path) -> None:
    """D2: dry-run reports archived=0 while the return forecast is not published."""
    log = tmp_path / "execution_log.md"
    log.write_text(TWO_SECTIONS, encoding="utf-8")
    result = _run_cli(log, "--keep", "1", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "COUNTS archived=0 recognized=2 present=5" in result.stdout
    assert 'SKIPPED ["# Execution Log", "## Nota", "## Nota"]' in result.stdout
    assert log.read_text(encoding="utf-8") == TWO_SECTIONS
    assert not (tmp_path / "archive").exists()


def test_empty_universe_reports_empty_state(tmp_path: Path) -> None:
    """D1: a genuinely empty log is the ONLY `state=empty` PASS case."""
    log = tmp_path / "execution_log.md"
    log.write_text("   \n", encoding="utf-8")
    result = _run_cli(log)
    assert result.returncode == 0, result.stderr
    assert "COUNTS archived=0 recognized=0 present=0" in result.stdout
    assert "SKIPPED []" in result.stdout
    assert "CONTENT state=empty" in result.stdout


def test_read_failure_is_unavailable_and_rc1(tmp_path: Path) -> None:
    """D1: an unreadable log fails closed and never claims an empty universe."""
    result = _run_cli(tmp_path / "nope.md")
    assert result.returncode == 1
    assert "COUNTS archived=0 recognized=0 present=0" in result.stdout
    assert "SKIPPED []" in result.stdout
    assert "CONTENT state=unavailable" in result.stdout


def test_invalid_utf8_log_is_unavailable(tmp_path: Path) -> None:
    """D1: UnicodeError on the log read is also `unavailable`, not empty."""
    log = tmp_path / "execution_log.md"
    log.write_bytes(b"# Execution Log\n### WP-2026-001\n\xff\xfe\n")
    result = _run_cli(log)
    assert result.returncode == 1
    assert "CONTENT state=unavailable" in result.stdout


def test_post_read_error_is_not_reclassified(tmp_path: Path) -> None:
    """D1: an error AFTER a successful log read must not become `unavailable`."""
    log = tmp_path / "execution_log.md"
    log.write_text(TWO_SECTIONS, encoding="utf-8")
    bad_archive = mod._archive_path(log)
    bad_archive.parent.mkdir(parents=True, exist_ok=True)
    bad_archive.write_bytes(b"### WP-2026-001\n\xff\n")
    before_log = log.read_bytes()
    before_archive = bad_archive.read_bytes()

    result = _run_cli(log, "--keep", "1")

    assert result.returncode != 0
    assert "CONTENT state=unavailable" not in result.stdout
    assert log.read_bytes() == before_log
    assert bad_archive.read_bytes() == before_archive
