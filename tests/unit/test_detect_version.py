"""
Tests for scripts/detect_version.py (AgentSystemDetector)

Covers: manifest-first detection, version fingerprinting, confidence scoring, upgrade paths, fail-safe defaults.
"""

import json

from scripts.detect_version import AgentSystemDetector


def detect_version(project_dir: str):
    """Helper to call detect_version from AgentSystemDetector."""
    detector = AgentSystemDetector(project_dir)
    return detector.detect_version()


class TestVersionDetection:
    """Test version detection for all agent system versions."""

    def test_detect_v8x_structures(self, tmp_path):
        """Test detection of v8.x architectural patterns."""
        # v8.x markers: .agent/agent_controller.py, scripts/run_pytest_safe.py
        # Optional: .agent/hooks/guard_paths.py, .agent/collaboration/
        # Absent: .agent/rules, skills, AGENTS.md, orquestador_de_agentes

        project = tmp_path / "v8x_project"
        project.mkdir()

        # Required
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("# v8 controller")
        (project / "scripts").mkdir()
        (project / "scripts" / "run_pytest_safe.py").write_text("# v8 script")

        # Optional present
        (project / ".agent" / "hooks").mkdir()
        (project / ".agent" / "hooks" / "guard_paths.py").write_text("# hook")
        (project / ".agent" / "collaboration").mkdir()

        # Absent markers (implicitly absent in tmp_path)
        # .agent/rules, skills/, AGENTS.md, orquestador_de_agentes not created

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_markers"
        assert result["legacy_version"] == "v8.x"
        assert result["confidence"] == "high"
        details = result["details"]
        assert details["required_met"] is True
        assert details["absent_violated"] is False

    def test_detect_v9_0_structures(self, tmp_path):
        """Test detection of v9.0-v9.1 patterns."""
        # v9.0-v9.1: .agent/agent_controller.py, .agent/rules/, skills/, CLAUDE.md
        # Optional: scripts/discover_skills.py, .agent/collaboration/
        # Absent: .claude/rules, AGENTS.md, agent_system/refactor_kit

        project = tmp_path / "v9_0_project"
        project.mkdir()

        # Required
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("# v9 controller")
        (project / ".agent" / "rules").mkdir()
        (project / "skills").mkdir()
        (project / "CLAUDE.md").write_text("# CLAUDE")

        # Optional
        (project / "scripts").mkdir(exist_ok=True)
        (project / "scripts" / "discover_skills.py").write_text("# discover")
        (project / ".agent" / "collaboration").mkdir()

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_markers"
        assert result["legacy_version"] == "v9.0-v9.1"
        assert result["confidence"] == "high"

    def test_detect_v9_2_structures(self, tmp_path):
        """Test detection of v9.2 patterns."""
        # v9.2: + agent_system/refactor_kit/, optional orquestador_de_agentes/, AGENTS.md
        # Absent: .claude/rules (pre-9.2.1)

        project = tmp_path / "v9_2_project"
        project.mkdir()

        # Required (v9.0-v9.1 + agent_system/refactor_kit/)
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("# v9.2")
        (project / ".agent" / "rules").mkdir()
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "CLAUDE.md").write_text("# CLAUDE")
        (project / "AGENTS.md").write_text("# AGENTS")  # Required in v9.2.1+ but optional in v9.2

        # Absent: .claude/rules should NOT exist

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_markers"
        # Since v9.2 requires agent_system/refactor_kit and optional AGENTS.md
        # Without .claude/rules, it matches v9.2
        assert result["legacy_version"] == "v9.2"
        assert result["confidence"] == "high"

    def test_detect_v9_6_structures(self, tmp_path):
        """Test detection of current v9.6 patterns."""
        # v9.6: v9.5 surface + isolated eval lane contract

        project = tmp_path / "v9_2_1_project"
        project.mkdir()

        # All required markers
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("# controller")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude").mkdir()
        (project / ".claude" / "rules").mkdir()
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("# agents")
        (project / "CLAUDE.md").write_text("# claude")
        (project / "QUICKSTART.md").write_text("# quickstart")
        (project / "INTERACTION_MODES.md").write_text("# interaction modes")
        (project / "scripts").mkdir()
        (project / "scripts" / "run_llm_evals.py").write_text("# evals")
        (project / ".agent" / "runtime").mkdir(parents=True)
        (project / ".agent" / "runtime" / "llm_evals_config.json").write_text(
            '{"model": "gpt-4o-mini", "metrics": ["relevance"], "dataset_path": "data.jsonl"}'
        )

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_markers"
        assert result["legacy_version"] == "v9.6"
        assert result["confidence"] == "high"

    def test_confidence_scoring_high(self, tmp_path):
        """Test high confidence when all required markers present."""
        project = tmp_path / "confident"
        project.mkdir()
        # Build v9.6 full structure
        (project / ".agent" / "agent_controller.py").parent.mkdir(parents=True)
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir(parents=True)
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")
        (project / "QUICKSTART.md").write_text("#")
        (project / "INTERACTION_MODES.md").write_text("#")
        (project / "scripts").mkdir()
        (project / "scripts" / "run_llm_evals.py").write_text("#")
        (project / ".agent" / "runtime").mkdir(parents=True)
        (project / ".agent" / "runtime" / "llm_evals_config.json").write_text(
            '{"model": "gpt-4o-mini", "metrics": ["relevance"], "dataset_path": "data.jsonl"}'
        )

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["confidence"] == "high"
        details = result["details"]
        assert details["required_met"] is True

    def test_confidence_scoring_low(self, tmp_path):
        """Test low confidence when only partial markers present."""
        project = tmp_path / "partial"
        project.mkdir()
        # Only some required markers for v9.6
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        # Missing: .agent/rules, .claude/rules, skills, etc.

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        # Partial match -> should still detect something but with low confidence
        assert result["detected"] is True
        assert result.get("confidence") == "low"
        assert "Partial legacy match" in result.get("message", "")

    def test_upgrade_path_suggestion(self):
        """Test upgrade path recommendations for each version."""
        # Use a dummy detector to test the method
        detector = AgentSystemDetector(".")
        # The method exists on the class; we test it directly
        path_v8 = detector.suggest_upgrade_path("v8.x")
        assert "v9.0-v9.1" in path_v8
        path_v9_0 = detector.suggest_upgrade_path("v9.0-v9.1")
        assert "v9.2" in path_v9_0
        path_v9_2 = detector.suggest_upgrade_path("v9.2")
        assert "v9.2.1+" in path_v9_2
        path_latest = detector.suggest_upgrade_path("v9.2.1+")
        assert "v9.6" in path_latest
        path_v9_5 = detector.suggest_upgrade_path("v9.5")
        assert "v9.6" in path_v9_5
        assert detector.suggest_upgrade_path("v9.6") == "Already latest"

    def test_fail_safe_defaults_no_agent_dir(self, tmp_path):
        """Test graceful handling when .agent/ is absent."""
        project = tmp_path / "empty"
        project.mkdir()

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        # Should not crash, should return detected=False
        assert result.get("detected") is False
        assert "No agent system found" in result.get("message", "")

    def test_fail_safe_defaults_corrupted_structure(self, tmp_path):
        """Test handling of partially corrupted agent system."""
        project = tmp_path / "corrupted"
        project.mkdir()

        # .agent exists but missing critical files
        (project / ".agent").mkdir()
        (project / ".agent" / "some_file.txt").write_text("nope")

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        # Should not crash. Should try to find closest match or fail gracefully
        assert "detected" in result
        # Likely detected=False or partial match with low confidence
        if result.get("detected"):
            assert result.get("confidence") in ("low", "unknown")

    def test_detect_manifest_first(self, tmp_path):
        """Test manifest-first detection with project_manifest.toml."""
        project = tmp_path / "manifest_project"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create project_manifest.toml
        manifest_content = """
[project]
id = "test_project"
name = "Test Project"
version = "1.0.0"

[paths]
root = "."
agent_dir = ".agent"
"""
        (project / ".agent" / "project_manifest.toml").write_text(manifest_content)

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "manifest"
        assert result["project_id"] == "test_project"
        assert result["status"] == "canonical"
        assert result["confidence"] == "high"
        assert "canonical_agent_root" in result

    def test_detect_version_manifest(self, tmp_path):
        """Test detection via .version_manifest.json."""
        project = tmp_path / "version_manifest_project"
        project.mkdir()
        (project / ".agent").mkdir()

        # Create .version_manifest.json
        version_manifest = {
            "agent_core_version": "8.2.0",
            "template_version": "1.0.0",
            "status": "recovered",
            "confidence": "high",
            "last_updated": "2026-04-28T22:00:00+02:00"
        }
        (project / ".agent" / ".version_manifest.json").write_text(json.dumps(version_manifest))

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "version_manifest"
        assert result["agent_core_version"] == "8.2.0"
        assert result["status"] == "recovered"
        assert result["confidence"] == "high"
        assert "canonical_agent_root" in result

    def test_detect_legacy_fallback(self, tmp_path):
        """Test fallback to legacy markers when no manifests."""
        project = tmp_path / "legacy_project"
        project.mkdir()

        # Create v9.2.1+ structure
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir()
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_markers"
        assert result["legacy_version"] == "v9.2.1+"
        assert result["status"] == "legacy"
        assert result["confidence"] == "high"

    def test_detect_not_initialized(self, tmp_path):
        """Test detection when no agent system is present."""
        project = tmp_path / "empty_project"
        project.mkdir()

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        assert result["detected"] is False
        assert result["detection_mode"] == "not_initialized"
        assert "No agent system found" in result["message"]

    def test_detect_corrupt_manifest_fallback(self, tmp_path):
        """Test handling of corrupt project_manifest.toml falls back to legacy."""
        project = tmp_path / "corrupt_manifest"
        project.mkdir()
        (project / ".agent").mkdir()
        (project / ".agent" / "agent_controller.py").write_text("# controller")

        # Corrupt TOML
        (project / ".agent" / "project_manifest.toml").write_text("[invalid toml")

        detector = AgentSystemDetector(str(project))
        result = detector.detect_version()

        # Should continue to legacy detection
        assert result["detected"] is True
        assert result["detection_mode"] == "legacy_partial"  # Since no full markers
        assert "Partial legacy match" in result["message"]


class TestVersionIntegration:
    """Integration tests for detect_version."""

    def test_detect_version_returns_dict(self, tmp_path):
        """Test calling detect_version directly returns proper dict."""
        # Create minimal v9.2.1+ structure
        project = tmp_path / "minimal"
        project.mkdir()
        (project / ".agent" / "agent_controller.py").parent.mkdir(parents=True)
        (project / ".agent" / "agent_controller.py").write_text("#")
        (project / ".agent" / "rules").mkdir(parents=True)
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "skills").mkdir()
        (project / "agent_system" / "refactor_kit").mkdir(parents=True)
        (project / "AGENTS.md").write_text("#")
        (project / "CLAUDE.md").write_text("#")

        result = detect_version(str(project))

        assert isinstance(result, dict)
        assert "detected" in result
        assert "version" in result or "message" in result
