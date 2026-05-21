"""
Tests for scripts/migrate_legacy_project.py (LegacyMigrationManager)

Covers: auto analysis, confirm migration, manifest creation, multiple .agent/ handling.
"""

import shutil
from pathlib import Path

import pytest
from scripts.migrate_legacy_project import LegacyMigrationManager


@pytest.fixture(autouse=True)
def isolate_repo_agent_dir():
    """Temporarily hide the repository .agent directory for isolation."""
    repo_root = Path(__file__).resolve().parents[2]
    agent_dir = repo_root / ".agent"
    hidden_dir = repo_root / ".agent.__pytest_hidden__"
    moved = False

    if hidden_dir.exists() and not agent_dir.exists():
        hidden_dir.rename(agent_dir)

    if agent_dir.exists():
        if hidden_dir.exists():
            shutil.rmtree(hidden_dir)
        agent_dir.rename(hidden_dir)
        moved = True

    try:
        yield
    finally:
        if moved and hidden_dir.exists():
            hidden_dir.rename(agent_dir)


class TestMigrateAuto:
    """Test auto migration analysis."""

    def test_auto_migrate_no_action_needed(self, tmp_path):
        """Test auto migrate when no action needed."""
        project = tmp_path / "ready"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create complete manifests
        manifest_content = """[project]
id = "test"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)
        (project / ".agent" / ".version_manifest.json").write_text('{"agent_core_version": "8.0.0"}')

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is False
        assert "already migrated" in " ".join(analysis["issues"]).lower()

    def test_auto_migrate_legacy_markers(self, tmp_path):
        """Test auto migrate detects legacy markers."""
        project = tmp_path / "legacy"
        project.mkdir()

        # Create legacy structure
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is True
        assert "Legacy marker-based detection" in analysis["issues"]
        assert "Create project_manifest.toml" in analysis["actions"]
        assert "Create .version_manifest.json" in analysis["actions"]

    def test_auto_migrate_partial_manifests(self, tmp_path):
        """Test auto migrate detects partial manifests."""
        project = tmp_path / "partial"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create only project manifest
        (project / ".agent" / "project_manifest.toml").write_text("[project]\nid = 'test'")

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is True
        assert "Missing .version_manifest.json" in analysis["issues"]
        assert "Create technical manifest" in analysis["actions"]

    def test_auto_migrate_not_initialized(self, tmp_path):
        """Test auto migrate handles uninitialized projects."""
        project = tmp_path / "empty"
        project.mkdir()

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is False
        assert "Project not initialized" in analysis["issues"]
        assert "Run install_agent_system.py first" in analysis["recommendations"]

    def test_auto_migrate_multiple_agent_dirs(self, tmp_path):
        """Test auto migrate reports multiple .agent directories."""
        project = tmp_path / "multiple"
        project.mkdir()

        # Create multiple .agent directories
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / "subdir" / ".agent").mkdir(parents=True)

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is True
        assert "Multiple .agent directories found" in " ".join(analysis["issues"])
        assert "Consolidate to canonical .agent/ at .agent" in analysis["actions"]
        assert analysis["canonical_agent"] == ".agent"


class TestMigrateConfirm:
    """Test confirm migration execution."""

    def test_confirm_migrate_legacy_to_manifests(self, tmp_path):
        """Test confirm migrate creates manifests from legacy."""
        project = tmp_path / "legacy_to_manifest"
        project.mkdir()

        # Create legacy structure
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is True
        assert "Migration completed successfully" in result["message"]
        assert ".agent/project_manifest.toml" in result["changes"]
        assert ".agent/.version_manifest.json" in result["changes"]

        # Verify manifests created
        assert (project / ".agent" / "project_manifest.toml").exists()
        assert (project / ".agent" / ".version_manifest.json").exists()

    def test_confirm_migrate_partial_manifests(self, tmp_path):
        """Test confirm migrate completes partial manifests."""
        project = tmp_path / "partial_complete"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create only project manifest
        (project / ".agent" / "project_manifest.toml").write_text("[project]\nid = 'test'")

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is True
        assert ".agent/.version_manifest.json" in result["changes"]

        # Verify version manifest created
        assert (project / ".agent" / ".version_manifest.json").exists()

    def test_confirm_migrate_multiple_agent_dirs(self, tmp_path):
        """Test confirm migrate consolidates multiple .agent directories."""
        project = tmp_path / "multiple_agent"
        project.mkdir()

        # Create multiple .agent directories
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "file1.txt").write_text("root content")
        sub_agent = project / "subdir" / ".agent"
        sub_agent.mkdir(parents=True)
        (sub_agent / "file2.txt").write_text("subdir content")
        (sub_agent / "file1.txt").write_text("conflict content")  # Conflict

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is True
        assert "Consolidated file2.txt" in " ".join(result["changes"])
        assert "Removed duplicate" in " ".join(result["changes"])
        assert any("Conflict for file1.txt" in w for w in result["warnings"])

        # Check consolidation
        assert (project / ".agent" / "file1.txt").read_text() == "root content"  # Kept root
        assert (project / ".agent" / "file2.txt").read_text() == "subdir content"  # Consolidated
        assert not sub_agent.exists()  # Removed

    def test_confirm_migrate_no_action_needed(self, tmp_path):
        """Test confirm migrate when no action needed."""
        project = tmp_path / "no_action"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create complete manifests
        manifest_content = """[project]
id = "test"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)
        (project / ".agent" / ".version_manifest.json").write_text('{"agent_core_version": "8.0.0"}')

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is True
        assert "No migration needed" in result["message"]
        assert len(result["changes"]) == 0

    def test_auto_migrate_detects_drift(self, tmp_path):
        """Test auto migrate detects route drift."""
        project = tmp_path / "drift"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create drifted manifest
        manifest_content = """[project]
id = "test"
version = "1.0.0"

[paths]
root = "wrong"
agent_dir = ".nonexistent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        manager = LegacyMigrationManager(str(project))
        analysis = manager.auto_migrate()

        assert analysis["migration_needed"] is True
        assert any("Drift in paths.root" in issue for issue in analysis["issues"])
        assert any("Drift in paths.agent_dir" in issue for issue in analysis["issues"])
        assert "Correct route drift in manifests" in analysis["actions"]

    def test_confirm_migrate_corrects_drift(self, tmp_path):
        """Test confirm migrate corrects repairable drift."""
        project = tmp_path / "drift_correct"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")

        # Create manifest with wrong root
        manifest_content = """
[project]
id = "test"
version = "1.0.0"

[paths]
root = "wrong"
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is True
        assert ".agent/.version_manifest.json" in result["changes"]

        # Verify correction
        with open(project / ".agent" / "project_manifest.toml") as f:
            content = f.read()
        assert 'root = "."' in content

    def test_confirm_migrate_blocks_ambiguous_drift(self, tmp_path):
        """Test confirm migrate blocks ambiguous drift."""
        project = tmp_path / "drift_ambiguous"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")  # .agent exists
        (project / ".nonexistent").mkdir()  # Declared alternative also exists, making drift ambiguous

        # Create manifest with wrong agent_dir and two plausible paths
        manifest_content = """
[project]
id = "test"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".nonexistent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        manager = LegacyMigrationManager(str(project))
        result = manager.confirm_migrate()

        assert result["success"] is False
        assert "Route drift correction failed" in " ".join(result["warnings"])
