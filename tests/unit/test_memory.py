"""
Tests for bus/memory_loader.py (WP-2026-178).

Covers:
- L3 -> L2 -> L1 fallback hierarchy
- get_bootstrap_context() with various memory states
- get_review_context() with domain filtering
- get_compact_context() combining L2+L3
- recall_observations() keyword filtering
- Edge cases: missing files, empty files, corrupted data
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


# Ensure project root is in sys.path for importing from bus/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bus.memory_loader import (  # noqa: E402
    _try_read_file,
    get_bootstrap_context,
    get_compact_context,
    get_memory_tier_status,
    get_review_context,
    recall_observations,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_memory_files(
    tmp_path: Path,
    observations: list[dict] | None = None,
    memory_rules: str | None = None,
    memory_profile: str | None = None,
) -> Path:
    """Create mock memory files in tmp_path and return the directory Path."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    if observations is not None:
        obs_path = mem_dir / "observations.jsonl"
        lines = "\n".join(json.dumps(o, ensure_ascii=False) for o in observations)
        obs_path.write_text(lines + "\n", encoding="utf-8")

    if memory_rules is not None:
        (mem_dir / "memory_rules.md").write_text(memory_rules, encoding="utf-8")

    if memory_profile is not None:
        (mem_dir / "memory_profile.md").write_text(memory_profile, encoding="utf-8")

    return mem_dir


# =============================================================================
# Tests for _try_read_file
# =============================================================================


class TestTryReadFile:
    def test_file_exists(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        assert _try_read_file(f) == "hello"

    def test_file_missing(self, tmp_path: Path) -> None:
        assert _try_read_file(tmp_path / "nonexistent.txt") == ""

    def test_io_error(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("denied")):
            result = _try_read_file(f)
        assert result == ""


# =============================================================================
# Tests for get_bootstrap_context (L3 -> L2 -> L1)
# =============================================================================


class TestGetBootstrapContext:
    def test_returns_l3_when_available(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            memory_profile="# L3 Profile\nActive domains: testing",
            memory_rules="# L2 Rules\n## Domain: testing\nRule text",
            observations=[{"signal": "obs1", "timestamp": "2026-05-30T10:00:00Z"}],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_bootstrap_context()

        assert "# L3 Profile" in ctx
        assert "Active domains" in ctx
        # L2 should NOT appear (L3 takes priority)
        assert "# L2 Rules" not in ctx

    def test_falls_back_to_l2_when_no_l3(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            memory_rules="# L2 Rules\n## Domain: testing\nRule text",
            observations=[{"signal": "obs1", "timestamp": "2026-05-30T10:00:00Z"}],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_bootstrap_context()

        assert "# L2 Rules" in ctx
        assert "## Domain: testing" in ctx

    def test_falls_back_to_l1_when_no_l2_l3(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            observations=[
                {
                    "signal": "obs1",
                    "topic": "test",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "builder",
                },
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_bootstrap_context()

        assert "Raw Observations" in ctx or "obs1" in ctx

    def test_returns_empty_when_no_memory(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_bootstrap_context()
        assert ctx == ""


# =============================================================================
# Tests for get_review_context (L2 by domain)
# =============================================================================


class TestGetReviewContext:
    L2_SAMPLE = (
        "# Memory Rules (L2)\n\n"
        "## Domain: Testing\n\n"
        "### R-001: Rule about tests\n\nTest rule text\n\n"
        "## Domain: Security\n\n"
        "### R-002: Security gate rule\n\nSecurity text\n\n"
    )

    def test_returns_all_rules_when_domain_none(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path, memory_rules=self.L2_SAMPLE)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_review_context(domain=None)
        assert "Testing" in ctx
        assert "Security" in ctx

    def test_filters_by_domain(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path, memory_rules=self.L2_SAMPLE)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_review_context(domain="testing")
        assert "R-001: Rule about tests" in ctx
        assert "Security" not in ctx

    def test_fallback_to_l1_when_no_l2(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            observations=[
                {
                    "signal": "obs1",
                    "topic": "test",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "builder",
                }
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_review_context(domain="test")
        assert "obs1" in ctx or "Raw Observations" in ctx

    def test_case_insensitive_domain_match(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path, memory_rules=self.L2_SAMPLE)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_review_context(domain="TESTING")
        assert "R-001: Rule about tests" in ctx


# =============================================================================
# Tests for get_compact_context (L3 + L2)
# =============================================================================


class TestGetCompactContext:
    def test_combines_l3_and_l2(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            memory_profile="# L3 Profile\nActive: testing",
            memory_rules="# L2 Rules\n## Domain: testing\nRule",
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_compact_context()
        assert "# L3 Profile" in ctx
        assert "# L2 Rules" in ctx
        assert "---" in ctx  # Separator between tiers

    def test_only_l3(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path, memory_profile="# L3 Profile\nActive: testing"
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_compact_context()
        assert "# L3 Profile" in ctx
        assert "# L2 Rules" not in ctx

    def test_fallback_to_l1(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            observations=[
                {
                    "signal": "obs1",
                    "topic": "test",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "builder",
                }
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_compact_context()
        assert "obs1" in ctx or "Raw Observations" in ctx

    def test_empty_when_no_memory(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_compact_context()
        assert ctx == ""


# =============================================================================
# Tests for recall_observations (L1 direct)
# =============================================================================


class TestRecallObservations:
    def test_returns_recent_observations(self, tmp_path: Path) -> None:
        observations = [
            {
                "signal": f"obs{i}",
                "topic": "test",
                "timestamp": f"2026-05-{30 - i:02d}T10:00:00Z",
                "source": "builder",
            }
            for i in range(5)
        ]
        mem_dir = _make_memory_files(tmp_path, observations=observations)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            result = recall_observations(limit=3)
        assert len(result) == 3

    def test_filter_by_keyword(self, tmp_path: Path) -> None:
        observations = [
            {
                "signal": "security finding",
                "topic": "security",
                "timestamp": "2026-05-30T10:00:00Z",
                "source": "audit",
            },
            {
                "signal": "testing result",
                "topic": "testing",
                "timestamp": "2026-05-29T10:00:00Z",
                "source": "builder",
            },
        ]
        mem_dir = _make_memory_files(tmp_path, observations=observations)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            result = recall_observations(query="security", limit=5)
        assert len(result) == 1
        assert result[0]["signal"] == "security finding"

    def test_empty_when_no_observations(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            result = recall_observations()
        assert result == []

    def test_query_finds_old_observations_beyond_recent_window(
        self, tmp_path: Path
    ) -> None:
        """Barrier: keyword recall must scan the FULL file, not a recent window.

        Previous behavior read only limit*2 recent entries before filtering,
        so a query matching only an old observation returned empty. This test
        would fail under that window-then-filter implementation.
        """
        old_match = {
            "signal": "ancient unique-needle finding",
            "topic": "archaeology",
            "timestamp": "2026-01-01T10:00:00Z",
            "source": "audit",
        }
        recent_noise = [
            {
                "signal": f"recent noise {i}",
                "topic": "noise",
                "timestamp": f"2026-05-{(i % 28) + 1:02d}T10:00:00Z",
                "source": "builder",
            }
            for i in range(20)
        ]
        # Oldest first in the file; the match is the very first line.
        mem_dir = _make_memory_files(tmp_path, observations=[old_match, *recent_noise])
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            # limit=3 -> old window was 6 entries; the needle is 21 entries deep.
            result = recall_observations(query="unique-needle", limit=3)
        assert len(result) == 1
        assert result[0]["signal"] == "ancient unique-needle finding"


# =============================================================================
# Tests for get_memory_tier_status
# =============================================================================


class TestMemoryTierStatus:
    def test_all_tiers_present(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            memory_profile="profile",
            memory_rules="rules",
            observations=[
                {
                    "signal": "s1",
                    "topic": "t",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "b",
                }
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            status = get_memory_tier_status()
        assert status == {"l3": True, "l2": True, "l1": True}

    def test_no_tiers(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path)
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            status = get_memory_tier_status()
        assert status == {"l3": False, "l2": False, "l1": False}

    def test_partial_tiers(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(tmp_path, memory_profile="profile")
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            status = get_memory_tier_status()
        assert status == {"l3": True, "l2": False, "l1": False}


# =============================================================================
# Edge cases: corrupted files, encoding issues
# =============================================================================


class TestEdgeCases:
    def test_corrupted_observations_skips_bad_lines(self, tmp_path: Path) -> None:
        obs_dir = tmp_path / "memory"
        obs_dir.mkdir(parents=True)
        obs_path = obs_dir / "observations.jsonl"
        obs_path.write_text(
            '{"signal": "valid", "topic": "t", "timestamp": "2026-05-30T10:00:00Z", "source": "b"}\n'
            "not json\n"
            '{"signal": "valid2", "topic": "t2", "timestamp": "2026-05-29T10:00:00Z", "source": "b"}\n',
            encoding="utf-8",
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=obs_dir):
            result = recall_observations(limit=5)
        # The function reads from end, so "valid2" comes first
        assert len(result) == 2

    def test_l2_with_unexpected_format(self, tmp_path: Path) -> None:
        """get_review_context should handle L2 files with unusual content gracefully."""
        mem_dir = _make_memory_files(
            tmp_path,
            memory_rules="# Memory Rules\nRandom content without domain sections",
            observations=[
                {
                    "signal": "l1 fallback",
                    "topic": "t",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "b",
                }
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            ctx = get_review_context(domain="nonexistent")
        # Should return all rules as fallback when domain not found
        assert "Memory Rules" in ctx

    def test_recall_observations_no_match(self, tmp_path: Path) -> None:
        mem_dir = _make_memory_files(
            tmp_path,
            observations=[
                {
                    "signal": "unique signal",
                    "topic": "t",
                    "timestamp": "2026-05-30T10:00:00Z",
                    "source": "b",
                }
            ],
        )
        with patch("bus.memory_loader._get_memory_dir", return_value=mem_dir):
            result = recall_observations(query="nonexistent_keyword", limit=5)
        assert result == []
