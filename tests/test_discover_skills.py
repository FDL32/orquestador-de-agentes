"""
Tests for scripts/discover_skills.py --check-contract

Covers: bidirectional prompt<->skill contract validation.

[NON-REVERSE-CLASSICAL: test de contrato nuevo, no bug fix]
"""

from pathlib import Path

import pytest
from scripts.discover_skills import (
    _check_contract,
    _resolve_skill_path,
    extract_frontmatter,
    parse_frontmatter,
)


class TestParseFrontmatter:
    """Tests for parse_frontmatter tri-state distinction."""

    def test_valid_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\nname: test\nrole: builder\n---\nBody")
        data, error = parse_frontmatter(f)
        assert error is None
        assert data["name"] == "test"
        assert data["role"] == "builder"

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("Just plain text")
        data, error = parse_frontmatter(f)
        assert error == "NO_FRONTMATTER"
        assert data == {}

    def test_empty_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\n---\nBody")
        data, error = parse_frontmatter(f)
        assert error == "NO_FRONTMATTER"
        assert data == {}

    def test_missing_closing_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\nname: test\nBody")
        data, error = parse_frontmatter(f)
        assert error == "NO_FRONTMATTER"
        assert data == {}

    def test_extract_frontmatter_backward_compat(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\nname: test\n---\nBody")
        data = extract_frontmatter(f)
        assert data["name"] == "test"

    def test_extract_frontmatter_empty_on_no_fm(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("No frontmatter")
        data = extract_frontmatter(f)
        assert data == {}

    def test_invalid_yaml_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\nname: test\ninvalid: [unclosed\n---\nBody")
        data, error = parse_frontmatter(f)
        assert error is not None
        assert "YAML_INVALIDO" in error
        assert data == {}


class TestResolveSkillPath:
    """Tests for _resolve_skill_path portability."""

    def test_relative_path_resolves(self, tmp_path: Path) -> None:
        bundle = tmp_path / "motor"
        prompt_file = bundle / "prompts" / "test.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("content")
        result = _resolve_skill_path("prompts/test.md", bundle)
        assert result == prompt_file.resolve()

    def test_absolute_path_fails(self, tmp_path: Path) -> None:
        bundle = tmp_path / "motor"
        bundle.mkdir()
        result = _resolve_skill_path(str(tmp_path / "outside" / "test.md"), bundle)
        assert result is None

    def test_path_outside_bundle_fails(self, tmp_path: Path) -> None:
        bundle = tmp_path / "motor"
        bundle.mkdir()
        result = _resolve_skill_path("../outside/test.md", bundle)
        assert result is None


class TestCheckContractInvalidYaml:
    """Tests for _check_contract with invalid YAML frontmatter."""

    def test_invalid_yaml_in_skill_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\ninvalid: [unclosed\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1


class TestCheckContract:
    """Tests for _check_contract validation."""

    def _setup_valid_contract(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        prompts_dir = bundle / "prompts"
        skills_dir.mkdir(parents=True)
        prompts_dir.mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/test.md\ncontract_id: cid-test-v1\n---\n"
        )

        prompt_file = prompts_dir / "test.md"
        prompt_file.write_text(
            "# Prompt\nSkill canonica: skills/my-skill/SKILL.md\ncontract_id: cid-test-v1\n"
        )

        return bundle, skill_file, prompt_file

    def test_valid_contract_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle, _, _ = self._setup_valid_contract(tmp_path)
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 0

    def test_missing_source_prompt_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Role skills that opt in via contract_id must also declare source_prompt:."""
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\ncontract_id: cid-test-v1\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_role_skill_without_contract_metadata_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legacy role skills remain out of scope until they opt into metadata."""
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)

        skill_dir = skills_dir / "legacy-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: legacy-skill\nrole: builder\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 0

    def test_source_prompt_without_contract_id_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skills with source_prompt: but missing contract_id should fail."""
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        prompts_dir = bundle / "prompts"
        skills_dir.mkdir(parents=True)
        prompts_dir.mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/test.md\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_missing_contract_id_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/test.md\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_nonexistent_prompt_path_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/nonexistent.md\ncontract_id: cid-test-v1\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_non_portable_path_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: /absolute/path/test.md\ncontract_id: cid-test-v1\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_missing_reverse_anchor_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        prompts_dir = bundle / "prompts"
        skills_dir.mkdir(parents=True)
        prompts_dir.mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/test.md\ncontract_id: cid-test-v1\n---\n"
        )

        prompt_file = prompts_dir / "test.md"
        prompt_file.write_text("# Prompt\ncontract_id: cid-test-v1\n")

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_contract_id_mismatch_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        prompts_dir = bundle / "prompts"
        skills_dir.mkdir(parents=True)
        prompts_dir.mkdir(parents=True)

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\nrole: builder\nsource_prompt: prompts/test.md\ncontract_id: cid-skill-v1\n---\n"
        )

        prompt_file = prompts_dir / "test.md"
        prompt_file.write_text(
            "# Prompt\nSkill canonica: skills/my-skill/SKILL.md\ncontract_id: cid-prompt-v1\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 1

    def test_skips_non_manager_builder_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        skills_dir.mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)

        skill_dir = skills_dir / "other-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: other-skill\nrole: researcher\n---\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 0

    def test_manager_contract_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        skills_dir = bundle / "skills"
        prompts_dir = bundle / "prompts"
        skills_dir.mkdir(parents=True)
        prompts_dir.mkdir(parents=True)

        skill_dir = skills_dir / "man-review"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: man-review\nrole: manager\nsource_prompt: prompts/manager.md\ncontract_id: cid-man-v1\n---\n"
        )

        (prompts_dir / "manager.md").write_text(
            "# Manager\nSkill canonica: skills/man-review/SKILL.md\ncontract_id: cid-man-v1\n"
        )

        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        rc = _check_contract()
        assert rc == 0


class TestCheckContractIntegration:
    """Integration tests using the real bundle root."""

    def test_real_bundle_contract_passes(self) -> None:
        """Verify that the real motor bundle passes --check-contract."""
        rc = _check_contract()
        assert rc == 0, "Real motor bundle should pass contract check"
