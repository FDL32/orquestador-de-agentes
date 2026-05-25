"""
Tests for scripts/doctor_agent_system.py (DoctorAgentSystem)

Covers: diagnosis, manifest repair, validation.
"""

import json

from scripts.doctor_agent_system import DoctorAgentSystem


class TestDoctorDiagnosis:
    """Test diagnosis functionality."""

    def test_diagnose_healthy_manifest(self, tmp_path):
        """Test diagnosis of healthy project with manifest."""
        project = tmp_path / "healthy"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create manifests
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        version_content = '{"agent_core_version": "1.0.0", "status": "canonical", "confidence": "high"}'
        (project / ".agent" / ".version_manifest.json").write_text(version_content)

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["severity"] == "healthy"
        assert diagnosis["detection"]["detection_mode"] == "manifest"

    def test_diagnose_legacy_markers(self, tmp_path):
        """Test diagnosis of legacy project with markers."""
        project = tmp_path / "legacy"
        project.mkdir()

        # Create legacy markers (v9.2.1+)
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["severity"] == "warning"
        assert diagnosis["detection"]["detection_mode"] == "legacy_markers"
        assert any("Legacy detection" in issue for issue in diagnosis["issues"])
        assert any(
            "Migrate to manifests" in rec for rec in diagnosis["recommendations"]
        )


class TestDoctorRepair:
    """Test manifest repair functionality."""

    def test_repair_manifest_legacy(self, tmp_path):
        """Test successful manifest repair from legacy markers."""
        project = tmp_path / "repair"
        project.mkdir()

        # Create legacy structure
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        doctor = DoctorAgentSystem(str(project))
        result = doctor.repair_manifest()

        assert result["success"] is True
        assert "Manifests created successfully" in result["message"]
        assert ".agent/project_manifest.toml" in result["created_files"]
        assert ".agent/.version_manifest.json" in result["created_files"]

        # Verify files exist
        assert (project / ".agent" / "project_manifest.toml").exists()
        assert (project / ".agent" / ".version_manifest.json").exists()

        # Verify content
        with open(project / ".agent" / ".version_manifest.json") as f:
            version_data = json.load(f)
        assert version_data["status"] == "recovered"
        assert version_data["confidence"] == "recovered_from_markers"

    def test_repair_manifest_already_exists(self, tmp_path):
        """Test repair when all manifests already exist."""
        project = tmp_path / "exists"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create existing manifests
        (project / ".agent" / "project_manifest.toml").write_text(
            "[project]\nid = 'existing'"
        )
        (project / ".agent" / ".version_manifest.json").write_text(
            '{"agent_core_version": "8.0.0"}'
        )

        doctor = DoctorAgentSystem(str(project))
        result = doctor.repair_manifest()

        assert result["success"] is True
        assert "All manifests exist" in result["message"]
        assert len(result["created_files"]) == 0

    def test_repair_manifest_not_initialized(self, tmp_path):
        """Test repair fails when no agent system."""
        project = tmp_path / "empty"
        project.mkdir()

        doctor = DoctorAgentSystem(str(project))
        result = doctor.repair_manifest()

        assert result["success"] is False
        assert "No agent system detected" in result["message"]

    def test_repair_manifest_partial_version_missing(self, tmp_path):
        """Test repair creates only .version_manifest.json when project_manifest.toml exists."""
        project = tmp_path / "partial"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create only project manifest
        (project / ".agent" / "project_manifest.toml").write_text("""
[project]
id = "test"
name = "Test"
version = "1.0.0"
""")

        doctor = DoctorAgentSystem(str(project))
        result = doctor.repair_manifest()

        assert result["success"] is True
        assert "Technical manifest created successfully" in result["message"]
        assert ".agent/.version_manifest.json" in result["created_files"]
        assert len(result["created_files"]) == 1

        # Verify content includes all required fields
        with open(project / ".agent" / ".version_manifest.json") as f:
            version_data = json.load(f)
        assert "agent_core_version" in version_data
        assert "components" in version_data
        assert "markers_validated" in version_data
        assert "drift_detected" in version_data
        assert version_data["status"] == "recovered"
        assert version_data["confidence"] == "recovered_from_markers"

    def test_repair_manifest_complete_spec(self, tmp_path):
        """Test that created manifests match complete spec."""
        project = tmp_path / "spec_test"
        project.mkdir()

        # Create legacy structure
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        doctor = DoctorAgentSystem(str(project))
        result = doctor.repair_manifest()

        assert result["success"] is True

        # Check project manifest
        with open(project / ".agent" / "project_manifest.toml") as f:
            content = f.read()
        assert "[project]" in content
        assert "[paths]" in content
        assert "[agent_system]" in content
        assert 'id = "spec_test"' in content  # Derived from directory name

        # Check version manifest has all required fields
        with open(project / ".agent" / ".version_manifest.json") as f:
            version_data = json.load(f)
        required_fields = [
            "agent_core_version",
            "template_version",
            "status",
            "confidence",
            "last_updated",
            "components",
            "markers_validated",
            "drift_detected",
        ]
        for field in required_fields:
            assert field in version_data


class TestDoctorValidation:
    """Test validation functionality."""

    def test_validate_healthy(self, tmp_path):
        """Test validation of healthy system."""
        project = tmp_path / "healthy"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create manifests
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        version_content = '{"agent_core_version": "1.0.0", "status": "canonical", "confidence": "high"}'
        (project / ".agent" / ".version_manifest.json").write_text(version_content)

        doctor = DoctorAgentSystem(str(project))
        validation = doctor.validate()

        assert validation["validation_passed"] is True
        assert validation["diagnosis"]["severity"] == "healthy"

    def test_validate_with_warnings(self, tmp_path):
        """Test validation shows warnings."""
        project = tmp_path / "warn"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create corrupt manifest
        (project / ".agent" / "project_manifest.toml").write_text("[invalid")

        doctor = DoctorAgentSystem(str(project))
        validation = doctor.validate()

        assert validation["validation_passed"] is False
        assert len(validation["diagnosis"]["issues"]) > 0


class TestDoctorDriftDetection:
    """Test drift detection functionality."""

    def test_diagnose_multiple_agent_dirs(self, tmp_path):
        """Test diagnosis detects multiple .agent directories."""
        project = tmp_path / "multi_agent"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / "subdir" / ".agent").mkdir(parents=True)

        # Create manifest
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["drift"]["detected"] is True
        assert diagnosis["drift"]["reparable"] is False
        assert any(
            "Multiple .agent/" in issue for issue in diagnosis["drift"]["details"]
        )
        assert diagnosis["severity"] == "error"

    def test_diagnose_paths_root_drift(self, tmp_path):
        """Test diagnosis detects paths.root drift."""
        project = tmp_path / "root_drift"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create manifest with non-canonical root
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"

[paths]
root = "some/other/path"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["drift"]["detected"] is True
        assert diagnosis["drift"]["reparable"] is False
        assert any(
            "paths.root drift" in issue for issue in diagnosis["drift"]["details"]
        )

    def test_diagnose_paths_agent_dir_drift(self, tmp_path):
        """Test diagnosis detects paths.agent_dir drift."""
        project = tmp_path / "agent_dir_drift"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create manifest with non-canonical agent_dir
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"

[paths]
agent_dir = "custom_agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["drift"]["detected"] is True
        assert diagnosis["drift"]["reparable"] is False
        assert any(
            "paths.agent_dir drift" in issue for issue in diagnosis["drift"]["details"]
        )

    def test_diagnose_reparable_drift(self, tmp_path):
        """Test diagnosis classifies partial manifests as reparable drift."""
        project = tmp_path / "partial"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create only version manifest
        version_content = '{"agent_core_version": "8.0.0", "status": "unknown"}'
        (project / ".agent" / ".version_manifest.json").write_text(version_content)

        doctor = DoctorAgentSystem(str(project))
        diagnosis = doctor.diagnose()

        assert diagnosis["drift"]["detected"] is True
        assert diagnosis["drift"]["reparable"] is True
        assert any(
            "partial manifests" in issue.lower()
            for issue in diagnosis["drift"]["details"]
        )

    def test_validate_drift_checks(self, tmp_path):
        """Test validation includes drift-specific checks."""
        project = tmp_path / "drift_validate"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / "another" / ".agent").mkdir(parents=True)

        # Create manifest
        manifest_content = """
[project]
id = "test"
name = "Test"
version = "1.0.0"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        doctor = DoctorAgentSystem(str(project))
        validation = doctor.validate()

        assert validation["validation_passed"] is False
        # Should have drift checks
        check_names = [check["check"] for check in validation["checks"]]
        assert "no_drift_detected" in check_names
        assert "drift_reparable" in check_names
        assert "single_agent_directory" in check_names
