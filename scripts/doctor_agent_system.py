#!/usr/bin/env python3
"""
Doctor agent system: diagnose, repair, and maintain agent system health.

Usage:
  python scripts/doctor_agent_system.py /path/to/project
  python scripts/doctor_agent_system.py /path/to/project --repair-manifest
  python scripts/doctor_agent_system.py /path/to/project --validate
"""

import json
import sys
from datetime import datetime
from pathlib import Path


try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.10 compatibility

# Add project root and agent_system to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.detect_version import AgentSystemDetector
from scripts.manifest_validator import ManifestValidator
from scripts.project_paths import ProjectPathsResolver


class DoctorAgentSystem:
    """Diagnose and repair agent system issues."""

    def _has_complete_manifests(self) -> bool:
        """Check whether both canonical manifests exist on disk."""
        if not self.agent_path:
            return False

        project_manifest = self.agent_path / "project_manifest.toml"
        version_manifest = self.agent_path / ".version_manifest.json"
        return project_manifest.exists() and version_manifest.exists()

    def __init__(self, project_dir: str):
        resolver = ProjectPathsResolver(project_dir)
        self.project_path = resolver.get_project_root()
        self.agent_path = resolver.get_agent_dir()
        self.drift_info = resolver.get_drift_info()

        if not self.project_path:
            self.project_path = Path(project_dir).resolve()

        # Fallback: if no agent_path found but .agent exists, use it
        if not self.agent_path and self.project_path:
            candidate_agent_path = self.project_path / ".agent"
            if candidate_agent_path.exists() and candidate_agent_path.is_dir():
                self.agent_path = candidate_agent_path

        # Validate manifests
        if self.agent_path:
            validator = ManifestValidator(self.agent_path)
            self.manifests_valid, self.validation_msgs = validator.validate_manifests()
            self.project_manifest, self.version_manifest, self.manifest_warnings = (
                validator.load_validated_manifests()
            )
        else:
            self.manifests_valid = False
            self.validation_msgs = ["No agent directory found"]
            self.project_manifest = None
            self.version_manifest = None
            self.manifest_warnings = []

    def _set_initial_severity(self, diagnosis: dict, detection: dict) -> None:
        """Set initial severity based on detection mode."""
        detection_mode = detection.get("detection_mode", "unknown")

        if detection_mode == "not_initialized":
            diagnosis["issues"].append("Agent system not initialized")
            diagnosis["recommendations"].append(
                "Run install_agent_system.py to initialize"
            )
            diagnosis["severity"] = "critical"
        elif detection_mode in ["legacy_markers", "legacy_partial"]:
            diagnosis["issues"].append(
                "Legacy detection - using markers instead of manifests"
            )
            diagnosis["recommendations"].append(
                "Migrate to manifests with doctor_agent_system.py --repair-manifest"
            )
            diagnosis["severity"] = "warning"
        elif detection_mode == "version_manifest":
            diagnosis["issues"].append(
                "Missing project manifest - only technical manifest present"
            )
            diagnosis["recommendations"].append(
                "Create project manifest with doctor_agent_system.py --repair-manifest"
            )
            diagnosis["severity"] = "warning"

    def _update_severity_for_warnings(self, diagnosis: dict, detection: dict) -> None:
        """Update severity if warnings present and manifest not healthy."""
        manifest_first_healthy = (
            detection.get("detection_mode") == "manifest"
            and self.manifests_valid
            and self.project_manifest is not None
            and self.version_manifest is not None
        )

        if detection.get("warnings"):
            diagnosis["issues"].extend([f"Warning: {w}" for w in detection["warnings"]])
            if diagnosis["severity"] == "healthy" and not manifest_first_healthy:
                diagnosis["severity"] = "warning"

    def _handle_drift_issues(self, diagnosis: dict, drift_issues: list) -> None:
        """Process drift issues and update severity accordingly."""
        if not drift_issues:
            return

        diagnosis["drift"]["detected"] = True
        diagnosis["drift"]["details"].extend(drift_issues)
        diagnosis["issues"].extend([f"Drift: {issue}" for issue in drift_issues])

        # Determine if drift is reparable
        for issue in drift_issues:
            if (
                "ambiguous" in issue.lower()
                or "multiple .agent/" in issue.lower()
                or "paths.root drift" in issue.lower()
                or "paths.agent_dir drift" in issue.lower()
            ):
                diagnosis["drift"]["reparable"] = False
                break

        if diagnosis["drift"]["reparable"]:
            diagnosis["recommendations"].append(
                "Run doctor_agent_system.py --repair-manifest to fix reparable drift"
            )
        else:
            diagnosis["issues"].append(
                "Ambiguous drift detected - manual intervention required for migrate/upgrade"
            )
            diagnosis["recommendations"].append(
                "Resolve ambiguous drift manually before running migrate/upgrade"
            )
            if diagnosis["severity"] in ["healthy", "warning"]:
                diagnosis["severity"] = "error"

    def diagnose(self) -> dict:
        """Run comprehensive diagnosis of the agent system."""
        detector = AgentSystemDetector(str(self.project_path))
        detection = detector.detect_version()

        diagnosis = {
            "detection": detection,
            "issues": [],
            "recommendations": [],
            "severity": "healthy",
            "drift": {"detected": False, "reparable": True, "details": []},
        }

        self._set_initial_severity(diagnosis, detection)
        self._update_severity_for_warnings(diagnosis, detection)

        drift_issues = self._check_drift(detection)
        self._handle_drift_issues(diagnosis, drift_issues)

        return diagnosis

    def _check_drift(self, detection: dict) -> list[str]:
        """Check for advanced drift issues."""
        issues = []

        # Check for multiple .agent directories
        agent_dirs = list(self.project_path.glob("**/.agent"))
        if len(agent_dirs) > 1:
            issues.append(
                f"Multiple .agent/ directories detected: {[str(d.relative_to(self.project_path)) for d in agent_dirs]}"
            )

        # Check manifest integrity if present (only if agent_path exists)
        if not self.agent_path:
            return issues

        manifest_path = self.agent_path / "project_manifest.toml"
        if manifest_path.exists():
            try:
                with open(manifest_path, "rb") as f:
                    manifest = tomllib.load(f)

                paths_section = manifest.get("paths", {})

                # Check paths.root drift
                declared_root = paths_section.get("root", ".")
                if declared_root != ".":
                    issues.append(
                        f"paths.root drift: declared '{declared_root}' but expected '.' for manifest-first architecture"
                    )

                # Check paths.agent_dir drift
                declared_agent_dir = paths_section.get("agent_dir", ".agent")
                if declared_agent_dir != ".agent":
                    issues.append(
                        f"paths.agent_dir drift: declared '{declared_agent_dir}' but expected '.agent'"
                    )

            except Exception as e:
                issues.append(f"Manifest corrupt: {e}")

        # Check for partial manifests
        version_manifest_path = self.agent_path / ".version_manifest.json"
        if manifest_path.exists() and not version_manifest_path.exists():
            issues.append(
                "Partial manifests: project_manifest.toml present but .version_manifest.json missing"
            )
        elif not manifest_path.exists() and version_manifest_path.exists():
            issues.append(
                "Partial manifests: .version_manifest.json present but project_manifest.toml missing"
            )

        return issues

    def repair_manifest(self) -> dict:
        """Create basic manifests from legacy markers."""
        detector = AgentSystemDetector(str(self.project_path))
        detection = detector.detect_version()

        result = {"success": False, "message": "", "created_files": [], "warnings": []}

        detection_mode = detection.get("detection_mode", "unknown")
        project_manifest_path = (
            self.agent_path / "project_manifest.toml" if self.agent_path else None
        )
        version_manifest_path = (
            self.agent_path / ".version_manifest.json" if self.agent_path else None
        )

        if (
            project_manifest_path
            and version_manifest_path
            and project_manifest_path.exists()
            and version_manifest_path.exists()
        ):
            result["message"] = "All manifests exist - no repair needed"
            result["success"] = True
            return result

        # Check if repair is needed
        if (
            detection_mode == "manifest"
            and version_manifest_path
            and not version_manifest_path.exists()
        ):
            try:
                self._create_version_manifest(detection)
                result["success"] = True
                result["message"] = "Technical manifest created successfully"
                result["created_files"] = [".agent/.version_manifest.json"]
            except Exception as e:
                result["message"] = f"Failed to create technical manifest: {e}"
                result["warnings"].append(str(e))
            return result

        if detection_mode == "not_initialized":
            result["message"] = "No agent system detected - cannot repair manifests"
            return result

        # For legacy modes, create all manifests
        if detection_mode in ["legacy_markers", "legacy_partial"]:
            try:
                self._create_project_manifest(detection)
                self._create_version_manifest(detection)
                result["success"] = True
                result["message"] = "Manifests created successfully"
                result["created_files"] = [
                    ".agent/project_manifest.toml",
                    ".agent/.version_manifest.json",
                ]
            except Exception as e:
                result["message"] = f"Failed to create manifests: {e}"
                result["warnings"].append(str(e))
        else:
            result["message"] = f"Unexpected detection mode: {detection_mode}"

        return result

    def _create_project_manifest(self, detection: dict):
        """Create basic project_manifest.toml from detection."""
        manifest_path = self.agent_path / "project_manifest.toml"

        # Derive identity from project path
        project_name = self.project_path.name or "unnamed_project"
        project_id = project_name.lower().replace(" ", "_").replace("-", "_")

        # Basic manifest structure
        manifest = {
            "project": {
                "id": project_id,
                "name": project_name.replace("_", " ").title(),
                "version": "1.0.0",
                "type": "python_app",
                "created_from": "legacy_markers",
            },
            "paths": {"root": ".", "agent_dir": ".agent"},
            "agent_system": {"min_version": "8.0.0", "upgrade_channel": "stable"},
        }

        # Write TOML
        content = f"""[project]
id = "{manifest["project"]["id"]}"
name = "{manifest["project"]["name"]}"
version = "{manifest["project"]["version"]}"
type = "{manifest["project"]["type"]}"
created_from = "{manifest["project"]["created_from"]}"

[paths]
root = "{manifest["paths"]["root"]}"
agent_dir = "{manifest["paths"]["agent_dir"]}"

[agent_system]
min_version = "{manifest["agent_system"]["min_version"]}"
upgrade_channel = "{manifest["agent_system"]["upgrade_channel"]}"
"""

        manifest_path.write_text(content)

    def _create_version_manifest(self, detection: dict):
        """Create .version_manifest.json with recovered status."""
        version_path = self.agent_path / ".version_manifest.json"

        # Determine agent_core_version from detection
        agent_core_version = detection.get("legacy_version", "unknown")

        version_manifest = {
            "agent_core_version": agent_core_version,
            "template_version": "1.0.0",
            "status": "recovered",
            "confidence": "recovered_from_markers",
            "last_updated": datetime.now().isoformat(),
            "components": {
                "agent_controller": "1.0.0",
                "hooks": "1.0.0",
                "rules": "1.0.0",
            },
            "markers_validated": True,
            "drift_detected": False,
        }

        version_path.write_text(json.dumps(version_manifest, indent=2))

    def validate(self) -> dict:
        """Validate current system integrity."""
        diagnosis = self.diagnose()
        manifest_first_healthy = (
            diagnosis["detection"].get("detection_mode") == "manifest"
            and self.manifests_valid
            and self.project_manifest is not None
            and self.version_manifest is not None
        )
        validation = {
            "diagnosis": diagnosis,
            "validation_passed": (
                (diagnosis["severity"] == "healthy" or manifest_first_healthy)
                and not diagnosis.get("drift", {}).get("detected")
            ),
            "checks": [],
        }

        # Add specific checks
        detection = diagnosis["detection"]
        detection_mode = detection.get("detection_mode", "unknown")

        validation["checks"].append(
            {
                "check": "detection_mode",
                "status": "pass" if detection_mode != "unknown" else "fail",
                "message": f"Detection mode: {detection_mode}",
            }
        )

        validation["checks"].append(
            {
                "check": "manifest_integrity",
                "status": "pass" if detection_mode == "manifest" else "warning",
                "message": "Project manifest present"
                if detection_mode == "manifest"
                else "Missing project manifest",
            }
        )

        validation["checks"].append(
            {
                "check": "no_warnings",
                "status": "pass" if not detection.get("warnings") else "warning",
                "message": f"Warnings: {len(detection.get('warnings', []))}",
            }
        )

        # Add drift-specific checks
        drift_details = diagnosis.get("drift", {}).get("details", [])
        validation["checks"].append(
            {
                "check": "no_drift_detected",
                "status": "pass"
                if not diagnosis.get("drift", {}).get("detected")
                else "fail",
                "message": f"Drift issues: {len(drift_details)}",
            }
        )

        validation["checks"].append(
            {
                "check": "drift_reparable",
                "status": "pass"
                if not diagnosis.get("drift", {}).get("detected")
                or diagnosis["drift"].get("reparable")
                else "fail",
                "message": "Drift reparable"
                if diagnosis.get("drift", {}).get("reparable", True)
                else "Drift ambiguous - blocks migrate/upgrade",
            }
        )

        # Add specific drift checks
        for detail in drift_details:
            if "multiple .agent/" in detail.lower():
                validation["checks"].append(
                    {
                        "check": "single_agent_directory",
                        "status": "fail",
                        "message": detail,
                    }
                )
            elif "paths.root drift" in detail.lower():
                validation["checks"].append(
                    {
                        "check": "paths_root_canonical",
                        "status": "fail",
                        "message": detail,
                    }
                )
            elif "paths.agent_dir drift" in detail.lower():
                validation["checks"].append(
                    {
                        "check": "paths_agent_dir_canonical",
                        "status": "fail",
                        "message": detail,
                    }
                )
            elif "partial manifests" in detail.lower():
                validation["checks"].append(
                    {
                        "check": "manifest_integrity_complete",
                        "status": "warning",
                        "message": detail,
                    }
                )

        return validation


def _print_header():
    """Print the header for the doctor output."""
    print("=" * 70)
    print("  AGENT SYSTEM DOCTOR")
    print("=" * 70)


def _print_footer():
    """Print the footer for the doctor output."""
    print("\n" + "=" * 70)


def _handle_repair_manifest_command(doctor: DoctorAgentSystem) -> None:
    """Handle the --repair-manifest command."""
    print("\nRunning manifest repair...\n")
    result = doctor.repair_manifest()

    if result["success"]:
        print("[OK] Repair successful!")
        print(f"Message: {result['message']}")
        if result["created_files"]:
            print("Created files:")
            for file in result["created_files"]:
                print(f"  - {file}")
    else:
        print("[ERROR] Repair failed!")
        print(f"Message: {result['message']}")

    if result.get("warnings"):
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")


def _handle_validate_command(doctor: DoctorAgentSystem) -> None:
    """Handle the --validate command."""
    print("\nRunning validation...\n")
    result = doctor.validate()

    status = "[OK] PASS" if result["validation_passed"] else "[WARN] ISSUES"
    print(f"Validation: {status}")
    print(f"Severity: {result['diagnosis']['severity']}")

    for check in result["checks"]:
        if check["status"] == "pass":
            status_icon = "[OK]"
        elif check["status"] == "warning":
            status_icon = "[WARN]"
        else:
            status_icon = "[ERROR]"
        print(f"{status_icon} {check['check']}: {check['message']}")

    if result["diagnosis"]["issues"]:
        print("\nIssues:")
        for issue in result["diagnosis"]["issues"]:
            print(f"  - {issue}")

    if result["diagnosis"]["recommendations"]:
        print("\nRecommendations:")
        for rec in result["diagnosis"]["recommendations"]:
            print(f"  - {rec}")


def _handle_diagnose_command(doctor: DoctorAgentSystem) -> None:
    """Handle the default diagnose command."""
    print("\nRunning diagnosis...\n")
    diagnosis = doctor.diagnose()

    print(f"Overall Status: {diagnosis['severity'].upper()}")
    print(f"Detection Mode: {diagnosis['detection']['detection_mode']}")

    if diagnosis["issues"]:
        print("\nIssues Found:")
        for issue in diagnosis["issues"]:
            print(f"  - {issue}")

    if diagnosis["recommendations"]:
        print("\nRecommendations:")
        for rec in diagnosis["recommendations"]:
            print(f"  - {rec}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Doctor agent system")
    parser.add_argument("project_dir", nargs="?", default=".", help="Project directory")
    parser.add_argument(
        "--repair-manifest",
        action="store_true",
        help="Create basic manifests from legacy markers",
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate system integrity"
    )

    args = parser.parse_args()

    doctor = DoctorAgentSystem(args.project_dir)

    _print_header()

    if args.repair_manifest:
        _handle_repair_manifest_command(doctor)
    elif args.validate:
        _handle_validate_command(doctor)
    else:
        _handle_diagnose_command(doctor)

    _print_footer()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
