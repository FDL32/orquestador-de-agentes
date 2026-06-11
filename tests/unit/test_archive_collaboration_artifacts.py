"""Tests for scripts/archive_collaboration_artifacts.py.

Tests verify:
- Idempotency: running twice does not duplicate or error.
- Active-only: the current ticket's PLAN/AUDIT remain in place.
- Closed files are moved to the archive directory.
- No files are touched when all tickets are active (edge case).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location(
    "archive_collaboration_artifacts",
    PROJECT_ROOT / "scripts" / "archive_collaboration_artifacts.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _setup_collaboration_dir(
    tmp_path: Path, active_wp: str, closed_wps: list[str]
) -> Path:
    """Create a mock collaboration directory with active and closed PLAN/AUDIT files."""
    collab = tmp_path / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)

    # Create work_plan.md with active WP
    work_plan = collab / "work_plan.md"
    work_plan.write_text(
        f"# Work Plan\n\n**ID:** {active_wp}\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )

    # Create active ticket PLAN/AUDIT
    year, num = active_wp.replace("WP-", "").split("-")
    active_plan = collab / f"PLAN_WP-{year}-{num}.md"
    active_audit = collab / f"AUDIT_WP-{year}-{num}.md"
    active_plan.write_text(f"# PLAN {active_wp}\n", encoding="utf-8")
    active_audit.write_text(f"# AUDIT {active_wp}\n", encoding="utf-8")

    # Create closed ticket PLAN/AUDIT files
    for wp_id in closed_wps:
        year, num = wp_id.replace("WP-", "").split("-")
        plan = collab / f"PLAN_WP-{year}-{num}.md"
        audit = collab / f"AUDIT_WP-{year}-{num}.md"
        plan.write_text(f"# PLAN {wp_id}\n", encoding="utf-8")
        audit.write_text(f"# AUDIT {wp_id}\n", encoding="utf-8")

    # Create other active files
    (collab / "TURN.md").write_text("# TURN\n", encoding="utf-8")
    (collab / "STATE.md").write_text("# STATE\n", encoding="utf-8")
    (collab / "execution_log.md").write_text("# Execution Log\n", encoding="utf-8")

    return collab


def test_parse_wp_number() -> None:
    """Test WP number extraction from filenames."""
    assert mod.parse_wp_number("PLAN_WP-2026-100.md") == "WP-2026-100"
    assert mod.parse_wp_number("AUDIT_WP-2026-099.md") == "WP-2026-099"
    assert mod.parse_wp_number("work_plan.md") is None
    assert mod.parse_wp_number("TURN.md") is None
    # 4-digit suffix is now valid (canonical pattern accepts any alphanumeric suffix)
    assert mod.parse_wp_number("PLAN_WP-2026-1000.md") == "WP-2026-1000"


def test_get_active_wp(tmp_path: Path) -> None:
    """Test reading active WP from work_plan.md."""
    collab = tmp_path / "collaboration"
    collab.mkdir()
    work_plan = collab / "work_plan.md"

    work_plan.write_text(
        "# Plan\n\n**ID:** WP-2026-100\n**Estado:** IN_PROGRESS\n", encoding="utf-8"
    )
    assert mod.get_active_wp(collab) == "WP-2026-100"

    # Missing work_plan
    empty_collab = tmp_path / "empty"
    empty_collab.mkdir()
    assert mod.get_active_wp(empty_collab) is None


def test_find_closed_plan_audit_files(tmp_path: Path) -> None:
    """Test finding closed PLAN/AUDIT files."""
    collab = _setup_collaboration_dir(
        tmp_path, "WP-2026-100", ["WP-2026-099", "WP-2026-098"]
    )

    closed = mod.find_closed_plan_audit_files(collab, "WP-2026-100")
    assert len(closed) == 4  # PLAN + AUDIT for each closed WP

    filenames = {f.name for f in closed}
    assert "PLAN_WP-2026-099.md" in filenames
    assert "AUDIT_WP-2026-099.md" in filenames
    assert "PLAN_WP-2026-098.md" in filenames
    assert "AUDIT_WP-2026-098.md" in filenames
    assert "PLAN_WP-2026-100.md" not in filenames
    assert "AUDIT_WP-2026-100.md" not in filenames


def test_archive_closed_files(tmp_path: Path) -> None:
    """Test archiving closed PLAN/AUDIT files."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", ["WP-2026-099"])

    result = mod.archive_collaboration_artifacts(collab, dry_run=False)

    assert len(result["archived"]) == 2
    assert len(result["errors"]) == 0

    # Verify files moved to archive
    archive_dir = mod.get_archive_dir(collab)
    assert archive_dir.exists()
    assert (archive_dir / "PLAN_WP-2026-099.md").exists()
    assert (archive_dir / "AUDIT_WP-2026-099.md").exists()

    # Verify active files remain
    assert (collab / "PLAN_WP-2026-100.md").exists()
    assert (collab / "AUDIT_WP-2026-100.md").exists()
    assert (collab / "work_plan.md").exists()
    assert (collab / "TURN.md").exists()
    assert (collab / "STATE.md").exists()
    assert (collab / "execution_log.md").exists()

    # Verify closed files removed from active
    assert not (collab / "PLAN_WP-2026-099.md").exists()
    assert not (collab / "AUDIT_WP-2026-099.md").exists()


def test_idempotent_second_run_archives_zero(tmp_path: Path) -> None:
    """Test that running twice does not duplicate or error."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", ["WP-2026-099"])

    first = mod.archive_collaboration_artifacts(collab, dry_run=False)
    second = mod.archive_collaboration_artifacts(collab, dry_run=False)

    assert len(first["archived"]) == 2
    assert len(second["archived"]) == 0  # Nothing left to archive
    assert len(second["errors"]) == 0


def test_dry_run_does_not_modify_disk(tmp_path: Path) -> None:
    """Test that dry_run reports without moving files."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", ["WP-2026-099"])

    result = mod.archive_collaboration_artifacts(collab, dry_run=True)

    assert len(result["archived"]) == 2
    assert len(result["errors"]) == 0

    # Verify no files moved
    archive_dir = mod.get_archive_dir(collab)
    assert not archive_dir.exists()

    # All files still in place
    assert (collab / "PLAN_WP-2026-099.md").exists()
    assert (collab / "AUDIT_WP-2026-099.md").exists()


def test_no_closed_files_no_op(tmp_path: Path) -> None:
    """Test that no files are touched when all are active."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", [])

    result = mod.archive_collaboration_artifacts(collab, dry_run=False)

    assert len(result["archived"]) == 0
    assert len(result["errors"]) == 0
    assert not mod.get_archive_dir(collab).exists()


def test_list_active_collaboration_files(tmp_path: Path) -> None:
    """Test listing active collaboration files."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", ["WP-2026-099"])

    active = mod.list_active_collaboration_files(collab)

    assert "work_plan.md" in active
    assert "TURN.md" in active
    assert "STATE.md" in active
    assert "execution_log.md" in active
    assert "PLAN_WP-2026-100.md" in active
    assert "AUDIT_WP-2026-100.md" in active
    assert "PLAN_WP-2026-099.md" not in active
    assert "AUDIT_WP-2026-099.md" not in active


def test_archive_dir_creation(tmp_path: Path) -> None:
    """Test that archive directory is created when needed."""
    collab = _setup_collaboration_dir(tmp_path, "WP-2026-100", ["WP-2026-099"])

    # Remove any existing archive dir
    archive_dir = mod.get_archive_dir(collab)
    if archive_dir.exists():
        import shutil

        shutil.rmtree(archive_dir)

    result = mod.archive_collaboration_artifacts(collab, dry_run=False)

    assert len(result["archived"]) == 2
    assert archive_dir.exists()
    assert archive_dir.is_dir()


# ── WT-2026-250a: letter-suffix ticket names ──────────────────────────────────


def test_parse_wp_number_letter_suffix() -> None:
    """parse_wp_number must handle letter-suffix filenames introduced in WT-2026-221a."""
    # PLAN with letter suffix
    assert mod.parse_wp_number("PLAN_WT-2026-221a.md") == "WT-2026-221a"
    # AUDIT with letter+digit suffix (three-letter prefix)
    assert mod.parse_wp_number("AUDIT_WOT-2026-001b.md") == "WOT-2026-001b"
    # Old numeric-only still works
    assert mod.parse_wp_number("PLAN_WT-2026-221.md") == "WT-2026-221"
    # No match for unrelated files
    assert mod.parse_wp_number("manager_feedback_WT-2026-249b.md") is None


def test_extract_ticket_id_from_feedback_letter_suffix() -> None:
    """extract_ticket_id_from_feedback must handle letter-suffix IDs."""
    assert (
        mod.extract_ticket_id_from_feedback("manager_feedback_WT-2026-249b.md")
        == "WT-2026-249b"
    )
    # Numeric-only still works
    assert (
        mod.extract_ticket_id_from_feedback("manager_feedback_WP-2026-100.md")
        == "WP-2026-100"
    )
    # Non-matching returns None
    assert mod.extract_ticket_id_from_feedback("PLAN_WT-2026-221a.md") is None


def test_get_active_wp_letter_suffix(tmp_path: Path) -> None:
    """get_active_wp must return letter-suffix IDs from work_plan.md."""
    collab = tmp_path / "collaboration"
    collab.mkdir()
    work_plan = collab / "work_plan.md"

    work_plan.write_text(
        "# Work Plan\n\n**ID:** WT-2026-248b\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    assert mod.get_active_wp(collab) == "WT-2026-248b"


def test_archive_letter_suffix_files(tmp_path: Path) -> None:
    """Closed PLAN/AUDIT files with letter-suffix names are archived correctly."""
    collab = tmp_path / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)

    active_id = "WT-2026-250a"
    closed_id = "WT-2026-221a"

    # Active work_plan.md
    (collab / "work_plan.md").write_text(
        f"# Work Plan\n\n**ID:** {active_id}\n**Estado:** IN_PROGRESS\n",
        encoding="utf-8",
    )
    # Active PLAN/AUDIT files
    (collab / f"PLAN_{active_id}.md").write_text(
        f"# PLAN {active_id}\n", encoding="utf-8"
    )
    (collab / f"AUDIT_{active_id}.md").write_text(
        f"# AUDIT {active_id}\n", encoding="utf-8"
    )
    # Closed PLAN/AUDIT files with letter suffix
    (collab / f"PLAN_{closed_id}.md").write_text(
        f"# PLAN {closed_id}\n", encoding="utf-8"
    )
    (collab / f"AUDIT_{closed_id}.md").write_text(
        f"# AUDIT {closed_id}\n", encoding="utf-8"
    )

    result = mod.archive_collaboration_artifacts(collab, dry_run=False)

    assert len(result["archived"]) == 2
    assert len(result["errors"]) == 0

    archive_dir = mod.get_archive_dir(collab)
    assert (archive_dir / f"PLAN_{closed_id}.md").exists()
    assert (archive_dir / f"AUDIT_{closed_id}.md").exists()
    # Active files remain
    assert (collab / f"PLAN_{active_id}.md").exists()
    assert (collab / f"AUDIT_{active_id}.md").exists()
