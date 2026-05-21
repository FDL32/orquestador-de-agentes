#!/usr/bin/env python3
"""
Manifest validation helper.

Validates project_manifest.toml and .version_manifest.json at load time.
Ensures minimum required structure, basic types, mandatory fields.
Handles legacy version alias compatibility without making it authoritative.
"""

import json
from pathlib import Path
from typing import ClassVar


try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.10 compatibility


class ManifestValidator:
    """Validate project manifests."""

    REQUIRED_PROJECT_MANIFEST_FIELDS: ClassVar[dict[str, dict[str, type]]] = {
        "project": {
            "id": str,
            "version": str,
        }
    }

    REQUIRED_VERSION_MANIFEST_FIELDS: ClassVar[dict[str, type]] = {
        "agent_core_version": str,
        "status": str,
        "confidence": str,
    }

    OPTIONAL_VERSION_MANIFEST_FIELDS: ClassVar[dict[str, type]] = {
        "version": str,  # Legacy alias, not authoritative
    }

    LEGACY_VERSION_WARNING = (
        "Warning: Legacy 'version' field present - use 'project.version' as authority"
    )

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self.project_manifest_path = agent_dir / "project_manifest.toml"
        self.version_manifest_path = agent_dir / ".version_manifest.json"

    def validate_manifests(self) -> tuple[bool, list[str]]:
        """
        Validate both manifests if they exist.

        Returns (is_valid, warnings_list)
        Fails fast on critical errors, collects warnings for legacy issues.
        """
        warnings = []
        errors = []

        # Validate project_manifest.toml
        if self.project_manifest_path.exists():
            valid, msgs = self._validate_project_manifest()
            if not valid:
                errors.extend(msgs)
            else:
                warnings.extend([m for m in msgs if "warning" in m.lower()])
        else:
            warnings.append("project_manifest.toml not found - using legacy detection")

        # Validate .version_manifest.json
        if self.version_manifest_path.exists():
            valid, msgs = self._validate_version_manifest()
            if not valid:
                errors.extend(msgs)
            else:
                warnings.extend([m for m in msgs if "warning" in m.lower()])
        else:
            warnings.append(".version_manifest.json not found - using legacy detection")

        # Check for legacy version alias conflicts
        legacy_warnings = self._check_legacy_version_conflicts()
        warnings.extend(legacy_warnings)

        is_valid = len(errors) == 0
        all_msgs = errors + warnings

        return is_valid, all_msgs

    def _validate_project_manifest(self) -> tuple[bool, list[str]]:
        """Validate project_manifest.toml structure."""
        msgs = []
        try:
            with open(self.project_manifest_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            return False, [f"Failed to load project_manifest.toml: {e}"]

        # Check required sections and fields
        for section, fields in self.REQUIRED_PROJECT_MANIFEST_FIELDS.items():
            if section not in data:
                msgs.append(
                    f"Missing required section [{section}] in project_manifest.toml"
                )
                continue

            section_data = data[section]
            for field, expected_type in fields.items():
                if field not in section_data:
                    msgs.append(f"Missing required field '{field}' in [{section}]")
                    continue

                value = section_data[field]
                if not isinstance(value, expected_type):
                    msgs.append(
                        f"Field '{field}' in [{section}] must be {expected_type.__name__}, got {type(value).__name__}"
                    )

        # Check for legacy version alias
        if "version" in data and data["version"] != data.get("project", {}).get(
            "version"
        ):
            msgs.append(self.LEGACY_VERSION_WARNING)

        return len([m for m in msgs if not m.startswith("warning")]) == 0, msgs

    def _validate_version_manifest(self) -> tuple[bool, list[str]]:
        """Validate .version_manifest.json structure."""
        msgs = []
        try:
            with open(self.version_manifest_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return False, [f"Failed to load .version_manifest.json: {e}"]

        # Check required fields
        for field, expected_type in self.REQUIRED_VERSION_MANIFEST_FIELDS.items():
            if field not in data:
                msgs.append(
                    f"Missing required field '{field}' in .version_manifest.json"
                )
                continue

            value = data[field]
            if not isinstance(value, expected_type):
                msgs.append(
                    f"Field '{field}' must be {expected_type.__name__}, got {type(value).__name__}"
                )

        # Check optional fields
        for field, expected_type in self.OPTIONAL_VERSION_MANIFEST_FIELDS.items():
            if field in data:
                value = data[field]
                if not isinstance(value, expected_type):
                    msgs.append(
                        f"Field '{field}' must be {expected_type.__name__}, got {type(value).__name__}"
                    )

        return len(msgs) == 0, msgs

    def _check_legacy_version_conflicts(self) -> list[str]:
        """Check for legacy version alias conflicts between manifests."""
        warnings = []

        project_version = None
        if self.project_manifest_path.exists():
            try:
                with open(self.project_manifest_path, "rb") as f:
                    data = tomllib.load(f)
                project_version = data.get("project", {}).get("version")
            except Exception as e:
                warnings.append(
                    f"Failed to load project manifest for legacy check: {e}"
                )

        agent_core_version = None
        if self.version_manifest_path.exists():
            try:
                with open(self.version_manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
                agent_core_version = data.get("agent_core_version")
            except Exception as e:
                warnings.append(
                    f"Failed to load version manifest for legacy check: {e}"
                )

        # If both exist and differ, warn
        if (
            project_version
            and agent_core_version
            and project_version != agent_core_version
        ):
            warnings.append(
                "project.version and agent_core_version differ - ensure correct authority"
            )

        return warnings

    def load_validated_manifests(self) -> tuple[dict | None, dict | None, list[str]]:
        """
        Load and validate manifests.

        Returns (project_manifest, version_manifest, warnings)
        If validation fails, returns None for failed manifests.
        """
        is_valid, msgs = self.validate_manifests()

        load_errors = []
        project_manifest = None
        if self.project_manifest_path.exists() and is_valid:
            try:
                with open(self.project_manifest_path, "rb") as f:
                    project_manifest = tomllib.load(f)
            except Exception as e:
                load_errors.append(f"Failed to load project manifest: {e}")

        version_manifest = None
        if self.version_manifest_path.exists() and is_valid:
            try:
                with open(self.version_manifest_path, encoding="utf-8") as f:
                    version_manifest = json.load(f)
            except Exception as e:
                load_errors.append(f"Failed to load version manifest: {e}")

        warnings = [
            m for m in msgs if "error" not in m.lower() and "failed" not in m.lower()
        ]
        warnings.extend(load_errors)

        return project_manifest, version_manifest, warnings
