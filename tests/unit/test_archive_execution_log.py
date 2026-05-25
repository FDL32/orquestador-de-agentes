"""Tests for scripts/archive_execution_log.py — idempotency + keep boundary."""

from __future__ import annotations

import importlib.util
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
