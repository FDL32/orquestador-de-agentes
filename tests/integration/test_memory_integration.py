"""Integration tests for memory_consolidate.py and memory_loader.py."""

import json
from pathlib import Path
from unittest.mock import patch

from bus import memory_loader
from scripts import memory_consolidate


class TestMemoryLoaderIntegration:
    """Tests integration between consolidation generation and loader consumption."""

    def test_consolidate_and_load(self, tmp_path: Path) -> None:
        """Test the full pipeline: observations -> consolidation -> loader."""
        agent_dir = tmp_path / ".agent"
        memory_dir = agent_dir / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        obs_file = memory_dir / "observations.jsonl"
        rules_file = memory_dir / "memory_rules.md"
        profile_file = memory_dir / "memory_profile.md"

        # Mock paths for both modules
        with (
            patch("scripts.memory_consolidate.OBS", obs_file),
            patch("scripts.memory_consolidate.MEMORY_DIR", memory_dir),
            patch("scripts.memory_consolidate.ARCHIVE_DIR", memory_dir / "archive"),
            patch("scripts.memory_consolidate.MEMORY_MD", memory_dir / "MEMORY.md"),
            patch("scripts.memory_consolidate.REPORT", memory_dir / "REPORT.md"),
            patch("scripts.memory_consolidate.MEMORY_RULES_MD", rules_file),
            patch("scripts.memory_consolidate.MEMORY_PROFILE_MD", profile_file),
            patch("bus.memory_loader._get_memory_dir", return_value=memory_dir),
        ):
            # 1. Create raw observations
            obs_data = [
                {
                    "timestamp": "2026-05-30T10:00:00Z",
                    "topic": "security",
                    "domain": "security-gates",
                    "signal": "Security gates must fail closed on invalid config. Silent permissive fallback is incredibly dangerous (AP-11).",
                    "source_ticket": "WP-001",
                },
                {
                    "timestamp": "2026-05-30T10:05:00Z",
                    "topic": "testing",
                    "domain": "testing",
                    "signal": "Use pytest fixtures instead of setup methods for better maintainability and scoped resources (AP-12).",
                    "source_ticket": "WP-002",
                },
            ]
            with open(obs_file, "w", encoding="utf-8") as f:
                for entry in obs_data:
                    f.write(json.dumps(entry) + "\n")

            # 2. Run consolidation pipeline directly
            recent, stats, _dropped, _deduped = memory_consolidate._run_pipeline(
                type(
                    "Args",
                    (),
                    {"apply": True, "dry_run": False, "since": "30d", "verbose": False},
                )()
            )
            memory_consolidate._apply_consolidation(recent, [], stats, False)

            # 3. Verify L2/L3 files were created
            assert rules_file.exists()
            assert profile_file.exists()

            # 4. Verify Loader consumes them properly
            # Bootstrap should return profile (L3)
            bootstrap_ctx = memory_loader.get_bootstrap_context()
            assert "Memory Profile (L3)" in bootstrap_ctx
            assert "Total observations: 2" in bootstrap_ctx

            # Review should return rules (L2) filtered by domain
            review_ctx_sec = memory_loader.get_review_context("security-gates")
            assert "## Domain: security-gates" in review_ctx_sec
            assert "AP-11" in review_ctx_sec
            assert "AP-12" not in review_ctx_sec  # Filtered out

            # Compact should return L3 + L2
            compact_ctx = memory_loader.get_compact_context()
            assert "Memory Profile (L3)" in compact_ctx
            assert "Memory Rules (L2)" in compact_ctx
