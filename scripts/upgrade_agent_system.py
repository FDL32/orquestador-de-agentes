#!/usr/bin/env python3
"""
Smart upgrade system for z_scripts agent system.

Detects current version, backs up state, performs three-way merge to preserve
local changes, and verifies integrity post-upgrade.

Usage:
  python scripts/upgrade_agent_system.py /path/to/project --dry-run
  python scripts/upgrade_agent_system.py /path/to/project --confirm
  python scripts/upgrade_agent_system.py /path/to/project --verify
"""

import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar


# Add project root and agent_system to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.doctor_agent_system import DoctorAgentSystem
from scripts.project_paths import ProjectPathsResolver


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
        resolver = ProjectPathsResolver(project_dir)
        self.project_path = resolver.get_project_root() or Path(project_dir).resolve()
        self.agent_dir = resolver.get_agent_dir()
        self.drift_info = resolver.get_drift_info()
        self.project_initialized = self.agent_dir is not None

        self.source_path = Path(source_dir).resolve()
        self.backup_dir = (
            self.project_path / ".agent" / "backups" if self.project_path else None
        )
        self.manifest_file = (
            self.agent_dir / ".version_manifest.json" if self.agent_dir else None
        )
        self.upgrade_log = (
            self.project_path / ".session" / "upgrade_log.md"
            if self.project_path
            else None
        )

        if not self.source_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

    def detect_current_version(self) -> dict:
        """Detect current version using manifest-first detection."""
        if not self.project_initialized or not self.agent_dir:
            return {
                "detected": False,
                "detection_mode": "not_initialized",
                "canonical_agent_root": str(self.agent_dir) if self.agent_dir else None,
                "project_root": str(self.project_path),
                "message": "No agent system detected",
            }

        from scripts.detect_version import AgentSystemDetector

        detector = AgentSystemDetector(str(self.project_path))
        return detector.detect_version()

    def _normalize_warnings(self, warnings: list[str]) -> list[str]:
        normalized = list(warnings)
        corrupt_warning = "corrupt project manifest detected"
        has_load_error = any(
            "failed to load project manifest" in w.lower() for w in normalized
        )
        if has_load_error and corrupt_warning not in normalized:
            normalized.insert(0, corrupt_warning)
        return normalized

    def detect_local_changes(self) -> dict[str, list[str]]:
        """Detect which files have been locally modified."""
        changes = {"modified": [], "added": [], "removed": []}

        for local_path in self.LOCAL_CUSTOMIZABLE:
            full_path = self.project_path / local_path
            manifest_exists = self.manifest_file and self.manifest_file.exists()
            if not full_path.exists() or not manifest_exists:
                continue

            manifest = json.loads(self.manifest_file.read_text())
            detected_date = manifest.get("detected_date", "2000-01-01")
            last_upgrade = datetime.fromisoformat(detected_date)
            if full_path.stat().st_mtime > last_upgrade.timestamp():
                changes["modified"].append(local_path)

        return changes

    def backup_current_state(self) -> Path:
        """Create timestamped backup of current state."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)

        backed_up_paths: list[str] = []
        for critical_path in self.CRITICAL_PATHS:
            src = self.project_path / critical_path
            if not src.exists():
                continue
            dst = backup_path / critical_path
            if src.is_dir():
                if critical_path == ".agent/":
                    ignore = shutil.ignore_patterns("backups")
                else:
                    ignore = None
                shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            backed_up_paths.append(critical_path)

        restoration_cmd = f"python scripts/rollback.py --backup {timestamp}"
        manifest = {
            "timestamp": timestamp,
            "version_before": self.detect_current_version(),
            "critical_paths_backed_up": backed_up_paths,
            "restoration_command": restoration_cmd,
        }
        manifest_file = backup_path / "BACKUP_MANIFEST.json"
        manifest_file.write_text(json.dumps(manifest, indent=2))
        return backup_path

    def get_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        if not file_path.exists():
            return ""

        file_hash = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(4096), b""):
                file_hash.update(chunk)
        return file_hash.hexdigest()

    def merge_changes(
        self, _source_version: str, local_changes: dict[str, list[str]]
    ) -> dict[str, str]:
        """Three-way merge: keep local, update upstream."""
        merge_results = {}
        changed_items = [item for sublist in local_changes.values() for item in sublist]

        for critical_path in self.CRITICAL_PATHS:
            src = self.source_path / critical_path
            dst = self.project_path / critical_path

            if not src.exists():
                merge_results[critical_path] = "source_missing"
                continue

            is_customizable = critical_path in self.LOCAL_CUSTOMIZABLE
            is_changed = critical_path in changed_items
            if is_customizable and is_changed:
                merge_results[critical_path] = "requires_manual_merge"
                continue

            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                merge_results[critical_path] = "updated"
            except Exception as exc:
                merge_results[critical_path] = f"error: {exc}"

        return merge_results

    def verify_upgrade(self) -> tuple[bool, dict]:
        """Verify post-upgrade integrity."""
        if not self.project_initialized or not self.agent_dir:
            return False, {
                "version_detected": False,
                "detection_mode": "not_initialized",
                "confidence": "low",
                "required_markers_met": False,
                "no_conflicts": False,
            }

        from scripts.detect_version import AgentSystemDetector

        detector = AgentSystemDetector(str(self.project_path))
        result = detector.detect_version()

        checks = {
            "version_detected": result.get("detected", False),
            "detection_mode": result.get("detection_mode", "unknown"),
            "confidence": result.get("confidence", "unknown"),
        }

        if result.get("detection_mode") in ["legacy_markers", "legacy_partial"]:
            details = result.get("details", {})
            checks.update(
                {
                    "required_markers_met": details.get("required_met", False),
                    "no_conflicts": not details.get("absent_violated", False),
                }
            )
        else:
            checks.update({"required_markers_met": True, "no_conflicts": True})

        return all(checks.values()), checks

    def update_manifest(self, new_version: str):
        """Update .version_manifest.json preserving the manifest-first contract."""
        existing_manifest = {}
        if self.manifest_file.exists():
            try:
                existing_manifest = json.loads(self.manifest_file.read_text())
            except Exception:
                existing_manifest = {}

        now = datetime.now().isoformat()
        manifest = {
            "version": new_version,  # Legacy alias for compatibility
            "agent_core_version": new_version,
            "template_version": existing_manifest.get("template_version", "1.0.0"),
            "status": "upgraded",
            "confidence": "high",
            "last_updated": now,
            "detected_date": now,
            "components": existing_manifest.get(
                "components",
                {
                    "agent_controller": "1.0.0",
                    "hooks": "1.0.0",
                    "rules": "1.0.0",
                },
            ),
            "markers_validated": existing_manifest.get("markers_validated", True),
            "drift_detected": False,
            "upgraded_from": existing_manifest.get("agent_core_version", "unknown"),
            "upgrade_timestamp": now,
            "upgraded_by": "upgrade_agent_system.py",
            "verification_status": "completed",
        }

        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_file.write_text(json.dumps(manifest, indent=2))

    def _print_warnings(self, warnings: list[str]) -> None:
        if not warnings:
            return
        print("Warnings detected:")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    def _check_drift_blockers(self, dry_run: bool, detection_mode: str) -> dict | None:
        if dry_run:
            return None

        doctor = DoctorAgentSystem(str(self.project_path))
        diagnosis = doctor.diagnose()
        drift = diagnosis.get("drift", {})
        if not drift.get("detected", False):
            return None

        if drift.get("reparable", True):
            msg = "Reparable drift detected - repair manifests first before upgrading."
            suggestion = "Run: python scripts/doctor_agent_system.py --repair-manifest"
            return {
                "status": "BLOCKED",
                "message": msg,
                "detection_mode": detection_mode,
                "drift_details": drift.get("details", []),
                "suggestion": suggestion,
            }

        msg = "Ambiguous drift detected - upgrade blocked. Resolve drift issues first."
        suggestion = "Run doctor_agent_system.py to diagnose and repair drift"
        return {
            "status": "BLOCKED",
            "message": msg,
            "detection_mode": detection_mode,
            "drift_details": drift.get("details", []),
            "suggestion": suggestion,
        }

    def _check_mode_blockers(
        self, dry_run: bool, detection_result: dict, detection_mode: str
    ) -> dict | None:
        if detection_mode == "not_initialized":
            msg = (
                "No agent system detected. "
                "Initialize first with install_agent_system.py"
            )
            return {
                "status": "BLOCKED",
                "message": msg,
                "detection_mode": detection_mode,
            }

        if detection_mode in ["legacy_markers", "legacy_partial"] and not dry_run:
            msg = (
                "Legacy detection. "
                "Run migration first: python scripts/migrate_legacy_project.py --auto"
            )
            return {
                "status": "BLOCKED",
                "message": msg,
                "detection_mode": detection_mode,
                "suggestion": "Migrate to manifests before upgrading",
            }

        has_low_confidence = (
            detection_mode == "version_manifest"
            and not dry_run
            and detection_result.get("confidence") not in ["high"]
        )
        if has_low_confidence:
            confidence = detection_result.get("confidence")
            msg = (
                f"Low confidence in version detection ({confidence}). "
                f"Repair manifests first."
            )
            return {
                "status": "BLOCKED",
                "message": msg,
                "detection_mode": detection_mode,
                "confidence": confidence,
            }

        return None

    def _resolve_current_version(
        self, detection_result: dict, detection_mode: str
    ) -> str:
        if detection_mode in ["manifest", "version_manifest"]:
            return detection_result.get("agent_core_version", "unknown")
        if detection_mode in ["legacy_markers", "legacy_partial"]:
            return detection_result.get("legacy_version", "unknown")
        return "unknown"

    def run_upgrade(self, dry_run: bool = True) -> dict:
        """Execute upgrade workflow."""
        agent_dirs = [
            d
            for d in self.project_path.glob("**/.agent")
            if d.is_dir() and "backups" not in d.parts
        ]
        if len(agent_dirs) > 1:
            dirs_str = [str(d.relative_to(self.project_path)) for d in agent_dirs]
            return {
                "status": "BLOCKED",
                "message": (
                    "Ambiguous drift detected - upgrade blocked. "
                    "Resolve drift issues first."
                ),
                "detection_mode": "drift",
                "drift_details": [f"Multiple .agent/ directories detected: {dirs_str}"],
                "suggestion": "Run doctor_agent_system.py to diagnose and repair drift",
            }

        if not self.project_initialized or not self.agent_dir:
            return {
                "status": "BLOCKED",
                "message": (
                    "No agent system detected. "
                    "Initialize first with install_agent_system.py"
                ),
                "detection_mode": "not_initialized",
            }

        detection_result = self.detect_current_version()
        local_changes = self.detect_local_changes()
        detection_mode = detection_result.get("detection_mode", "unknown")
        warnings = self._normalize_warnings(detection_result.get("warnings", []))
        self._print_warnings(warnings)

        drift_block = self._check_drift_blockers(dry_run, detection_mode)
        if drift_block:
            return drift_block

        mode_block = self._check_mode_blockers(
            dry_run, detection_result, detection_mode
        )
        if mode_block:
            return mode_block

        current_version = self._resolve_current_version(
            detection_result, detection_mode
        )
        if current_version == "unknown" or not detection_result.get("detected"):
            return {
                "status": "FAILED",
                "message": "Could not detect or determine current version",
                "detection_mode": detection_mode,
            }

        if not self.UPGRADE_PATHS.get(current_version):
            return {
                "status": "ALREADY_LATEST",
                "current_version": current_version,
                "version": current_version,
                "message": f"Project is already at latest version ({current_version})",
                "detection_mode": detection_mode,
            }

        target_version = self.UPGRADE_PATHS[current_version][-1]
        upgrade_path_str = " -> ".join(
            [current_version] + self.UPGRADE_PATHS[current_version]
        )
        result = {
            "status": "READY_FOR_UPGRADE",
            "detection_mode": detection_mode,
            "current_version": current_version,
            "target_version": target_version,
            "upgrade_path": upgrade_path_str,
            "local_changes": local_changes,
            "dry_run": dry_run,
        }

        if warnings:
            result["warnings"] = warnings
        if dry_run:
            result["message"] = (
                "Dry run - no changes made. Run with --confirm to proceed."
            )
            return result

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
                    "recovery": (
                        f"Run: python scripts/rollback_agent_system.py "
                        f"--backup {backup_path.name}"
                    ),
                }
            )

        return result


def _print_result_header(result: dict) -> None:
    print(f"\nStatus: {result['status']}")
    print(f"Detection Mode: {result.get('detection_mode', 'unknown')}")
    print(f"Current Version: {result.get('current_version', 'Unknown')}")
    print(f"Target Version: {result.get('target_version', 'N/A')}")
    if "upgrade_path" in result:
        print(f"Upgrade Path: {result['upgrade_path']}")


def _print_result_warnings_and_changes(result: dict) -> None:
    if "warnings" in result:
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if "local_changes" in result and any(result["local_changes"].values()):
        print("\nLocal Changes Detected:")
        for change_type, files in result["local_changes"].items():
            if files:
                print(f"  {change_type}: {', '.join(files)}")


def _print_result_status_message(result: dict, confirm: bool) -> None:
    if result["status"] == "READY_FOR_UPGRADE":
        print(f"\n{result['message']}")
        if not confirm:
            print("Run with --confirm to proceed.")
    elif result["status"] == "BLOCKED":
        print(f"\nUpgrade blocked: {result['message']}")
        if "suggestion" in result:
            print(f"Suggestion: {result['suggestion']}")
    elif result["status"] == "COMPLETED":
        print("\nUpgrade completed successfully!")
        print(f"Backup: {result['backup_location']}")
    elif result["status"] == "VERIFICATION_FAILED":
        print("\nVerification failed. Backup preserved.")
        print(f"Recovery: {result['recovery']}")


def _print_cli_result(result: dict, confirm: bool) -> None:
    _print_result_header(result)
    _print_result_warnings_and_changes(result)
    _print_result_status_message(result, confirm)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Upgrade z_scripts agent system")
    parser.add_argument(
        "project_dir", nargs="?", default=".", help="Project directory to upgrade"
    )
    parser.add_argument(
        "--source", default=None, help="Source directory (default: z_scripts)"
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
        print(f"\nVerification Status: {'✓ PASS' if success else ' ✗ FAIL'}")
        for key, value in checks.items():
            print(f"  {key}: {value}")
        return 0 if success else 1

    result = manager.run_upgrade(dry_run=not args.confirm)
    _print_cli_result(result, args.confirm)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
