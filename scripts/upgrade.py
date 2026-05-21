#!/usr/bin/env python3
"""
Smart upgrade system for z_scripts agent system.

Detects current version, backs up state, performs three-way merge to preserve
local changes, and verifies integrity post-upgrade.

Usage:
  python scripts/upgrade.py /path/to/project --dry-run
  python scripts/upgrade.py /path/to/project --confirm
  python scripts/upgrade.py /path/to/project --verify
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import ClassVar


class UpgradeManager:
    """Manage agent system upgrades with three-way merge and rollback."""

    UPGRADE_PATHS: ClassVar[dict[str, list[str]]] = {
        "v8.x": ["v9.0-v9.1", "v9.2", "v9.2.1+", "v9.4", "v9.5", "v9.6"],
        "v9.0-v9.1": ["v9.2", "v9.2.1+", "v9.4", "v9.5", "v9.6"],
        "v9.2": ["v9.2.1+", "v9.4", "v9.5", "v9.6"],
        "v9.2.1+": ["v9.4", "v9.5", "v9.6"],
        "v9.4": ["v9.5", "v9.6"],
        "v9.5": ["v9.6"],
        "v9.6": [],
    }

    CRITICAL_PATHS: ClassVar[list[str]] = [
        ".agent/",
        ".claude/",
        "agent_system/",
        "skills/",
        "scripts/",
        ".goosehints",
        "AGENTS.md",
        "CLAUDE.md",
    ]

    LOCAL_CUSTOMIZABLE: ClassVar[list[str]] = [
        ".agent/rules/",
        "skills/",
        "CLAUDE.md",
        "PROJECT.md",
    ]

    def __init__(self, project_dir: str, source_dir: str):
        self.project_path = Path(project_dir).resolve()
        self.source_path = Path(source_dir).resolve()
        self.backup_dir = self.project_path / ".agent" / "backups"
        self.manifest_file = self.project_path / ".agent" / ".version_manifest.json"
        self.upgrade_log = self.project_path / ".session" / "upgrade_log.md"

        if not self.project_path.exists():
            raise FileNotFoundError(f"Project directory not found: {project_dir}")
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

    def detect_current_version(self) -> str | None:
        """Detect current version using pattern matching."""
        try:
            from detect_version import AgentSystemDetector
        except ImportError:
            from scripts.detect_version import AgentSystemDetector

        detector = AgentSystemDetector(str(self.project_path))
        result = detector.detect_version()

        if result.get("detected"):
            return result.get("version")
        return None

    def detect_local_changes(self) -> dict[str, list[str]]:
        """Detect which files have been locally modified."""
        changes = {
            "modified": [],
            "added": [],
            "removed": [],
        }

        for local_path in self.LOCAL_CUSTOMIZABLE:
            full_path = self.project_path / local_path
            if not full_path.exists():
                continue

            # Check modification time against manifest
            if self.manifest_file.exists():
                manifest = json.loads(self.manifest_file.read_text())
                last_upgrade = datetime.fromisoformat(
                    manifest.get("detected_date", "2000-01-01")
                )

                if full_path.stat().st_mtime > last_upgrade.timestamp():
                    changes["modified"].append(local_path)

        return changes

    def backup_current_state(self) -> Path:
        """Create timestamped backup of current state."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)

        # Backup critical paths
        backed_up_paths: list[str] = []
        for critical_path in self.CRITICAL_PATHS:
            src = self.project_path / critical_path
            if src.exists():
                dst = backup_path / critical_path
                if src.is_dir():
                    ignore = (
                        shutil.ignore_patterns("backups")
                        if critical_path == ".agent/"
                        else None
                    )
                    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                backed_up_paths.append(critical_path)

        # Write backup manifest
        manifest = {
            "timestamp": timestamp,
            "version_before": self.detect_current_version(),
            "critical_paths_backed_up": backed_up_paths,
            "restoration_command": f"python scripts/rollback.py --backup {timestamp}",
        }
        (backup_path / "BACKUP_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2)
        )

        return backup_path

    def get_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file."""
        if not file_path.exists():
            return ""

        hash_md5 = hashlib.md5()  # noqa: S324 - legacy checksum for local change detection
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def merge_changes(
        self, _source_version: str, local_changes: dict[str, list[str]]
    ) -> dict[str, str]:
        """Three-way merge: keep local, update upstream."""
        merge_results = {}

        for critical_path in self.CRITICAL_PATHS:
            src = self.source_path / critical_path
            dst = self.project_path / critical_path

            if not src.exists():
                merge_results[critical_path] = "source_missing"
                continue

            if critical_path in self.LOCAL_CUSTOMIZABLE and any(
                critical_path == lc or critical_path.startswith(lc)
                for lc in local_changes["modified"] + local_changes["added"]
            ):
                # Local customization detected - ask for merge strategy
                merge_results[critical_path] = "requires_manual_merge"
                continue

            # Safe copy: replace non-customized files
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                merge_results[critical_path] = "updated"
            except Exception as e:
                merge_results[critical_path] = f"error: {e}"

        return merge_results

    def verify_upgrade(self) -> tuple[bool, dict]:
        """Verify post-upgrade integrity."""
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
            "required_markers_met": result.get("details", {}).get(
                "required_met", False
            ),
            "no_conflicts": not result.get("details", {}).get("absent_violated", False),
        }

        all_passed = all(checks.values())
        return all_passed, checks

    def update_manifest(self, new_version: str):
        """Update .version_manifest.json with new version info."""
        manifest = {
            "agent_core_version": new_version,
            "version": new_version,
            "status": "upgraded",
            "confidence": "high",
            "detected_date": datetime.now().isoformat(),
            "upgraded_from": self.detect_current_version(),
            "detected_by": "upgrade.py",
            "upgrade_timestamp": datetime.now().isoformat(),
            "verification": "pending",
        }

        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_file.write_text(json.dumps(manifest, indent=2))

    def run_upgrade(self, dry_run: bool = True) -> dict:
        """Execute upgrade workflow."""
        current_version = self.detect_current_version()
        local_changes = self.detect_local_changes()

        if not current_version:
            return {
                "status": "FAILED",
                "message": "Could not detect current version",
            }

        if not self.UPGRADE_PATHS.get(current_version):
            return {
                "status": "ALREADY_LATEST",
                "current_version": current_version,
                "version": current_version,
                "message": f"Project is already at latest version ({current_version})",
            }

        target_version = self.UPGRADE_PATHS[current_version][-1]

        result = {
            "status": "READY_FOR_UPGRADE",
            "current_version": current_version,
            "target_version": target_version,
            "upgrade_path": " -> ".join(
                [current_version] + self.UPGRADE_PATHS[current_version]
            ),
            "local_changes": local_changes,
            "dry_run": dry_run,
        }

        if dry_run:
            result["message"] = (
                "Dry run - no changes made. Run with --confirm to proceed."
            )
            return result

        # Perform upgrade
        backup_path = self.backup_current_state()
        merge_results = self.merge_changes(current_version, local_changes)
        success, checks = self.verify_upgrade()

        if success:
            self.update_manifest(target_version)
            result.update(
                {
                    "status": "COMPLETED",
                    "backup_location": str(backup_path),
                    "merge_results": merge_results,
                    "verification": checks,
                }
            )
        else:
            result.update(
                {
                    "status": "VERIFICATION_FAILED",
                    "backup_location": str(backup_path),
                    "merge_results": merge_results,
                    "verification": checks,
                    "recovery": f"Run: python scripts/rollback.py --backup {backup_path.name}",
                }
            )

        return result


def main():  # noqa: C901
    import argparse

    parser = argparse.ArgumentParser(description="Upgrade z_scripts agent system")
    parser.add_argument(
        "project_dir", nargs="?", default=".", help="Project directory to upgrade"
    )
    parser.add_argument(
        "--source", default=None, help="Source directory (default: current system)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate upgrade without changes"
    )
    parser.add_argument("--confirm", action="store_true", help="Perform actual upgrade")
    parser.add_argument(
        "--verify", action="store_true", help="Verify current system integrity"
    )

    args = parser.parse_args()

    source_dir = args.source or Path(__file__).parent.parent
    manager = UpgradeManager(args.project_dir, source_dir)

    print("=" * 70)
    print("  AGENT SYSTEM UPGRADE MANAGER")
    print("=" * 70)

    if args.verify:
        success, checks = manager.verify_upgrade()
        print(f"\nVerification Status: {'âœ“ PASS' if success else 'âœ— FAIL'}")
        for key, value in checks.items():
            print(f"  {key}: {value}")
        return 0 if success else 1

    result = manager.run_upgrade(dry_run=not args.confirm)

    print(f"\nStatus: {result['status']}")
    print(f"Current Version: {result.get('current_version', 'Unknown')}")
    print(f"Target Version: {result.get('target_version', 'N/A')}")

    if "upgrade_path" in result:
        print(f"Upgrade Path: {result['upgrade_path']}")

    if "local_changes" in result and any(result["local_changes"].values()):
        print("\nLocal Changes Detected:")
        for change_type, files in result["local_changes"].items():
            if files:
                print(f"  {change_type}: {', '.join(files)}")

    if result["status"] == "READY_FOR_UPGRADE":
        print(f"\n{result['message']}")
        if not args.confirm:
            print("Run with --confirm to proceed.")

    elif result["status"] == "COMPLETED":
        print("\nUpgrade completed successfully!")
        print(f"Backup: {result['backup_location']}")

    elif result["status"] == "VERIFICATION_FAILED":
        print("\n[X] Verification failed. Backup preserved.")
        print(f"Recovery: {result['recovery']}")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
