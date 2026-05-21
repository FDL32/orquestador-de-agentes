"""Tests for scripts/cleanup_legacy.py."""

import shutil
from pathlib import Path

from scripts.cleanup_legacy import LegacyCleanup


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_confirm_removal_cleans_safe_items_and_archives_guide():
    project = PROJECT_ROOT / ".tmp" / "cleanup_legacy_test"
    shutil.rmtree(project, ignore_errors=True)
    scripts_dir = project / "scripts"
    agent_legacy = project / ".agent" / "legacy"
    backups_dir = project / ".agent" / "backups"
    pycache_dir = project / ".ruff_cache"
    session_dir = project / ".session"

    scripts_dir.mkdir(parents=True)
    agent_legacy.mkdir(parents=True)
    backups_dir.mkdir(parents=True)
    pycache_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)

    (scripts_dir / "detect_agent_system_version.py").write_text("# old detector")
    (project / "debug_output.txt").write_text("debug")
    (project / "temp_output.txt").write_text("temp")
    (pycache_dir / "__pycache__").mkdir()
    (agent_legacy / "old_state.json").write_text("{}")
    (backups_dir / "backup_old").mkdir()
    (project / "UPGRADE_GUIDE.md").write_text("# old guide")

    cleanup = LegacyCleanup(str(project))
    legacy = cleanup.find_legacy_files()
    removed, failed = cleanup.confirm_removal(legacy)

    assert failed == 0
    assert removed >= 2
    assert not (scripts_dir / "detect_agent_system_version.py").exists()
    assert not (project / "debug_output.txt").exists()
    assert not (project / "temp_output.txt").exists()
    assert not agent_legacy.exists()
    assert not backups_dir.exists()
    assert not pycache_dir.exists()
    assert not (project / "UPGRADE_GUIDE.md").exists()
    assert (project / ".session" / "archive" / "UPGRADE_GUIDE.md").exists()
    assert cleanup.cleanup_log.exists()
    log_text = cleanup.cleanup_log.read_text(encoding="utf-8")
    assert "Removed items" in log_text
    assert "Archived items" in log_text
    shutil.rmtree(project, ignore_errors=True)
