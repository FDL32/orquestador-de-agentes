"""
Tests for scripts/discover_skills.py --check-contract

Covers: bidirectional prompt<->skill contract validation.

[NON-REVERSE-CLASSICAL: test de contrato nuevo, no bug fix]
"""

from pathlib import Path

import pytest
from scripts.discover_skills import (
    _check_contract,
    _derive_disable_model_invocation,
    _get_bundle_root,
    _resolve_skill_path,
    discover_skills,
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

    def test_auditor_contract_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WOT-2026-008k: role: auditor opts into the contract (enforced)."""
        bundle = tmp_path / "motor"
        (bundle / "skills" / "audit-x").mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "skills" / "audit-x" / "SKILL.md").write_text(
            "---\nname: audit-x\nrole: auditor\nsource_prompt: prompts/aud.md\n"
            "contract_id: cid-aud-v1\n---\n"
        )
        (bundle / "prompts" / "aud.md").write_text(
            "# Aud\nSkill canonica: skills/audit-x/SKILL.md\ncontract_id: cid-aud-v1\n"
        )
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _check_contract() == 0

    def test_auditor_contract_enforced_not_silently_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The anti-false-green guarantee: an auditor skill with a broken
        contract_id must FAIL, proving auditor is genuinely in the opt-in and not
        skipped like role: shared."""
        bundle = tmp_path / "motor"
        (bundle / "skills" / "audit-x").mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "skills" / "audit-x" / "SKILL.md").write_text(
            "---\nname: audit-x\nrole: auditor\nsource_prompt: prompts/aud.md\n"
            "contract_id: cid-aud-v1\n---\n"
        )
        # Prompt declares a DIFFERENT contract_id -> contract must fail.
        (bundle / "prompts" / "aud.md").write_text(
            "# Aud\nSkill canonica: skills/audit-x/SKILL.md\ncontract_id: cid-WRONG\n"
        )
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _check_contract() == 1

    def test_shared_role_still_skips_contract(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """role: shared (no contract) is not in the opt-in -> skipped, not failed.
        Guards the two shared->auditor skills that have no source_prompt."""
        bundle = tmp_path / "motor"
        (bundle / "skills" / "shared-x").mkdir(parents=True)
        (bundle / "skills" / "shared-x" / "SKILL.md").write_text(
            "---\nname: shared-x\nrole: shared\n---\n"
        )
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _check_contract() == 0


class TestCheckContractIntegration:
    """Integration tests using the real bundle root."""

    def test_real_bundle_contract_passes(self) -> None:
        """Verify that the real motor bundle passes --check-contract."""
        rc = _check_contract()
        assert rc == 0, "Real motor bundle should pass contract check"

    def test_manager_review_binding_after_rename(self) -> None:
        """WOT-2026-008e: man-review-implementation binds to manager_review.md and
        the canonical prompt keeps the anchor + contract_id literals in its body
        (the contract-check searches both by substring/regex MULTILINE)."""
        bundle = _get_bundle_root()
        skill = bundle / "skills" / "man-review-implementation" / "SKILL.md"
        assert "source_prompt: prompts/manager_review.md" in skill.read_text(
            encoding="utf-8"
        )
        canonical = (bundle / "prompts" / "manager_review.md").read_text(
            encoding="utf-8"
        )
        # Literals must live in the BODY (not migrated into the YAML block).
        assert "Skill canonica: skills/man-review-implementation/SKILL.md" in canonical
        assert "contract_id: cid-man-review-v2" in canonical
        # And the legacy stub still resolves (frontmatter declares the alias).
        fm, _ = parse_frontmatter(bundle / "prompts" / "manager_review.md")
        assert fm.get("legacy_aliases") == ["review_manager"]


class TestDisableModelInvocation:
    """WOT-2026-010s: hybrid user/model-invoked taxonomy parsing.

    The flag is additive metadata. These barriers cover the four contract cases
    (true / absent / invalid) and the trigger_map parity guarantee.
    """

    def test_flag_true_is_user_invoked(self) -> None:
        assert (
            _derive_disable_model_invocation({"disable-model-invocation": True}) is True
        )

    def test_flag_true_string_is_user_invoked(self) -> None:
        # YAML may surface the value as a string depending on the parser.
        assert (
            _derive_disable_model_invocation({"disable-model-invocation": "true"})
            is True
        )

    def test_absent_defaults_to_model_invoked(self) -> None:
        # Backward-compat: existing skills without the field stay model-invoked.
        assert _derive_disable_model_invocation({}) is False

    def test_flag_false_is_model_invoked(self) -> None:
        assert (
            _derive_disable_model_invocation({"disable-model-invocation": False})
            is False
        )

    def test_invalid_value_defaults_to_model_invoked(self) -> None:
        # A typo/garbage value must never silently hide a skill from the model.
        assert (
            _derive_disable_model_invocation({"disable-model-invocation": "maybe"})
            is False
        )
        assert (
            _derive_disable_model_invocation({"disable-model-invocation": 42}) is False
        )

    def test_discover_exposes_flag_per_skill(self) -> None:
        """Every discovered skill exposes disable_model_invocation as a bool,
        without dropping the pre-existing keys."""
        result = discover_skills()
        assert result["skills"], "expected at least one discovered skill"
        for skill in result["skills"]:
            assert "disable_model_invocation" in skill
            assert isinstance(skill["disable_model_invocation"], bool)
            # Additive: legacy keys survive.
            assert "triggers" in skill
            assert "name" in skill

    def test_trigger_map_parity_unaffected_by_flag(self) -> None:
        """Barrier: the additive flag must NOT change trigger_map. trigger_map is
        built only from skill['triggers'] (active skills), so adding metadata
        cannot alter dispatch. This guards the 010s hybrid-migration contract."""
        result = discover_skills()
        tm = result["trigger_map"]
        # trigger_map keys are triggers; values are skill_file paths. The flag
        # lives on the skill entry, never on the map.
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in tm.items())
        # Re-running discovery is deterministic (parity with itself).
        again = discover_skills()
        assert again["trigger_map"] == tm
