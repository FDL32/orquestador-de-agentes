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
            skill_file.write_text(
                f"---\nname: {skill_name}\ntriggers: [/{skill_name}]\n---\n"
            )

        result = discover_skills(skills_dir)

        assert result["total_skills"] == 3
        assert len(result["skills"]) == 3
        names = {s["name"] for s in result["skills"]}
        assert names == {"incense", "candles", "rosary"}

    def test_skill_frontmatter_parsing(self):
        """Test extraction of YAML frontmatter from SKILL.md."""
        content = "---\nname: Test Skill\ntriggers: [/test, testing]\ndescription: A test skill\nversion: 1.2.3\n---\nBody text"
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
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
        (skills_dir / "skill_a" / "SKILL.md").write_text(
            "---\nname: Skill A\ntriggers: [/a, /unique]\n---"
        )
        (skills_dir / "skill_b").mkdir()
        (skills_dir / "skill_b" / "SKILL.md").write_text(
            "---\nname: Skill B\ntriggers: [/b]\n---"
        )

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
        skill_file.write_text(
            "---\nname: Candles\ntriggers: [/candle, /candles]\ndescription: Liturgical candles\n---"
        )

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
        (skills_dir / "broken_skill" / "SKILL.md").write_text(
            "Just plain text, no frontmatter"
        )
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
        (skills_dir / "rosary" / "SKILL.md").write_text(
            f"---\nname: Rosary\ndescription: {description}\ntriggers: [/rosary]\n---\n"
        )

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
        assert result["trigger_map"] == {
            "/host": str(host_dir / "my-skill" / "SKILL.md")
        }

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
        assert result["trigger_map"] == {
            "/fallback": str(bundle_dir / "fallback-skill" / "SKILL.md")
        }

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
        assert result["trigger_map"] == {
            "/my-trigger": str(host_dir / "bar-host" / "SKILL.md")
        }


class TestSkillResolverValidation:
    """Tests for WP-2026-128: SkillResolver validation."""

    def test_validate_allowlists_against_catalog_valid(self, tmp_path):
        """Test validation passes when allowlist references exist."""
        from bus.skill_resolver import SkillResolver

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test_skill").mkdir()
        (skills_dir / "test_skill" / "SKILL.md").write_text(
            "---\nname: Test Skill\ntriggers: [/test]\n---"
        )

        resolver = SkillResolver(
            project_root=tmp_path,
            role_allowlists={"BUILDER": ["/test", "test_skill"]},
        )
        # Override discover to use our temp skills_dir
        resolver._discovered_skills = {
            "test_skill": {"name": "Test Skill", "triggers": ["/test"]}
        }
        warnings = resolver.validate_allowlists_against_catalog()
        assert warnings == []

    def test_validate_allowlists_against_catalog_missing(self, tmp_path):
        """Test validation reports warnings for missing skill references."""
        from bus.skill_resolver import SkillResolver

        resolver = SkillResolver(
            project_root=tmp_path,
            role_allowlists={"BUILDER": ["/nonexistent", "missing_skill"]},
        )
        # Empty catalog
        resolver._discovered_skills = {}
        warnings = resolver.validate_allowlists_against_catalog()
        assert len(warnings) == 2
        assert "nonexistent" in warnings[0]
        assert "missing_skill" in warnings[1]


class TestEmptySkillCatalogError:
    """Tests for WP-2026-128: EmptySkillCatalogError."""

    def test_empty_skill_catalog_error_message(self, tmp_path):
        """Test EmptySkillCatalogError has informative message."""
        from bus.exceptions import EmptySkillCatalogError

        error = EmptySkillCatalogError(project_root=tmp_path)
        assert "Empty skill catalog" in str(error)
        assert str(tmp_path) in str(error)

    def test_empty_skill_catalog_error_with_skills_dir(self, tmp_path):
        """Test EmptySkillCatalogError includes skills_dir when provided."""
        from bus.exceptions import EmptySkillCatalogError

        skills_dir = tmp_path / "skills"
        error = EmptySkillCatalogError(project_root=tmp_path, skills_dir=skills_dir)
        assert "skills_dir" in str(error) or str(skills_dir) in str(error)

    def test_create_resolver_raises_on_empty_catalog(self, tmp_path, monkeypatch):
        """Test create_resolver raises EmptySkillCatalogError when no skills."""
        from bus.exceptions import EmptySkillCatalogError
        from bus.skill_resolver import SkillResolver

        # Mock discover_skills to return empty result
        def mock_discover_skills():
            return {
                "skills": [],
                "trigger_map": {},
                "total_skills": 0,
                "total_triggers": 0,
            }

        monkeypatch.setattr(
            "scripts.discover_skills.discover_skills", mock_discover_skills
        )

        # Direct test: SkillResolver._discover_skills should raise on empty catalog
        resolver = SkillResolver(project_root=tmp_path, role_allowlists={})

        # _discover_skills should raise when no skills found
        with pytest.raises(EmptySkillCatalogError):
            resolver._discover_skills()


class TestRevisorAllowlist:
    """Tests for WOT-2026-100g: REVISOR allowlist key in agents.json."""

    def test_revisor_allowlist_key_legible(self):
        """T6: The real agents.json bundle has REVISOR in skill_allowlists
        and the agents_config loader validation accepts it."""
        import json
        from pathlib import Path

        bundle_root = Path(__file__).resolve().parent.parent.parent
        agents_path = bundle_root / ".agent" / "config" / "agents.json"
        assert agents_path.exists(), (
            f"agents.json should exist in bundle at {agents_path}"
        )

        with open(agents_path, encoding="utf-8") as f:
            config = json.load(f)

        skill_allowlists = config.get("skill_allowlists", {})
        assert "REVISOR" in skill_allowlists, "REVISOR must be in skill_allowlists"
        assert isinstance(skill_allowlists["REVISOR"], list), (
            "REVISOR value must be a list"
        )
        assert len(skill_allowlists["REVISOR"]) > 0, "REVISOR list must not be empty"

        # Invocar el loader del bundle (no mock): su validacion pasa
        import sys as _sys

        _sys.path.insert(0, str(bundle_root / ".agent"))
        from agents_config import _validate_skill_allowlists

        _validate_skill_allowlists(config, agents_path)

    def test_revisor_skill_real_binding_fields_present(self):
        """T7: El bundle real de revisor tiene source_prompt + contract_id en
        el frontmatter, por lo que _validate_frontmatter_contract_opt_in NO
        lo descarta (skip silencioso :402 :403 ya no aplica)."""
        from pathlib import Path

        from scripts.discover_skills import _validate_frontmatter_contract_opt_in

        bundle_root = Path(__file__).resolve().parent.parent.parent
        skill_path = bundle_root / "skills" / "revisor-independent-review" / "SKILL.md"
        assert skill_path.exists(), (
            f"revisor SKILL.md real debe existir en {skill_path}"
        )

        fm, error = _validate_frontmatter_contract_opt_in(skill_path, bundle_root)

        assert error is None, f"La skill real no debe ser descartada; error: {error}"
        assert fm is not None, (
            "_validate_frontmatter_contract_opt_in debe devolver fm no-None"
        )
        assert fm.get("contract_id") == "cid-revisor-review-v1", (
            f"contract_id debe ser 'cid-revisor-review-v1', "
            f"got: {fm.get('contract_id')!r}"
        )
        assert fm.get("source_prompt") is not None and fm.get("source_prompt") != "", (
            "source_prompt debe estar presente"
        )
