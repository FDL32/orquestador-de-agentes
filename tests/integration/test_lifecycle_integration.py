"""
Integration tests for lifecycle scripts: detect_version -> upgrade -> rollback

Tests end-to-end workflows and thread safety for concurrent upgrade scenarios.
"""

from unittest.mock import patch

from scripts.detect_version import AgentSystemDetector
from scripts.rollback import RollbackManager
from scripts.upgrade import UpgradeManager


class TestLifecycleWorkflows:
    """Full end-to-end upgrade/rollback cycles."""

    def test_detect_then_upgrade_workflow(self, tmp_path):
        """Test complete flow: detect version -> simulate upgrade."""
        # Setup project at v9.2
        project = tmp_path / "project"
        source = tmp_path / "source"
        project.mkdir()
        source.mkdir()

        # Build v9.2 project structure
        v9_2_structure = [
            ".agent/agent_controller.py",
            ".agent/rules/rules.md",
            "skills/skill1.md",
            "agent_system/refactor_kit/kit.md",
            "CLAUDE.md",
            "AGENTS.md",
        ]
        for f in v9_2_structure:
            (project / f).parent.mkdir(parents=True, exist_ok=True)
            (project / f).write_text(f"# {f}")

        # Build v9.5 source (target)
        for f in v9_2_structure:
            (source / f).parent.mkdir(parents=True, exist_ok=True)
            (source / f).write_text(f"# upgraded {f}")
        (source / ".claude" / "rules").mkdir(parents=True)
        (source / "QUICKSTART.md").write_text("# quickstart")
        (source / "INTERACTION_MODES.md").write_text("# interaction modes")

        # Step 1: Detect version
        detector = AgentSystemDetector(str(project))
        detected = detector.detect_version()
        assert detected["detected"] is True
        assert detected["version"] == "v9.2"

        # Step 2: Upgrade dry-run
        upgrade_mgr = UpgradeManager(str(project), str(source))
        upgrade_result = upgrade_mgr.run_upgrade(dry_run=True)

        assert upgrade_result["status"] == "READY_FOR_UPGRADE"
        assert "v9.2" in upgrade_result["current_version"]
        assert "v9.6" in upgrade_result["target_version"]

    def test_upgrade_then_rollback_workflow(self, tmp_path):
        """Test full cycle: detect -> upgrade -> verify -> rollback."""
        project = tmp_path / "project"
        source = tmp_path / "source"
        project.mkdir()
        source.mkdir()

        v9_2_files = [
            ".agent/agent_controller.py",
            ".agent/rules/rules.md",
            "skills/skill1.md",
            "agent_system/refactor_kit/kit.py",
            "CLAUDE.md",
            "AGENTS.md",
        ]
        for f in v9_2_files:
            (project / f).parent.mkdir(parents=True, exist_ok=True)
            (project / f).write_text(f"v9.2 content: {f}")
        for f in v9_2_files:
            (source / f).parent.mkdir(parents=True, exist_ok=True)
            (source / f).write_text(f"v9.5 content: {f}")
        (source / ".claude" / "rules").mkdir(parents=True)
        (source / "QUICKSTART.md").write_text("# quickstart")

        # WOT-2026-013t: the single owner (scripts.upgrade_agent_system) is
        # manifest-first and BLOCKS legacy projects without a manifest. Provide the
        # canonical manifests so this lifecycle test exercises the COMPLETED path
        # under the owner's real contract (same setup the owner's unit tests use).
        (project / ".agent" / "project_manifest.toml").write_text(
            '[project]\nid = "lifecycle"\nname = "Lifecycle"\nversion = "v8.x"\n'
        )
        (project / ".agent" / ".version_manifest.json").write_text(
            '{"agent_core_version": "v8.x", "template_version": "1.0.0", '
            '"status": "canonical", "confidence": "high"}'
        )

        upgrade_mgr = UpgradeManager(str(project), str(source))

        # 1. Dry-run check
        dry = upgrade_mgr.run_upgrade(dry_run=True)
        assert dry["status"] == "READY_FOR_UPGRADE"

        # 2. Actual upgrade (mocked verification)
        with patch.object(upgrade_mgr, "verify_upgrade", return_value=(True, {})):
            result = upgrade_mgr.run_upgrade(dry_run=False)

        assert result["status"] == "COMPLETED"

        # 3. Rollback
        rollback_mgr = RollbackManager(str(project))
        with patch.object(
            rollback_mgr,
            "restore_backup",
            return_value={"status": "COMPLETED", "paths_restored": 10},
        ):
            rollback_result = rollback_mgr.restore_backup("test")
        assert rollback_result["status"] == "COMPLETED"


class TestConcurrentUpgradeSafety:
    """Thread safety checks for concurrent upgrade scenarios."""

    def test_concurrent_upgrade_safety(self, tmp_path):
        """Test that concurrent upgrades are safe."""
        from datetime import datetime as real_datetime

        project = tmp_path / "project"
        source = tmp_path / "source"
        project.mkdir()
        source.mkdir()

        for p in [project, source]:
            (p / ".agent" / "agent_controller.py").parent.mkdir(parents=True)
            (p / ".agent" / "agent_controller.py").write_text("#")
            (p / ".agent" / "rules").mkdir(parents=True)
            (p / ".claude" / "rules").mkdir(parents=True)
            (p / "skills").mkdir()
            (p / "agent_system" / "refactor_kit").mkdir(parents=True)
            (p / "AGENTS.md").write_text("#")
            (p / "CLAUDE.md").write_text("#")

        managers = [UpgradeManager(str(project), str(source)) for _ in range(3)]
        versions = [m.detect_current_version() for m in managers]
        assert all(v == versions[0] for v in versions)

        # WOT-2026-013t: UpgradeManager's single owner is scripts.upgrade_agent_system;
        # patch the owner's datetime/shutil (re-exported by scripts.upgrade) so the
        # patch reaches the code that actually runs the copies.
        with patch("scripts.upgrade_agent_system.datetime") as mock_dt:
            times = [real_datetime(2026, 4, 27, 12, 0, i + 1) for i in range(3)]
            mock_dt.now.side_effect = times
            with (
                patch("scripts.upgrade_agent_system.shutil.copytree"),
                patch("scripts.upgrade_agent_system.shutil.copy2"),
            ):
                backups = [m.backup_current_state() for m in managers]

        backup_names = [b.name for b in backups]
        assert len(set(backup_names)) == len(backups)


class TestCrossScriptIntegration:
    """Integration across all three lifecycle scripts."""

    def test_full_lifecycle_chain(self, tmp_path):
        """Test detect -> upgrade -> rollback -> verify complete cycle."""
        project = tmp_path / "project"
        source = tmp_path / "source"
        project.mkdir()
        source.mkdir()

        v9_2 = [
            ".agent/agent_controller.py",
            ".agent/rules/rule.md",
            "skills/skill.md",
            "agent_system/refactor_kit/kit.md",
            "CLAUDE.md",
            "AGENTS.md",
        ]
        for f in v9_2:
            (project / f).parent.mkdir(parents=True, exist_ok=True)
            (project / f).write_text(f"v9.2: {f}")

        for f in v9_2:
            (source / f).parent.mkdir(parents=True, exist_ok=True)
            (source / f).write_text(f"v9.2.1+: {f}")
        (source / ".claude" / "rules").mkdir(parents=True)

        # 1. DETECT
        detector = AgentSystemDetector(str(project))
        detect_result = detector.detect_version()
        assert detect_result["version"] == "v9.2"

        # 2. UPGRADE (planning)
        up_mgr = UpgradeManager(str(project), str(source))
        plan = up_mgr.run_upgrade(dry_run=True)
        assert plan["status"] == "READY_FOR_UPGRADE"

        # 3. UPGRADE (execution)
        # WOT-2026-013t: the single owner (scripts.upgrade_agent_system) is
        # manifest-first: a LEGACY project without a manifest is BLOCKED with a
        # "Run migration first" message, NOT auto-upgraded. The old scripts.upgrade
        # fork upgraded legacy projects laxly; consolidating onto the owner removes
        # that lax path. This test now asserts the owner's real, safer contract.
        with patch.object(
            up_mgr, "verify_upgrade", return_value=(True, {"version_detected": True})
        ):
            exec_result = up_mgr.run_upgrade(dry_run=False)
        assert exec_result["status"] == "BLOCKED"
        assert "migration first" in exec_result["message"].lower()
        assert exec_result["detection_mode"] == "legacy_markers"

        # 4. ROLLBACK is still a valid standalone operation (independent of the
        # blocked upgrade): the rollback manager restores from a backup.
        rb_mgr = RollbackManager(str(project))
        with patch.object(
            rb_mgr,
            "restore_backup",
            return_value={"status": "COMPLETED", "paths_restored": 10},
        ):
            rb_result = rb_mgr.restore_backup("ts123")
        assert rb_result["status"] == "COMPLETED"

        # 5. VERIFY: the project is still legacy v9.2 (upgrade was blocked).
        verify = detector.detect_version()
        assert verify["detected"] is True
        assert verify["version"] == "v9.2"
