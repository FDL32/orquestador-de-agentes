#!/usr/bin/env python3
"""
Unit tests for manifest_validator.py
"""

import json
import sys
from pathlib import Path


# Add agent_system to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_system"))

from scripts.manifest_validator import ManifestValidator


def _write_project_manifest(agent_dir: Path, text: str) -> Path:
    manifest_path = agent_dir / "project_manifest.toml"
    manifest_path.write_text(text, encoding="utf-8")
    return manifest_path


def _write_version_manifest(agent_dir: Path, payload: dict) -> Path:
    manifest_path = agent_dir / ".version_manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


class TestManifestValidator:
    """Test ManifestValidator."""

    def test_validate_project_manifest_missing(self, tmp_path):
        """Test validation when project_manifest.toml is missing."""
        validator = ManifestValidator(tmp_path)
        is_valid, msgs = validator.validate_manifests()
        assert is_valid is False or len(msgs) > 0  # Should have warnings
        assert any("project_manifest.toml not found" in msg for msg in msgs)

    def test_validate_version_manifest_missing(self, tmp_path):
        """Test validation when .version_manifest.json is missing."""
        validator = ManifestValidator(tmp_path)
        _, msgs = validator.validate_manifests()
        assert any(".version_manifest.json not found" in msg for msg in msgs)

    def test_validate_project_manifest_valid(self, tmp_path):
        """Test validation of valid project_manifest.toml."""
        _write_project_manifest(
            tmp_path,
            """
[project]
id = "test_project"
version = "1.0.0"
""",
        )

        validator = ManifestValidator(tmp_path)
        is_valid, msgs = validator.validate_manifests()
        # Project manifest is valid, version manifest missing is warning
        assert is_valid
        assert any(".version_manifest.json not found" in msg for msg in msgs)
        # But for project manifest part
        valid, proj_msgs = validator._validate_project_manifest()
        assert valid is True
        assert len(proj_msgs) == 0

    def test_validate_project_manifest_invalid_structure(self, tmp_path):
        """Test validation of invalid project_manifest.toml."""
        _write_project_manifest(
            tmp_path,
            """
[wrong_section]
id = "test"
""",
        )

        validator = ManifestValidator(tmp_path)
        valid, msgs = validator._validate_project_manifest()
        assert valid is False
        assert any("Missing required section [project]" in msg for msg in msgs)

    def test_validate_version_manifest_valid(self, tmp_path):
        """Test validation of valid .version_manifest.json."""
        _write_version_manifest(
            tmp_path,
            {
                "version": "1.0.0",
                "agent_core_version": "9.2.1+",
                "status": "canonical",
                "confidence": "high",
            },
        )

        validator = ManifestValidator(tmp_path)
        valid, msgs = validator._validate_version_manifest()
        assert valid is True
        assert len(msgs) == 0

    def test_validate_version_manifest_invalid_type(self, tmp_path):
        """Test validation of .version_manifest.json with wrong type."""
        _write_version_manifest(
            tmp_path,
            {
                "version": 1.0,  # Should be str
                "agent_core_version": "9.2.1+",
                "status": "canonical",
                "confidence": "high",
            },
        )

        validator = ManifestValidator(tmp_path)
        valid, msgs = validator._validate_version_manifest()
        assert valid is False
        assert any("must be str" in msg for msg in msgs)

    def test_legacy_version_alias_warning(self, tmp_path):
        """Test warning for legacy version alias in project manifest."""
        _write_project_manifest(
            tmp_path,
            """
version = "legacy_version"

[project]
id = "test_project"
version = "1.0.0"
""",
        )

        validator = ManifestValidator(tmp_path)
        _, msgs = validator._validate_project_manifest()
        assert any("Legacy 'version' field present" in msg for msg in msgs)

    def test_load_validated_manifests(self, tmp_path):
        """Test loading validated manifests."""
        _write_project_manifest(
            tmp_path,
            """
[project]
id = "test_project"
version = "1.0.0"
""",
        )

        _write_version_manifest(
            tmp_path,
            {
                "version": "1.0.0",
                "agent_core_version": "1.0.0",
                "status": "canonical",
                "confidence": "high",
            },
        )

        validator = ManifestValidator(tmp_path)
        proj, ver, warnings = validator.load_validated_manifests()
        assert proj is not None
        assert "project" in proj
        assert proj["project"]["id"] == "test_project"
        assert ver is not None
        assert ver["agent_core_version"] == "1.0.0"
        assert len(warnings) == 0

    def test_check_legacy_version_conflicts(self, tmp_path):
        """Test checking for conflicts between legacy version and agent_core_version."""
        _write_project_manifest(
            tmp_path,
            """
[project]
id = "test_project"
version = "1.0.0"
""",
        )

        _write_version_manifest(
            tmp_path,
            {
                "version": "1.0.0",
                "agent_core_version": "1.0.0",
                "status": "canonical",
                "confidence": "high",
            },
        )

        validator = ManifestValidator(tmp_path)
        warnings = validator._check_legacy_version_conflicts()
        # Versions match, no warning
        assert len(warnings) == 0

    def test_validate_version_manifest_without_legacy_version(self, tmp_path):
        """Test validation of .version_manifest.json without legacy version field."""
        _write_version_manifest(
            tmp_path,
            {
                "agent_core_version": "9.2.1+",
                "status": "canonical",
                "confidence": "high",
            },
        )

        validator = ManifestValidator(tmp_path)
        valid, msgs = validator._validate_version_manifest()
        assert valid is True
        assert len(msgs) == 0
