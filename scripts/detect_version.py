#!/usr/bin/env python3
"""
Detect z_scripts agent system version by architectural patterns.

Usage:
  python scripts/detect_version.py /path/to/project
  python scripts/detect_version.py .  # Current directory
"""

import sys
from pathlib import Path
from typing import ClassVar


# Add agent_system to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.manifest_validator import ManifestValidator
from scripts.project_paths import ProjectPathsResolver


class AgentSystemDetector:
    """Detect agent system version by fingerprinting project structure."""

    # Markers for each version
    MARKERS: ClassVar[dict[str, dict[str, list[str]]]] = {
        "v8.x": {
            "required": [".agent/agent_controller.py", "scripts/run_pytest_safe.py"],
            "optional": [".agent/hooks/guard_paths.py", ".agent/collaboration/"],
            "absent": [".agent/rules", "skills", "AGENTS.md", "orquestador_de_agentes"],
        },
        "v9.0-v9.1": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                "skills/",
                "CLAUDE.md",
            ],
            "optional": ["scripts/discover_skills.py", ".agent/collaboration/"],
            "absent": [".claude/rules", "AGENTS.md", "agent_system/refactor_kit"],
        },
        "v9.2": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                "skills/",
                "agent_system/refactor_kit/",
                "CLAUDE.md",
            ],
            "optional": ["orquestador_de_agentes/", "AGENTS.md"],
            "absent": [".claude/rules"],  # Pre-9.2.1
        },
        "v9.2.1+": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                ".claude/rules/",
                "skills/",
                "agent_system/refactor_kit/",
                "AGENTS.md",
                "CLAUDE.md",
            ],
            "optional": ["orquestador_de_agentes/", ".version_manifest.json"],
            "absent": [],
        },
        "v9.6": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                ".claude/rules/",
                "skills/",
                "agent_system/refactor_kit/",
                "AGENTS.md",
                "CLAUDE.md",
                "QUICKSTART.md",
                "INTERACTION_MODES.md",
                "scripts/run_llm_evals.py",
                ".agent/runtime/llm_evals_config.json",
            ],
            "optional": ["orquestador_de_agentes/", ".version_manifest.json"],
            "absent": [],
        },
        "v9.5": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                ".claude/rules/",
                "skills/",
                "agent_system/refactor_kit/",
                "AGENTS.md",
                "CLAUDE.md",
                "QUICKSTART.md",
                "INTERACTION_MODES.md",
            ],
            "optional": ["orquestador_de_agentes/", ".version_manifest.json"],
            "absent": [],
        },
        "v9.4": {
            "required": [
                ".agent/agent_controller.py",
                ".agent/rules/",
                ".claude/rules/",
                "skills/",
                "agent_system/refactor_kit/",
                "AGENTS.md",
                "CLAUDE.md",
                "QUICKSTART.md",
            ],
            "optional": ["orquestador_de_agentes/", ".version_manifest.json"],
            "absent": [],
        },
    }

    def __init__(self, project_dir: str):
        resolver = ProjectPathsResolver(project_dir)
        self.project_path = resolver.get_project_root()
        self.agent_dir = resolver.get_agent_dir()
        self.drift_info = resolver.get_drift_info()

        if not self.project_path:
            self.project_path = Path(project_dir).resolve()

        # Fallback: if no agent_dir found but .agent exists in project, use it (for partial/test projects)
        if not self.agent_dir and self.project_path:
            candidate_agent_dir = self.project_path / ".agent"
            if candidate_agent_dir.exists() and candidate_agent_dir.is_dir():
                self.agent_dir = candidate_agent_dir

        # Validate manifests at init
        if self.agent_dir:
            validator = ManifestValidator(self.agent_dir)
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

    def has_multi_agent_system(self) -> bool:
        """Check if project has any version of the agent system."""
        return (
            self.agent_dir is not None
            and (self.agent_dir / "agent_controller.py").exists()
        )

    def check_markers(self, version: str) -> tuple[bool, dict]:
        """Check if project matches markers for a specific version."""
        markers = self.MARKERS.get(version)
        if not markers:
            return False, {}

        required_met = all(
            (self.project_path / marker).exists() for marker in markers["required"]
        )

        optional_met = sum(
            1 for marker in markers["optional"] if (self.project_path / marker).exists()
        )

        absent_violated = any(
            (self.project_path / marker).exists() for marker in markers["absent"]
        )

        return (required_met and not absent_violated), {
            "required_met": required_met,
            "optional_met": optional_met,
            "optional_total": len(markers["optional"]),
            "absent_violated": absent_violated,
        }

    def _detect_via_legacy_markers(self) -> dict | None:
        """Detect version via legacy markers and return result dict or None."""
        results = {}
        for version in [
            "v9.6",
            "v9.5",
            "v9.4",
            "v9.2.1+",
            "v9.2",
            "v9.0-v9.1",
            "v8.x",
        ]:
            matches, details = self.check_markers(version)
            results[version] = {"matches": matches, **details}

        # Find best match
        best_match = None
        for version, result in results.items():
            if result["matches"]:
                best_match = version
                break

        if best_match:
            return {
                "detected": True,
                "detection_mode": "legacy_markers",
                "canonical_agent_root": str(self.agent_dir),
                "project_root": str(self.project_path),
                "version": best_match,
                "legacy_version": best_match,
                "status": "legacy",
                "confidence": "high",
                "details": results[best_match],
                "message": f"Detected via legacy markers: {best_match}",
            }

        # Partial match - find closest
        closest = max(
            results.items(),
            key=lambda x: (x[1]["required_met"], x[1]["optional_met"]),
        )
        return {
            "detected": True,
            "detection_mode": "legacy_partial",
            "canonical_agent_root": str(self.agent_dir),
            "project_root": str(self.project_path),
            "version": closest[0],
            "legacy_version": closest[0],
            "status": "legacy",
            "confidence": "low",
            "message": "Partial legacy match - system may be customized or corrupted",
            "details": closest[1],
        }

    def _build_warnings(self) -> list[str]:
        """Build warnings list for detection result."""
        warnings = (
            self.manifest_warnings + self.validation_msgs
            if not self.manifests_valid
            else self.manifest_warnings
        )

        # Add drift warnings
        if self.drift_info["drift_detected"]:
            warnings.append(f"Path drift detected: {self.drift_info['message']}")

        return warnings

    def detect_version(self) -> dict:
        """Detect project version with manifest-first approach."""
        warnings = self._build_warnings()

        # 1. Use validated project_manifest.toml if available
        if self.project_manifest:
            project_id = self.project_manifest.get("project", {}).get("id", "unknown")
            project_version = self.project_manifest.get("project", {}).get(
                "version", "unknown"
            )

            # Get agent_core_version from version_manifest if available
            agent_core_version = "unknown"
            status = "canonical"
            confidence = "high"
            if self.version_manifest:
                agent_core_version = self.version_manifest.get(
                    "agent_core_version", "unknown"
                )
                status = self.version_manifest.get("status", "canonical")
                confidence = self.version_manifest.get("confidence", "high")

            result = {
                "detected": True,
                "detection_mode": "manifest",
                "canonical_agent_root": str(self.agent_dir),
                "project_root": str(self.project_path),
                "project_id": project_id,
                "version": project_version,  # project.version is authoritative
                "agent_core_version": agent_core_version,
                "status": status,
                "confidence": confidence,
                "message": "Detected via validated project_manifest.toml",
            }
            if warnings:
                result["warnings"] = warnings
            return result

        # 2. Fallback to version_manifest.json
        if self.version_manifest:
            agent_core_version = self.version_manifest.get(
                "agent_core_version", "unknown"
            )
            status = self.version_manifest.get("status", "unknown")
            confidence = self.version_manifest.get("confidence", "unknown")
            result = {
                "detected": True,
                "detection_mode": "version_manifest",
                "canonical_agent_root": str(self.agent_dir),
                "project_root": str(self.project_path),
                "version": agent_core_version,
                "agent_core_version": agent_core_version,
                "status": status,
                "confidence": confidence,
                "message": "Detected via .version_manifest.json (legacy)",
            }
            if warnings:
                result["warnings"] = warnings
            return result

        # 3. Fallback to legacy markers
        if not self.has_multi_agent_system():
            result = {
                "detected": False,
                "detection_mode": "not_initialized",
                "canonical_agent_root": str(self.agent_dir) if self.agent_dir else None,
                "project_root": str(self.project_path) if self.project_path else None,
                "message": "No agent system found",
            }
            if warnings:
                result["warnings"] = warnings
            return result

        legacy_result = self._detect_via_legacy_markers()
        if legacy_result:
            if warnings:
                legacy_result["warnings"] = warnings
            return legacy_result

    def suggest_upgrade_path(self, detected_version: str) -> str:
        """Suggest upgrade path from detected version."""
        paths = {
            "v8.x": "v8.x -> v9.0-v9.1 -> v9.2 -> v9.2.1+ -> v9.4 -> v9.5 -> v9.6",
            "v9.0-v9.1": "v9.0-v9.1 -> v9.2 -> v9.2.1+ -> v9.4 -> v9.5 -> v9.6",
            "v9.2": "v9.2 -> v9.2.1+ -> v9.4 -> v9.5 -> v9.6",
            "v9.2.1+": "v9.2.1+ -> v9.4 -> v9.5 -> v9.6",
            "v9.4": "v9.4 -> v9.5 -> v9.6",
            "v9.5": "v9.5 -> v9.6",
            "v9.6": "Already latest",
        }
        return paths.get(detected_version, "Unknown")

    def create_version_manifest(self, version: str) -> dict:
        """Create .version_manifest.json for detected version."""
        manifest = {
            "version": version,
            "detected_date": __import__("datetime").datetime.now().isoformat(),
            "detected_by": "detect_version.py",
            "confidence": "auto-detected",
            "markers_matched": self._get_matched_markers(version),
        }
        return manifest

    def _get_matched_markers(self, version: str) -> list[str]:
        """Get list of markers that matched for a version."""
        markers = self.MARKERS.get(version, {})
        return [
            marker
            for marker in markers.get("required", [])
            if (self.project_path / marker).exists()
        ]


def main():
    import sys

    project_dir = "." if len(sys.argv) < 2 else sys.argv[1]

    print("=== AGENT SYSTEM VERSION DETECTION ===\n")
    print(f"Project: {Path(project_dir).resolve()}\n")

    detector = AgentSystemDetector(project_dir)
    result = detector.detect_version()

    if result["detected"]:
        detection_mode = result.get("detection_mode", "unknown")
        print(f"Detection Mode: {detection_mode}")

        if detection_mode == "manifest":
            print(f"Project ID: {result.get('project_id', 'unknown')}")
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"Confidence: {result.get('confidence', 'unknown')}")
        elif detection_mode == "version_manifest":
            print(f"Agent Core Version: {result.get('agent_core_version', 'unknown')}")
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"Confidence: {result.get('confidence', 'unknown')}")
        elif detection_mode in ["legacy_markers", "legacy_partial"]:
            version = result.get("legacy_version", "unknown")
            confidence = result.get("confidence", "unknown")
            print(f"Legacy Version: {version}")
            print(f"Confidence: {confidence}")
            print(f"Upgrade Path: {detector.suggest_upgrade_path(version)}\n")

            if "details" in result:
                details = result["details"]
                print("Diagnostic:")
                print(f"  Required markers met: {details.get('required_met')}")
                print(
                    f"  Optional markers: {details.get('optional_met')}/{details.get('optional_total')}"
                )
                print(f"  No conflicts: {not details.get('absent_violated')}")

        print(f"Canonical Agent Root: {result.get('canonical_agent_root', 'unknown')}")
        print(f"Message: {result.get('message', '')}")

        return 0
    else:
        print(f"Detection Mode: {result.get('detection_mode', 'unknown')}")
        print(result.get("message", "Unknown error"))
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
