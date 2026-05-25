"""
Tests for scripts/rollback.py (RollbackManager)

Covers: backup enumeration, restoration (latest & specific), manifest updates,
post-rollback verification.
"""

import json

from scripts.rollback import (
    RollbackManager,
    list_available_backups,
    restore_latest_backup,
)


class TestRollbackBackupEnumeration:
    """Test backup listing and discovery."""

    def test_list_available_backups_empty(self, tmp_path):
        """Test listing when no backups exist."""
        project = tmp_path / "project"
        project.mkdir()
        # No backups directory
        (project / ".agent").mkdir()

        manager = RollbackManager(str(project))
        backups = manager.list_backups()

        assert backups == []

    def test_list_available_backups_with_multiple(self, tmp_path):
        """Test listing multiple timestamped backups."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)

        # Create two backups with manifests
        for ts in ["20260426_120000", "20260426_143022"]:
            backup = backup_root / f"backup_{ts}"
            backup.mkdir()
            manifest = {
                "timestamp": ts,
                "version_before": "v9.2",
                "critical_paths_backed_up": [".agent/", "skills/"],
                "restoration_command": f"python scripts/rollback.py --backup {ts}",
            }
            (backup / "BACKUP_MANIFEST.json").write_text(json.dumps(manifest))

        manager = RollbackManager(str(project))
        backups = manager.list_backups()

        assert len(backups) == 2
        timestamps = [b["timestamp"] for b in backups]
        assert timestamps == sorted(timestamps, reverse=True)
        assert backups[0]["timestamp"] == "20260426_143022"

    def test_get_latest_backup(self, tmp_path):
        """Test retrieval of most recent backup."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)

        for ts in ["20260426_120000", "20260426_143022"]:
            (backup_root / f"backup_{ts}").mkdir()

        manager = RollbackManager(str(project))
        latest = manager.get_latest_backup()

        assert latest is not None
        assert latest.name == "backup_20260426_143022"


class TestRollbackRestore:
    """Test backup restoration functionality."""

    def test_restore_latest_backup(self, tmp_path):
        """Test restoring the most recent backup."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)

        ts = "20260426_143022"
        backup = backup_root / f"backup_{ts}"
        backup.mkdir()
        (backup / "config.txt").write_text("# backed up content")
        (backup / "BACKUP_MANIFEST.json").write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "version_before": "v9.2",
                    "critical_paths_backed_up": ["config.txt"],
                }
            )
        )

        (project / "config.txt").write_text("# current version")

        manager = RollbackManager(str(project))
        result = manager.restore_backup(ts)

        assert result["status"] == "COMPLETED"
        assert result["backup_id"] == ts
        assert result["paths_restored"] >= 1
        restored_content = (project / "config.txt").read_text()
        assert restored_content == "# backed up content"

    def test_restore_specific_backup_by_timestamp(self, tmp_path):
        """Test restoring a specific backup by timestamp."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)

        for ts, content in [
            ("20260426_120000", "old backup"),
            ("20260426_143022", "new backup"),
        ]:
            backup = backup_root / f"backup_{ts}"
            backup.mkdir()
            (backup / "marker.txt").write_text(content)
            (backup / "BACKUP_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "timestamp": ts,
                        "version_before": "v9.2",
                        "critical_paths_backed_up": ["marker.txt"],
                    }
                )
            )

        (project / "marker.txt").write_text("current")

        manager = RollbackManager(str(project))
        result = manager.restore_backup("20260426_120000")

        assert result["status"] == "COMPLETED"
        assert result["backup_id"] == "20260426_120000"
        assert (project / "marker.txt").read_text() == "old backup"


class TestRollbackManifestUpdate:
    """Test manifest updates after rollback."""

    def test_rollback_updates_manifest(self, tmp_path):
        """Test that rollback updates .version_manifest.json."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)

        (project / ".agent").mkdir(parents=True, exist_ok=True)
        current_manifest = {
            "version": "v9.2.1+",
            "detected_date": "2026-04-27T10:00:00",
            "upgraded_from": "v9.2",
        }
        (project / ".agent" / ".version_manifest.json").write_text(
            json.dumps(current_manifest)
        )

        ts = "20260426_143022"
        backup = backup_root / f"backup_{ts}"
        backup.mkdir()
        (backup / "agent_controller.py").write_text("# backed up content")
        (backup / "BACKUP_MANIFEST.json").write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "version_before": "v9.2",
                    "critical_paths_backed_up": ["agent_controller.py"],
                }
            )
        )

        manager = RollbackManager(str(project))
        manager.restore_backup(ts)

        new_manifest = json.loads(
            (project / ".agent" / ".version_manifest.json").read_text()
        )
        assert "rollback_from" in new_manifest
        assert new_manifest["rollback_from"] == "v9.2.1+"
        assert "rolled_back_to" in new_manifest
        assert new_manifest["rolled_back_to"] == "v9.2"
        assert "rollback_timestamp" in new_manifest


class TestRollbackHelperFunctions:
    """Test module-level helper wrappers."""

    def test_list_available_backups_function(self, tmp_path):
        """Test list_available_backups() wrapper."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)
        (backup_root / "backup_test_ts").mkdir()
        (backup_root / "backup_test_ts" / "BACKUP_MANIFEST.json").write_text(
            json.dumps(
                {
                    "timestamp": "test_ts",
                    "version_before": "v9.2",
                    "critical_paths_backed_up": [],
                }
            )
        )

        backups = list_available_backups(str(project))
        assert len(backups) == 1

    def test_restore_latest_backup_function(self, tmp_path):
        """Test restore_latest_backup() wrapper."""
        project = tmp_path / "project"
        project.mkdir()
        backup_root = project / ".agent" / "backups"
        backup_root.mkdir(parents=True)
        backup = backup_root / "backup_latest"
        backup.mkdir()
        (backup / "BACKUP_MANIFEST.json").write_text(
            json.dumps(
                {
                    "timestamp": "latest",
                    "version_before": "v9.2",
                    "critical_paths_backed_up": [],
                }
            )
        )

        result = restore_latest_backup(str(project))
        assert "status" in result
