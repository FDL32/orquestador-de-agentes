"""
Tests for scripts/discover_skills.py --check-contract

Covers: bidirectional prompt<->skill contract validation.

[NON-REVERSE-CLASSICAL: test de contrato nuevo, no bug fix]
"""

from pathlib import Path
from typing import Any

import pytest
from scripts.discover_skills import (
    _check_contract,
    _deployed_stub_names,
    _derive_cycle_phase,
    _derive_disable_model_invocation,
    _get_bundle_root,
    _resolve_skill_path,
    check_skill_stubs_stale,
    discover_skills,
    extract_frontmatter,
    generate_skill_stubs,
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

    def test_orchestrator_contract_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEC-router-skills-001 D-S2: role: orchestrator opts into the contract
        (enforced), closing the gap where the 3 orchestrate-* skills escaped
        --check-contract under role: shared despite declaring source_prompt/
        contract_id."""
        bundle = tmp_path / "motor"
        (bundle / "skills" / "orch-x").mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "skills" / "orch-x" / "SKILL.md").write_text(
            "---\nname: orch-x\nrole: orchestrator\nsource_prompt: prompts/orch.md\n"
            "contract_id: cid-orch-v1\n---\n"
        )
        (bundle / "prompts" / "orch.md").write_text(
            "# Orch\nSkill canonica: skills/orch-x/SKILL.md\ncontract_id: cid-orch-v1\n"
        )
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _check_contract() == 0

    def test_orchestrator_contract_enforced_not_silently_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-false-green guarantee for D-S2: an orchestrator skill with a
        broken contract_id must FAIL, proving orchestrator is genuinely in the
        opt-in and not silently skipped like role: shared."""
        bundle = tmp_path / "motor"
        (bundle / "skills" / "orch-x").mkdir(parents=True)
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "skills" / "orch-x" / "SKILL.md").write_text(
            "---\nname: orch-x\nrole: orchestrator\nsource_prompt: prompts/orch.md\n"
            "contract_id: cid-orch-v1\n---\n"
        )
        (bundle / "prompts" / "orch.md").write_text(
            "# Orch\nSkill canonica: skills/orch-x/SKILL.md\ncontract_id: cid-WRONG\n"
        )
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _check_contract() == 1


class TestCheckContractIntegration:
    """Integration tests using the real bundle root."""

    def test_real_bundle_contract_passes(self) -> None:
        """Verify that the real motor bundle passes --check-contract."""
        rc = _check_contract()
        assert rc == 0, "Real motor bundle should pass contract check"

    def test_manager_review_binding_after_rename(self) -> None:
        """WOT-2026-008e/008i: manager-review-implementation binds to
        manager_review.md and the canonical prompt keeps the anchor + contract_id
        literals in its body (contract-check searches by substring/regex
        MULTILINE). The skill dir is manager-* since the 008i rename."""
        bundle = _get_bundle_root()
        skill = bundle / "skills" / "manager-review-implementation" / "SKILL.md"
        assert "source_prompt: prompts/manager_review.md" in skill.read_text(
            encoding="utf-8"
        )
        canonical = (bundle / "prompts" / "manager_review.md").read_text(
            encoding="utf-8"
        )
        # Literals must live in the BODY (not migrated into the YAML block).
        assert (
            "Skill canonica: skills/manager-review-implementation/SKILL.md" in canonical
        )
        assert "contract_id: cid-man-review-v2" in canonical
        # And the legacy stub still resolves (frontmatter declares the alias).
        fm, _ = parse_frontmatter(bundle / "prompts" / "manager_review.md")
        assert fm.get("legacy_aliases") == ["review_manager"]


class TestDeriveCyclePhase:
    """DEC-router-skills-001 D-S1: a pointer-skill without its own cycle_phase
    inherits it from its source_prompt; one that declares its own uses that
    value; an autocontenida (no source_prompt) with no cycle_phase resolves to
    an empty tuple (no herencia posible)."""

    def test_pointer_skill_inherits_from_source_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "prompts" / "p.md").write_text(
            "---\nrole: manager\ncycle_phase: [F6-revision]\nroute_kind: entry\n---\n# P\n"
        )
        fm = {"source_prompt": "prompts/p.md"}
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _derive_cycle_phase(fm, bundle) == ("F6-revision",)

    def test_skill_with_own_cycle_phase_overrides_inheritance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "prompts" / "p.md").write_text(
            "---\nrole: manager\ncycle_phase: [F6-revision]\nroute_kind: entry\n---\n# P\n"
        )
        fm = {"source_prompt": "prompts/p.md", "cycle_phase": ["F7-cierre-sesion"]}
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _derive_cycle_phase(fm, bundle) == ("F7-cierre-sesion",)

    def test_autocontenida_without_source_prompt_uses_own_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        fm = {"cycle_phase": ["F5-implementacion"]}
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _derive_cycle_phase(fm, bundle) == ("F5-implementacion",)

    def test_no_source_prompt_and_no_own_value_resolves_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "motor"
        fm: dict[str, Any] = {}
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _derive_cycle_phase(fm, bundle) == ()

    def test_source_prompt_missing_cycle_phase_resolves_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the prompt itself has no cycle_phase (e.g. route_kind: modulo,
        where it's forbidden), the skill inherits nothing rather than erroring."""
        bundle = tmp_path / "motor"
        (bundle / "prompts").mkdir(parents=True)
        (bundle / "prompts" / "p.md").write_text(
            "---\nrole: manager\nroute_kind: modulo\n---\n# P\n"
        )
        fm = {"source_prompt": "prompts/p.md"}
        monkeypatch.setattr("scripts.discover_skills._get_bundle_root", lambda: bundle)
        assert _derive_cycle_phase(fm, bundle) == ()

    def test_discover_exposes_cycle_phase_per_skill(self) -> None:
        """Integration: discover_skills() surfaces cycle_phase (possibly empty
        tuple) for every real skill, without raising."""
        result = discover_skills()
        assert result["skills"], "expected at least one discovered skill"
        for skill in result["skills"]:
            assert "cycle_phase" in skill
            assert isinstance(skill["cycle_phase"], tuple)

    def test_manager_review_implementation_inherits_f6(self) -> None:
        """manager-review-implementation has no own cycle_phase and its
        source_prompt (prompts/manager_review.md) is F6-revision."""
        result = discover_skills()
        skills_by_dir = {Path(s["path"]).name: s for s in result["skills"]}
        entry = skills_by_dir["manager-review-implementation"]
        assert entry["cycle_phase"] == ("F6-revision",)


class TestGenerateSkillStubs:
    """DEC-router-skills-001 D-S4: generate .claude/skills/<n>/SKILL.md stubs
    (name + description + a one-line pointer) for Claude Code's native skill
    listing, with a freshness gate guarding against stub/source drift."""

    def _setup_bundle(self, tmp_path: Path) -> Path:
        bundle = tmp_path / "motor"
        (bundle / "skills" / "my-skill").mkdir(parents=True)
        (bundle / "skills" / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Hace una cosa util.\n---\nBody\n"
        )
        return bundle

    def test_generates_stub_with_name_and_description(self, tmp_path: Path) -> None:
        bundle = self._setup_bundle(tmp_path)
        paths = generate_skill_stubs(bundle, names=["my-skill"])
        assert len(paths) == 1
        stub = bundle / ".claude" / "skills" / "my-skill" / "SKILL.md"
        assert stub in paths
        content = stub.read_text(encoding="utf-8")
        assert "name: my-skill" in content
        assert "description: Hace una cosa util." in content
        assert "skills/my-skill/SKILL.md" in content

    def test_names_filter_restricts_scope(self, tmp_path: Path) -> None:
        bundle = tmp_path / "motor"
        (bundle / "skills" / "a").mkdir(parents=True)
        (bundle / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: A.\n---\n"
        )
        (bundle / "skills" / "b").mkdir(parents=True)
        (bundle / "skills" / "b" / "SKILL.md").write_text(
            "---\nname: b\ndescription: B.\n---\n"
        )
        generate_skill_stubs(bundle, names=["a"])
        assert (bundle / ".claude" / "skills" / "a" / "SKILL.md").exists()
        assert not (bundle / ".claude" / "skills" / "b" / "SKILL.md").exists()

    def test_names_none_generates_all(self, tmp_path: Path) -> None:
        bundle = tmp_path / "motor"
        for n in ("a", "b", "c"):
            (bundle / "skills" / n).mkdir(parents=True)
            (bundle / "skills" / n / "SKILL.md").write_text(
                f"---\nname: {n}\ndescription: {n.upper()}.\n---\n"
            )
        paths = generate_skill_stubs(bundle, names=None)
        assert len(paths) == 3
        for n in ("a", "b", "c"):
            assert (bundle / ".claude" / "skills" / n / "SKILL.md").exists()

    def test_fresh_stub_is_not_stale(self, tmp_path: Path) -> None:
        bundle = self._setup_bundle(tmp_path)
        generate_skill_stubs(bundle, names=["my-skill"])
        is_stale, diag = check_skill_stubs_stale(bundle, names=["my-skill"])
        assert is_stale is False
        assert diag == ""

    def test_missing_stub_is_stale(self, tmp_path: Path) -> None:
        bundle = self._setup_bundle(tmp_path)
        is_stale, diag = check_skill_stubs_stale(bundle, names=["my-skill"])
        assert is_stale is True
        assert "my-skill" in diag

    def test_stub_desynced_description_is_stale(self, tmp_path: Path) -> None:
        """Mutation guard: editing the REAL SKILL.md after the stub was
        generated, without regenerating, must be caught as drift."""
        bundle = self._setup_bundle(tmp_path)
        generate_skill_stubs(bundle, names=["my-skill"])
        (bundle / "skills" / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Descripcion CAMBIADA.\n---\nBody\n"
        )
        is_stale, diag = check_skill_stubs_stale(bundle, names=["my-skill"])
        assert is_stale is True
        assert "my-skill" in diag

    def test_stub_regenerated_after_source_change_is_fresh_again(
        self, tmp_path: Path
    ) -> None:
        bundle = self._setup_bundle(tmp_path)
        generate_skill_stubs(bundle, names=["my-skill"])
        (bundle / "skills" / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Descripcion CAMBIADA.\n---\nBody\n"
        )
        generate_skill_stubs(bundle, names=["my-skill"])
        is_stale, _ = check_skill_stubs_stale(bundle, names=["my-skill"])
        assert is_stale is False

    def test_real_bundle_all_43_skills_generate_without_error(
        self, tmp_path: Path
    ) -> None:
        """Verifies the generator runs end-to-end over the real 43 skills
        (not just the 4-skill pilot subset) -- tramo 3 PASO 1 pieza 3:
        'verificalo en el worktree, no lo commitees sobre las 43'. Reads the
        REAL skills/ of this bundle but writes stubs into an isolated
        tmp_path via stub_root, so nothing lands in the real .claude/skills/.
        """
        bundle = _get_bundle_root()
        paths = generate_skill_stubs(bundle, names=None, stub_root=tmp_path)
        # D-S4 excepcion 2026-10-06: a skill named like a versioned command
        # (`session-hop`) gets no stub, so the full scope is 43 minus those.
        commands = bundle / ".claude" / "commands"
        skills = [
            p.name
            for p in (bundle / "skills").iterdir()
            if p.is_dir() and not p.name.startswith(("_", "."))
        ]
        expected = [n for n in skills if not (commands / f"{n}.md").exists()]
        assert len(skills) == 43
        assert len(paths) == len(expected)
        assert not (tmp_path / "session-hop").exists()
        for p in paths:
            assert p.exists()
            assert p.parent.parent == tmp_path

    def test_all_skills_scope_skips_a_name_taken_by_a_command(
        self, tmp_path: Path
    ) -> None:
        """Mutation for the D-S4 exception: the same skill gets a stub until a
        versioned command with its name appears; then --all-skills skips it."""
        for name in ("a", "b"):
            skill_dir = tmp_path / "skills" / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: d\n---\n", encoding="utf-8"
            )
        out = tmp_path / "out"
        assert len(generate_skill_stubs(tmp_path, names=None, stub_root=out)) == 2
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "b.md").write_text("x\n", encoding="utf-8")
        paths = generate_skill_stubs(tmp_path, names=None, stub_root=tmp_path / "o2")
        assert [p.parent.name for p in paths] == ["a"]


class TestDeployedStubNames:
    """CLI wiring for --check-index: watches only what is deployed, never
    demands all 43 before the batch rollout (separate tramo)."""

    def test_empty_when_no_stub_dir(self, tmp_path: Path) -> None:
        assert _deployed_stub_names(tmp_path) == []

    def test_lists_only_dirs_with_a_skill_md(self, tmp_path: Path) -> None:
        stub_dir = tmp_path / ".claude" / "skills"
        (stub_dir / "a").mkdir(parents=True)
        (stub_dir / "a" / "SKILL.md").write_text("---\nname: a\n---\n")
        (stub_dir / "b-empty").mkdir(parents=True)  # no SKILL.md inside
        assert _deployed_stub_names(tmp_path) == ["a"]

    def test_real_bundle_deployed_stubs_pass_check_index_scope(self) -> None:
        """Integration: whatever is deployed today in THIS bundle's real
        .claude/skills/ (the 4-skill pilot) must be internally consistent
        (fresh), proving the --check-index wiring would pass as-is."""
        bundle = _get_bundle_root()
        deployed = _deployed_stub_names(bundle)
        assert deployed, "expected the pilot's stubs to be deployed already"
        is_stale, diag = check_skill_stubs_stale(bundle, names=deployed)
        assert is_stale is False, diag


class TestGenerateSkillStubsCliScope:
    """Regression guard: --generate-skill-stubs must NEVER default to all 43
    (that is the batch-rollout tramo, opt-in only via --all-skills). This was
    a real bug caught during the pilot: the first CLI wiring defaulted to
    names=None (= all 43) and generated 39 stubs beyond the pilot's 4,
    requiring a manual cleanup before this guard was written."""

    def test_default_scope_never_exceeds_deployed_names(self) -> None:
        import subprocess
        import sys as _sys

        bundle = _get_bundle_root()
        before = set(_deployed_stub_names(bundle))
        result = subprocess.run(
            [_sys.executable, "scripts/discover_skills.py", "--generate-skill-stubs"],
            cwd=bundle,
            capture_output=True,
            text=True,
            timeout=60,
        )
        after = set(_deployed_stub_names(bundle))
        assert result.returncode == 0, result.stderr
        assert after == before, (
            "generating without --all-skills must not create stubs beyond "
            f"what was already deployed; before={sorted(before)} "
            f"after={sorted(after)}"
        )


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
