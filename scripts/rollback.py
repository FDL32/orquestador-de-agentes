#!/usr/bin/env python3
"""
Rollback agent system to previous state.

Restores from timestamped backups created during upgrade process.

Usage:
  python scripts/rollback.py --list
  python scripts/rollback.py --backup 20260426_143022
  python scripts/rollback.py --latest
"""

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


class RollbackManager:
    """Manage rollback of agent system upgrades."""

    def __init__(self, project_dir: str = "."):
        self.project_path = Path(project_dir).resolve()
        self.backup_dir = self.project_path / ".agent" / "backups"

        if not self.project_path.exists():
            raise FileNotFoundError(f"Project directory not found: {project_dir}")

    def list_backups(self) -> list[dict]:
        """List all available backups."""
        if not self.backup_dir.exists():
            return []

        backups = []
        for backup_path in sorted(self.backup_dir.iterdir(), reverse=True):
            if not backup_path.is_dir():
                continue

            manifest_file = backup_path / "BACKUP_MANIFEST.json"
            if manifest_file.exists():
                manifest = json.loads(manifest_file.read_text())
                backups.append(
                    {
                        "timestamp": backup_path.name.replace("backup_", ""),
                        "version_before": manifest.get("version_before"),
                        "critical_paths": len(
                            manifest.get("critical_paths_backed_up", [])
                        ),
                        "path": str(backup_path),
                    }
                )

        return backups

    def get_latest_backup(self) -> Path | None:
        """Get the most recent backup."""
        if not self.backup_dir.exists():
            return None

        backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)
        return backups[0] if backups else None

    def restore_backup(self, backup_id: str) -> dict:  # noqa: C901
        """Restore from specific backup."""
        backup_path = self.backup_dir / f"backup_{backup_id}"

        if not backup_path.exists():
            return {
                "status": "FAILED",
                "message": f"Backup not found: {backup_id}",
            }

        manifest_file = backup_path / "BACKUP_MANIFEST.json"
        if not manifest_file.exists():
            return {
                "status": "FAILED",
                "message": f"Backup corrupted (missing manifest): {backup_id}",
            }

        manifest = json.loads(manifest_file.read_text())
        restored_paths = []
        failed_paths = []

        def copy_tree_contents(source: Path, target: Path) -> None:
            for item in source.rglob("*"):
                relative = item.relative_to(source)
                destination = target / relative
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)

        # Restore critical paths
        for critical_path in manifest.get("critical_paths_backed_up", []):
            src = backup_path / critical_path
            dst = self.project_path / critical_path

            if not src.exists():
                failed_paths.append(critical_path)
                continue

            try:
                if critical_path == ".agent/":
                    with tempfile.TemporaryDirectory() as temp_dir:
                        staging_root = Path(temp_dir) / ".agent"
                        staging_root.mkdir(parents=True, exist_ok=True)
                        copy_tree_contents(src, staging_root)
                        if dst.exists():
                            shutil.rmtree(dst)
                        copy_tree_contents(staging_root, dst)
                else:
                    # Remove current version
                    if dst.exists():
                        if dst.is_dir():
                            shutil.rmtree(dst)
                        else:
                            dst.unlink()

                    # Restore from backup
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)

                restored_paths.append(critical_path)
            except Exception as e:
                failed_paths.append(f"{critical_path} (error: {e})")

        # Update manifest
        manifest_file_current = self.project_path / ".agent" / ".version_manifest.json"
        if manifest_file_current.exists():
            manifest_data = json.loads(manifest_file_current.read_text())
            manifest_data["rollback_from"] = manifest_data.get("version")
            manifest_data["rolled_back_to"] = manifest.get("version_before")
            manifest_data["rollback_timestamp"] = datetime.now().isoformat()
            manifest_file_current.write_text(json.dumps(manifest_data, indent=2))

        result = {
            "status": "COMPLETED" if not failed_paths else "PARTIAL",
            "backup_id": backup_id,
            "version_restored": manifest.get("version_before"),
            "paths_restored": len(restored_paths),
            "paths_failed": len(failed_paths),
            "restored_paths": restored_paths,
        }

        if failed_paths:
            result["failed_paths"] = failed_paths

        return result

    def verify_restore(self) -> tuple[bool, dict]:
        """Verify system integrity after restore."""
        try:
            from detect_version import AgentSystemDetector
        except ImportError:
            from scripts.detect_version import AgentSystemDetector

        detector = AgentSystemDetector(str(self.project_path))
        result = detector.detect_version()

        checks = {
            "version_detected": result.get("detected", False),
            "version": result.get("version"),
            "confidence": result.get("confidence"),
            "integrity_ok": result.get("details", {}).get("required_met", False),
        }

        all_passed = all(checks.values())
        return all_passed, checks


def list_available_backups(project_dir: str = ".") -> list[dict]:
    """Wrapper for RollbackManager.list_backups()."""
    return RollbackManager(project_dir).list_backups()


def restore_latest_backup(project_dir: str = ".") -> dict:
    """Wrapper for RollbackManager.restore_backup(latest)."""
    manager = RollbackManager(project_dir)
    latest = manager.get_latest_backup()
    if not latest:
        return {"status": "FAILED", "message": "No backups found"}
    backup_id = latest.name.replace("backup_", "")
    return manager.restore_backup(backup_id)


def main():  # noqa: C901
    import argparse

    parser = argparse.ArgumentParser(
        description="Rollback agent system to previous state"
    )
    parser.add_argument("--project", default=".", help="Project directory")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument(
        "--backup", metavar="ID", help="Restore specific backup (timestamp)"
    )
    parser.add_argument("--latest", action="store_true", help="Restore latest backup")
    parser.add_argument(
        "--verify", action="store_true", help="Verify integrity after restore"
    )

    args = parser.parse_args()

    manager = RollbackManager(args.project)

    print("=" * 70)
    print("  AGENT SYSTEM ROLLBACK MANAGER")
    print("=" * 70)

    if args.list:
        backups = manager.list_backups()

        if not backups:
            print("\nNo backups found.")
            return 0

        print(f"\nAvailable Backups ({len(backups)}):\n")
        for backup in backups:
            print(f"  ID: {backup['timestamp']}")
            print(f"     Version: {backup['version_before']}")
            print(f"     Paths: {backup['critical_paths']}")
            print(f"     Path: {backup['path']}")
            print()

        return 0

    if args.latest:
        latest = manager.get_latest_backup()
        if latest:
            backup_id = latest.name.replace("backup_", "")
            args.backup = backup_id
        else:
            print("\nNo backups found.")
            return 1

    if args.backup:
        print(f"\nRestoring backup: {args.backup}")
        result = manager.restore_backup(args.backup)

        print(f"\nRestore Status: {result['status']}")
        print(f"Version Restored: {result.get('version_restored')}")
        print(f"Paths Restored: {result.get('paths_restored')}")

        if result.get("failed_paths"):
            print(f"\nFailed Paths ({len(result['failed_paths'])}):")
            for path in result["failed_paths"]:
                print(f"  - {path}")

        if args.verify:
            print("\nVerifying integrity...")
            success, checks = manager.verify_restore()
            print(f"Verification: {'âœ“ PASS' if success else 'âœ— FAIL'}")
            for key, value in checks.items():
                print(f"  {key}: {value}")

        return 0 if result["status"] == "COMPLETED" else 1

    print("\nUsage: python scripts/rollback.py --list | --latest | --backup ID")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
