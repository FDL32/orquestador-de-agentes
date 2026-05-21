#!/usr/bin/env python3
"""
Legacy project migration tool.

Usage:
  python scripts/migrate_legacy_project.py /path/to/project --auto
  python scripts/migrate_legacy_project.py /path/to/project --confirm
"""

import json


try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.10 compatibility
import sys
from pathlib import Path


# Add project root and agent_system to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.detect_version import AgentSystemDetector
from scripts.doctor_agent_system import DoctorAgentSystem
from scripts.manifest_validator import ManifestValidator
from scripts.project_paths import ProjectPathsResolver


class LegacyMigrationManager:
    """Manage migration of legacy projects to manifest-based architecture."""

    def __init__(self, project_dir: str):
        resolver = ProjectPathsResolver(project_dir)
        self.project_path = resolver.get_project_root() or Path(project_dir).resolve()
        self.agent_path = resolver.get_agent_dir()
        self.drift_info = resolver.get_drift_info()
        self.project_initialized = self.agent_path is not None

        # Validate manifests
        if self.agent_path:
            validator = ManifestValidator(self.agent_path)
            self.manifests_valid, self.validation_msgs = validator.validate_manifests()
        else:
            self.manifests_valid = False
            self.validation_msgs = ["No agent directory found"]

    def auto_migrate(self) -> dict:
        """Analyze project and prepare migration plan without making changes."""
        analysis = {
            "detection": {
                "detected": False,
                "detection_mode": "not_initialized",
                "project_root": str(self.project_path),
                "message": "No agent system found",
            },
            "migration_needed": False,
            "issues": [],
            "actions": [],
            "risks": [],
            "recommendations": [],
        }

        # Check for multiple .agent directories
        agent_dirs = [
            d
            for d in self.project_path.glob("**/.agent")
            if d.is_dir() and "backups" not in d.parts
        ]
        if len(agent_dirs) > 1:
            analysis["migration_needed"] = True
            dirs_str = [str(d.relative_to(self.project_path)) for d in agent_dirs]
            analysis["issues"].append(f"Multiple .agent directories found: {dirs_str}")
            # Propose canonical
            canonical = self._select_canonical_agent_dir(agent_dirs)
            canonical_rel = canonical.relative_to(self.project_path)
            msg = f"Consolidate to canonical .agent/ at {canonical_rel}"
            analysis["actions"].append(msg)
            analysis["canonical_agent"] = str(canonical.relative_to(self.project_path))
            return analysis

        if not self.project_initialized or not self.agent_path:
            analysis["issues"].append("Project not initialized")
            analysis["recommendations"].append("Run install_agent_system.py first")
            return analysis

        project_manifest_path = self.agent_path / "project_manifest.toml"
        version_manifest_path = self.agent_path / ".version_manifest.json"
        has_project_manifest = project_manifest_path.exists()
        has_version_manifest = version_manifest_path.exists()

        if has_project_manifest:
            det_mode = "manifest" if has_version_manifest else "version_manifest"
            analysis["detection"] = {
                "detected": True,
                "detection_mode": det_mode,
                "canonical_agent_root": str(self.agent_path),
                "project_root": str(self.project_path),
                "message": "Detected via manifest files",
            }
            drift_issues = self._detect_route_drift()
            if not has_version_manifest:
                analysis["migration_needed"] = True
                analysis["issues"].append("Missing .version_manifest.json")
                analysis["actions"].append("Create technical manifest")
                if drift_issues:
                    analysis["migration_needed"] = True
                    analysis["issues"].extend(drift_issues)
                    analysis["actions"].append("Correct route drift in manifests")
                return analysis

            if drift_issues:
                analysis["migration_needed"] = True
                analysis["issues"].extend(drift_issues)
                analysis["actions"].append("Correct route drift in manifests")
            else:
                analysis["issues"].append("already migrated")
                analysis["recommendations"].append("No migration needed")
            return analysis

        if has_version_manifest:
            analysis["detection"] = {
                "detected": True,
                "detection_mode": "version_manifest",
                "canonical_agent_root": str(self.agent_path),
                "project_root": str(self.project_path),
                "message": "Detected via .version_manifest.json",
            }
            analysis["migration_needed"] = True
            analysis["issues"].append("Missing project_manifest.toml")
            analysis["actions"].append("Create project manifest")
            return analysis

        # Check for route drift in manifests
        drift_issues = self._detect_route_drift()
        if drift_issues:
            analysis["migration_needed"] = True
            analysis["issues"].extend(drift_issues)
            analysis["actions"].append("Correct route drift in manifests")

        # Fallback to legacy detection
        if self._has_legacy_markers():
            analysis["migration_needed"] = True
            analysis["issues"].append("Legacy marker-based detection")
            analysis["actions"].extend(self._get_migration_actions())
        else:
            analysis["issues"].append("No migration indicators found")
            analysis["recommendations"].append("Project appears to be in unknown state")

        return analysis

    def confirm_migrate(self) -> dict:  # noqa: C901
        """Execute migration based on analysis."""
        # First run auto analysis
        analysis = self.auto_migrate()

        result = {"success": False, "message": "", "changes": [], "warnings": []}

        if not analysis["migration_needed"]:
            result["success"] = True
            result["message"] = "No migration needed"
            return result

        # Handle multiple .agent/ directories
        agent_dirs = list(self.project_path.glob("**/.agent"))
        if len(agent_dirs) > 1:
            canonical = self._select_canonical_agent_dir(agent_dirs)
            consolidated_files, conflicts = self._consolidate_agent_dirs(canonical)
            result["changes"].extend([f"Consolidated {f}" for f in consolidated_files])
            result["changes"].append("Removed duplicate .agent/ directories")
            if conflicts:
                result["warnings"].extend(conflicts)

        # Apply migration actions
        try:
            created_files = []

            create_manifest_action = (
                "Create project manifest" in analysis["actions"]
                or "Create project_manifest.toml" in analysis["actions"]
            )
            if create_manifest_action:
                self._create_missing_manifests()
                # Check what was created
                if (self.agent_path / "project_manifest.toml").exists():
                    created_files.append(".agent/project_manifest.toml")
                if (self.agent_path / ".version_manifest.json").exists():
                    created_files.append(".agent/.version_manifest.json")

            if "Create technical manifest" in analysis["actions"]:
                doctor = DoctorAgentSystem(str(self.project_path))
                repair_result = doctor.repair_manifest()
                if repair_result["success"]:
                    created_files.extend(repair_result["created_files"])
                else:
                    msg = repair_result["message"]
                    result["warnings"].append(f"Manifest repair failed: {msg}")

            result["changes"].extend(created_files)

            drift_blocked = False
            if "Correct route drift in manifests" in analysis["actions"]:
                drift_corrected = self._correct_route_drift()
                if drift_corrected:
                    result["changes"].append("Corrected route drift")
                else:
                    result["success"] = False
                    result["message"] = (
                        "Migration blocked: ambiguous route drift detected"
                    )
                    result["warnings"].append("Route drift correction failed")
                    drift_blocked = True
            if not drift_blocked:
                result["success"] = True
                result["message"] = "Migration completed successfully"

        except Exception as e:
            result["message"] = f"Migration failed: {e}"
            result["warnings"].append(str(e))

        return result

    def _select_canonical_agent_dir(self, agent_dirs):
        """Select the canonical .agent/ directory to keep."""
        # Priority: root .agent/, then shortest path
        root_agent = self.project_path / ".agent"
        if root_agent in agent_dirs:
            return root_agent

        # Choose the one with shortest relative path
        def rel_path_depth(d):
            return len(d.relative_to(self.project_path).parts)

        return min(agent_dirs, key=rel_path_depth)

    def _detect_route_drift(self):
        """Detect drift in declared routes vs real filesystem structure."""
        issues = []
        manifest_path = self.agent_path / "project_manifest.toml"
        if not manifest_path.exists():
            return issues  # No manifest, no drift

        try:
            with open(manifest_path, "rb") as f:
                manifest = tomllib.load(f)
        except Exception:
            return ["Manifest corrupt - cannot check drift"]

        paths = manifest.get("paths", {})

        # Check paths.root
        declared_root = paths.get("root", ".")
        if declared_root != ".":
            msg = f"Drift in paths.root: declared '{declared_root}', should be '.'"
            issues.append(msg)

        # Check paths.agent_dir
        declared_agent_dir = paths.get("agent_dir", ".agent")
        if declared_agent_dir != ".agent":
            real_agent_dir = self.project_path / ".agent"
            declared_agent_path = self.project_path / declared_agent_dir
            if real_agent_dir.exists() and declared_agent_path.exists():
                msg = (
                    f"Drift in paths.agent_dir: declared '{declared_agent_dir}' "
                    f"and real '.agent' both exist - ambiguous"
                )
                issues.append(msg)
            elif real_agent_dir.exists():
                msg = (
                    f"Drift in paths.agent_dir: declared '{declared_agent_dir}', "
                    f"real is '.agent' - repairable"
                )
                issues.append(msg)
            else:
                msg = (
                    f"Drift in paths.agent_dir: declared '{declared_agent_dir}', "
                    f"no .agent found - ambiguous"
                )
                issues.append(msg)

        return issues

    def _consolidate_agent_dirs(self, canonical_dir):
        """Consolidate multiple .agent/ directories into the canonical one."""
        agent_dirs = list(self.project_path.glob("**/.agent"))
        agent_dirs.remove(canonical_dir)  # Don't consolidate canonical into itself

        consolidated_files = []
        conflicts = []

        for src_dir in agent_dirs:
            for src_file in src_dir.rglob("*"):
                if src_file.is_file():
                    # Compute relative path from .agent/
                    rel_path = src_file.relative_to(src_dir)
                    dst_file = canonical_dir / rel_path

                    if dst_file.exists():
                        # Conflict: keep canonical, warn
                        msg = f"Conflict for {rel_path}: keeping canonical version"
                        conflicts.append(msg)
                    else:
                        # Copy file
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        import shutil

                        shutil.copy2(src_file, dst_file)
                        consolidated_files.append(str(rel_path))

            # Remove the empty source dir
            import shutil

            shutil.rmtree(src_dir)

        return consolidated_files, conflicts

    def _correct_route_drift(self):
        """Correct repairable route drift in project_manifest.toml."""
        manifest_path = self.agent_path / "project_manifest.toml"
        if not manifest_path.exists():
            return False

        try:
            with open(manifest_path, "rb") as f:
                manifest = tomllib.load(f)
        except Exception:
            return False

        paths = manifest.get("paths", {})
        corrected = False

        # Correct paths.root if wrong
        if paths.get("root") != ".":
            paths["root"] = "."
            corrected = True

        # Correct paths.agent_dir if repairable
        if paths.get("agent_dir") != ".agent":
            real_agent = self.project_path / ".agent"
            declared_agent = self.project_path / paths.get("agent_dir", ".agent")
            if real_agent.exists() and real_agent.is_dir() and declared_agent.exists():
                return False
            if real_agent.exists() and real_agent.is_dir():
                paths["agent_dir"] = ".agent"
                corrected = True
            else:
                # Ambiguous or not repairable
                return False

        if corrected:
            # Write back the corrected manifest
            content = f"""[project]
id = "{manifest["project"].get("id", "unknown")}"
name = "{manifest["project"].get("name", "Unknown")}"
version = "{manifest["project"].get("version", "1.0.0")}"
type = "{manifest["project"].get("type", "python_app")}"
created_from = "{manifest["project"].get("created_from", "unknown")}"

[paths]
root = "{paths.get("root", ".")}"
agent_dir = "{paths.get("agent_dir", ".agent")}"

[agent_system]
min_version = "{manifest.get("agent_system", {}).get("min_version", "8.0.0")}"
upgrade_channel = "{manifest.get("agent_system", {}).get("upgrade_channel", "stable")}"
"""
            manifest_path.write_text(content)

        return corrected

    def _has_legacy_markers(self) -> bool:
        """Check if project has legacy markers indicating migration needed."""
        markers = [
            self.project_path / "AGENTS.md",
            self.project_path / "CLAUDE.md",
            self.project_path / "skills",
            self.project_path / "agent_system",
            self.project_path / ".claude",
        ]
        # Check files exist
        if not all(m.exists() for m in markers[:2]):
            return False
        # Check directories exist
        if not all(m.exists() for m in markers[2:]):
            return False
        # Check .agent has rules
        return (self.agent_path / "rules").exists()

    def _get_migration_actions(self) -> list[str]:
        """Get list of migration actions for legacy markers."""
        return [
            "Create project_manifest.toml",
            "Create .version_manifest.json",
            "Preserve existing structure",
        ]

    def _create_missing_manifests(self):
        """Create missing manifests for legacy projects."""
        # Check what manifests are missing
        project_manifest_path = self.agent_path / "project_manifest.toml"
        version_manifest_path = self.agent_path / ".version_manifest.json"

        if not project_manifest_path.exists():
            detector = AgentSystemDetector(str(self.project_path))
            detection = detector.detect_version()
            doctor = DoctorAgentSystem(str(self.project_path))
            doctor._create_project_manifest(detection)

        if not version_manifest_path.exists():
            self._create_version_manifest_from_project_manifest()

    def _create_version_manifest_from_project_manifest(self):
        """Create a minimal .version_manifest.json from the current manifest."""
        version_path = self.agent_path / ".version_manifest.json"
        project_manifest_path = self.agent_path / "project_manifest.toml"

        agent_core_version = "unknown"
        if project_manifest_path.exists():
            try:
                with open(project_manifest_path, "rb") as f:
                    project_manifest = tomllib.load(f)
                project_info = project_manifest.get("project", {})
                agent_core_version = project_info.get("version", "unknown")
            except Exception:
                agent_core_version = "unknown"

        version_manifest = {
            "version": agent_core_version,
            "agent_core_version": agent_core_version,
            "template_version": "1.0.0",
            "status": "recovered",
            "confidence": "recovered_from_manifest",
            "last_updated": "",
            "components": {
                "agent_controller": "1.0.0",
                "hooks": "1.0.0",
                "rules": "1.0.0",
            },
            "markers_validated": True,
            "drift_detected": False,
        }

        version_path.write_text(json.dumps(version_manifest, indent=2))


def main():  # noqa: C901
    import argparse

    parser = argparse.ArgumentParser(description="Migrate legacy projects")
    parser.add_argument("project_dir", nargs="?", default=".", help="Project directory")
    parser.add_argument(
        "--auto", action="store_true", help="Analyze and plan migration"
    )
    parser.add_argument("--confirm", action="store_true", help="Execute migration")

    args = parser.parse_args()

    manager = LegacyMigrationManager(args.project_dir)

    print("=" * 70)
    print("  LEGACY PROJECT MIGRATION MANAGER")
    print("=" * 70)

    if args.auto:
        print("\nRunning migration analysis...\n")
        analysis = manager.auto_migrate()

        print(f"Migration Needed: {analysis['migration_needed']}")
        print(f"Detection Mode: {analysis['detection']['detection_mode']}")

        if analysis["issues"]:
            print("\nIssues Found:")
            for issue in analysis["issues"]:
                print(f"  - {issue}")

        if analysis["actions"]:
            print("\nPlanned Actions:")
            for action in analysis["actions"]:
                print(f"  - {action}")

        if analysis["recommendations"]:
            print("\nRecommendations:")
            for rec in analysis["recommendations"]:
                print(f"  - {rec}")

    elif args.confirm:
        print("\nExecuting migration...\n")
        result = manager.confirm_migrate()

        if result["success"]:
            print("âœ… Migration successful!")
            print(f"Message: {result['message']}")
            if result["changes"]:
                print("Changes made:")
                for change in result["changes"]:
                    print(f"  - {change}")
        else:
            print("âŒ Migration failed!")
            print(f"Message: {result['message']}")

        if result["warnings"]:
            print("\nWarnings:")
            for warning in result["warnings"]:
                print(f"  - {warning}")

    else:
        print("Use --auto to analyze or --confirm to execute migration")

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
