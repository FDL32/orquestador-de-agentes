"""
Tests for scripts/discover_skills.py

Covers: file enumeration, frontmatter parsing, trigger uniqueness, mapping generation,
invalid SKILL.md handling, description extraction.
"""

from pathlib import Path
import pytest
from scripts.discover_skills import discover_skills, extract_frontmatter


class TestSkillDiscovery:
    """Test skill discovery and trigger mapping."""

    def test_discover_skills_finds_all_skill_files(self, tmp_path):
        """Test that discover_skills enumerates all SKILL.md files."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        for skill_name in ["incense", "candles", "rosary"]:
            skill_path = skills_dir / skill_name
            skill_path.mkdir()
            skill_file = skill_path / "SKILL.md"
            skill_file.write_text(f"---\nname: {skill_name}\ntriggers: [/{skill_name}]\n---\n")

        result = discover_skills(skills_dir)

        assert result["total_skills"] == 3
        assert len(result["skills"]) == 3
        names = {s["name"] for s in result["skills"]}
        assert names == {"incense", "candles", "rosary"}

    def test_skill_frontmatter_parsing(self):
        """Test extraction of YAML frontmatter from SKILL.md."""
        content = "---\nname: Test Skill\ntriggers: [/test, testing]\ndescription: A test skill\nversion: 1.2.3\n---\nBody text"
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
            f.write(content)
            temp_path = Path(f.name)
        try:
            fm = extract_frontmatter(temp_path)
            assert fm["name"] == "Test Skill"
            assert fm["triggers"] == ["/test", "testing"]
            assert fm["description"] == "A test skill"
            assert fm["version"] == "1.2.3"
        finally:
            temp_path.unlink()

    def test_trigger_uniqueness_no_collisions(self, tmp_path):
        """Test that no two skills share the same trigger."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        (skills_dir / "skill_a").mkdir()
        (skills_dir / "skill_a" / "SKILL.md").write_text("---\nname: Skill A\ntriggers: [/a, /unique]\n---")
        (skills_dir / "skill_b").mkdir()
        (skills_dir / "skill_b" / "SKILL.md").write_text("---\nname: Skill B\ntriggers: [/b]\n---")

        result = discover_skills(skills_dir)
        trigger_map = result["trigger_map"]
        assert len(trigger_map) == 3

    def test_trigger_map_generation(self, tmp_path):
        """Test that trigger_map correctly maps triggers to skill file paths."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_name = "candles"
        (skills_dir / skill_name).mkdir()
        skill_file = skills_dir / skill_name / "SKILL.md"
        skill_file.write_text("---\nname: Candles\ntriggers: [/candle, /candles]\ndescription: Liturgical candles\n---")

        result = discover_skills(skills_dir)
        assert "/candle" in result["trigger_map"]
        assert "/candles" in result["trigger_map"]
        assert result["trigger_map"]["/candle"] == str(skill_file)

    def test_invalid_skill_md_handling(self, tmp_path):
        """Test graceful handling of malformed or missing SKILL.md."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        (skills_dir / "orphan_skill").mkdir()
        (skills_dir / "broken_skill").mkdir()
        (skills_dir / "broken_skill" / "SKILL.md").write_text("Just plain text, no frontmatter")
        (skills_dir / "empty_skill").mkdir()
        (skills_dir / "empty_skill" / "SKILL.md").write_text("---\n---\n")

        result = discover_skills(skills_dir)
        assert result["total_skills"] == 0
        assert result["skills"] == []

    def test_skill_description_parsing(self, tmp_path):
        """Test that description field is correctly extracted."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        description = "Rosary prayer beads"
        (skills_dir / "rosary").mkdir()
        (skills_dir / "rosary" / "SKILL.md").write_text(f"---\nname: Rosary\ndescription: {description}\ntriggers: [/rosary]\n---\n")

        result = discover_skills(skills_dir)
        assert result["total_skills"] == 1
        assert result["skills"][0]["description"] == description


class TestSkillDiscoveryIntegration:
    """Integration tests for skill discovery."""

    def test_discover_skills_returns_dict_with_keys(self, tmp_path):
        """Basic contract: result must have 'skills' and 'trigger_map'."""
        empty_result = discover_skills(tmp_path / "nonexistent")
        assert "skills" in empty_result
        assert "trigger_map" in empty_result

    def test_host_precedence_homonymous_override(self, tmp_path):
        """Test that skills in host_skills_dir override homonymous skills in skills_dir."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "my-skill").mkdir()
        (bundle_dir / "my-skill" / "SKILL.md").write_text(
            "---\nname: Bundle Skill\ntriggers: [/bundle]\n---\n"
        )

        host_dir = tmp_path / "host"
        host_dir.mkdir()
        (host_dir / "my-skill").mkdir()
        (host_dir / "my-skill" / "SKILL.md").write_text(
            "---\nname: Host Skill\ntriggers: [/host]\n---\n"
        )

        result = discover_skills(skills_dir=bundle_dir, host_skills_dir=host_dir)

        # There should only be 1 skill (total), and it must be the host's version
        assert result["total_skills"] == 1
        assert len(result["skills"]) == 1
        skill = result["skills"][0]
        assert skill["name"] == "Host Skill"
        assert skill["triggers"] == ["/host"]
        # Trigger map should map the host trigger to the host file path
        assert result["trigger_map"] == {"/host": str(host_dir / "my-skill" / "SKILL.md")}

    def test_bundle_fallback_when_host_missing(self, tmp_path):
        """Test that bundle skills act as fallbacks if host does not define them."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "fallback-skill").mkdir()
        (bundle_dir / "fallback-skill" / "SKILL.md").write_text(
            "---\nname: Fallback Skill\ntriggers: [/fallback]\n---\n"
        )

        host_dir = tmp_path / "host"
        host_dir.mkdir()
        # No fallback-skill folder in host_dir

        result = discover_skills(skills_dir=bundle_dir, host_skills_dir=host_dir)

        assert result["total_skills"] == 1
        assert result["skills"][0]["name"] == "Fallback Skill"
        assert result["trigger_map"] == {"/fallback": str(bundle_dir / "fallback-skill" / "SKILL.md")}

    def test_host_precedence_different_folder_same_trigger(self, tmp_path):
        """Test that host skills override trigger mappings even if folder names differ."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "foo-bundle").mkdir()
        (bundle_dir / "foo-bundle" / "SKILL.md").write_text(
            "---\nname: Bundle Skill\ntriggers: [/my-trigger]\n---\n"
        )

        host_dir = tmp_path / "host"
        host_dir.mkdir()
        (host_dir / "bar-host").mkdir()
        (host_dir / "bar-host" / "SKILL.md").write_text(
            "---\nname: Host Skill\ntriggers: [/my-trigger]\n---\n"
        )

        result = discover_skills(skills_dir=bundle_dir, host_skills_dir=host_dir)

        # There should only be 1 skill (total), and it must be the host's version
        assert result["total_skills"] == 1
        assert len(result["skills"]) == 1
        skill = result["skills"][0]
        assert skill["name"] == "Host Skill"
        assert skill["triggers"] == ["/my-trigger"]
        # Trigger map should map to the host's skill file path
        assert result["trigger_map"] == {"/my-trigger": str(host_dir / "bar-host" / "SKILL.md")}
