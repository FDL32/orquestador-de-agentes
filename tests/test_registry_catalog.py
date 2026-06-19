"""Tests for the derived catalog + generated INDEX projection — WOT-2026-008c.

Authority stays in frontmatter + live layout (DEC-008B-001): there is NO
registry.json. These tests verify that the catalog is derived from live
sources, that status has real dispatch effect, and that the INDEX stale gate
blocks divergence.
"""

from __future__ import annotations

from pathlib import Path

from scripts.discover_skills import (
    DEFAULT_STATUS,
    VALID_STATUS,
    _derive_owner,
    _derive_role,
    _derive_status,
    build_catalog,
    check_index_stale,
    discover_skills,
    generate_index,
    render_index,
)


NL_ = chr(10)


def _make_skill(
    skills_dir: Path,
    name: str,
    *,
    triggers: str,
    status: str | None = None,
    author: str | None = None,
) -> None:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    fm = [f"name: {name}", f"triggers: [{triggers}]"]
    if status is not None:
        fm.append(f"status: {status}")
    if author is not None:
        fm.append(f"author: {author}")
    body = "---\n" + "\n".join(fm) + "\n---\nbody\n"
    (d / "SKILL.md").write_text(body, encoding="utf-8")


class TestDerivedMetadata:
    """status/owner derived from frontmatter, never invented."""

    def test_status_defaults_active(self):
        assert _derive_status({}) == "active"
        assert _derive_status({"status": "active"}) == "active"

    def test_status_supports_lifecycle(self):
        assert _derive_status({"status": "deprecated"}) == "deprecated"
        assert _derive_status({"status": "draft"}) == "draft"

    def test_status_unknown_falls_back_active(self):
        # A typo must never silently hide a skill.
        assert _derive_status({"status": "retired"}) == "active"
        assert _derive_status({"status": ""}) == "active"

    def test_valid_status_contract(self):
        assert VALID_STATUS == ("active", "deprecated", "draft")
        assert DEFAULT_STATUS == "active"

    def test_owner_derivation_order(self):
        assert _derive_owner({"author": "agent", "role": "manager"}) == "agent"
        assert _derive_owner({"role": "builder"}) == "builder"
        assert _derive_owner({}) == "system"

    def test_role_is_separate_from_owner(self):
        # WOT-2026-008k: role comes from frontmatter `role`, default shared, and
        # is independent of owner (which prefers author).
        fm = {"author": "agent", "role": "auditor"}
        assert _derive_role(fm) == "auditor"
        assert _derive_owner(fm) == "agent"  # owner unchanged, coexists with role
        assert _derive_role({}) == "shared"
        assert _derive_role({"role": "builder"}) == "builder"


class TestStatusDispatchEffect:
    """deprecated/draft skills stay in the catalog but do not bind triggers."""

    def test_active_dispatches_draft_deprecated_do_not(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        _make_skill(skills, "alpha", triggers="/alpha", status="active")
        _make_skill(skills, "beta", triggers="/beta", status="draft")
        _make_skill(skills, "gamma", triggers="/gamma", status="deprecated")
        _make_skill(skills, "delta", triggers="/delta")  # no status -> active

        res = discover_skills(skills_dir=skills, host_skills_dir=tmp_path / "nohost")

        # All four remain visible in the catalog.
        assert res["total_skills"] == 4
        # Only active (and default-active) bind triggers.
        assert "/alpha" in res["trigger_map"]
        assert "/delta" in res["trigger_map"]
        assert "/beta" not in res["trigger_map"]
        assert "/gamma" not in res["trigger_map"]

    def test_aliases_equal_triggers(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        _make_skill(skills, "alpha", triggers="/alpha, alpha-alt", status="active")
        res = discover_skills(skills_dir=skills, host_skills_dir=tmp_path / "nohost")
        alpha = next(s for s in res["skills"] if s["name"] == "alpha")
        assert alpha["aliases"] == alpha["triggers"]
        assert "/alpha" in alpha["aliases"]


class TestCatalog:
    """build_catalog covers all kinds and stays parity with discovery."""

    def test_catalog_covers_live_kinds(self):
        catalog = build_catalog()
        kinds = {e["kind"] for e in catalog["entries"]}
        # Real motor must have at least skills, prompts, references, shared, consumers.
        assert {"skill", "prompt", "reference", "shared", "script-consumer"} <= kinds

    def test_catalog_entries_have_required_fields(self):
        catalog = build_catalog()
        required = {
            "kind",
            "path",
            "status",
            "owner",
            "role",
            "canonical_source",
            "aliases",
            "invocation",
        }
        for e in catalog["entries"]:
            assert required <= set(e.keys()), f"missing fields in {e}"
            # 008c does no renames: canonical_source == path.
            assert e["canonical_source"] == e["path"]
            # WOT-2026-008c: invocation reflects the hybrid taxonomy (010s).
            assert e["invocation"] in ("user-invoked", "model-invoked")
            # WOT-2026-008k: role is always a non-empty string (default shared).
            assert isinstance(e["role"], str) and e["role"]

    def test_catalog_role_parity_with_discovery(self):
        """WOT-2026-008k: a skill's catalog role must match the frontmatter role
        from discovery, exposed separately from owner."""
        catalog = build_catalog()
        disc = {s["path"]: s.get("role") for s in discover_skills()["skills"]}
        for e in catalog["entries"]:
            if e["kind"] != "skill":
                continue
            skill_dir = e["path"].rsplit("/SKILL.md", 1)[0]
            matching = [
                v for k, v in disc.items() if k.replace("\\", "/").endswith(skill_dir)
            ]
            if matching:
                assert e["role"] == matching[0]

    def test_audit_skills_are_role_auditor(self):
        """WOT-2026-008k: the five audit skills own role auditor; builder-self-audit
        stays builder (owned by the builder for self-audit, not the auditor)."""
        catalog = build_catalog()
        by_path = {e["path"].replace("\\", "/"): e for e in catalog["entries"]}
        for name in (
            "audit-git-publication",
            "audit-pipeline",
            "system-health-audit",
            "code-audit",
            "local-audit",
        ):
            entry = by_path[f"skills/{name}/SKILL.md"]
            assert entry["role"] == "auditor", f"{name} should be role auditor"
        assert by_path["skills/builder-self-audit/SKILL.md"]["role"] == "builder"

    def test_catalog_invocation_parity_with_discovery(self):
        """WOT-2026-008c: a skill's catalog invocation must match its
        disable_model_invocation flag from discovery (010s metadata)."""
        catalog = build_catalog()
        disc = {
            s["path"]: s.get("disable_model_invocation", False)
            for s in discover_skills()["skills"]
        }
        for e in catalog["entries"]:
            if e["kind"] != "skill":
                continue
            skill_dir = e["path"].rsplit("/SKILL.md", 1)[0]
            matching = [
                v for k, v in disc.items() if k.replace("\\", "/").endswith(skill_dir)
            ]
            if matching:
                expected = "user-invoked" if matching[0] else "model-invoked"
                assert e["invocation"] == expected

    def test_catalog_skill_status_parity_with_discovery(self):
        """Catalog skill status must match what discover_skills derives."""
        catalog = build_catalog()
        disc = {s["path"]: s["status"] for s in discover_skills()["skills"]}
        for e in catalog["entries"]:
            if e["kind"] != "skill":
                continue
            # catalog path is the SKILL.md file; discovery path is the dir.
            skill_dir = e["path"].rsplit("/SKILL.md", 1)[0]
            matching = [
                v for k, v in disc.items() if k.replace("\\", "/").endswith(skill_dir)
            ]
            if matching:
                assert e["status"] == matching[0]


class TestIndexStaleGate:
    """INDEX.md is a generated projection; the gate blocks divergence."""

    def test_generate_then_in_sync(self, tmp_path):
        root = _seed_minimal_motor(tmp_path)
        generate_index(root)
        is_stale, diag = check_index_stale(root)
        assert is_stale is False, diag

    def test_missing_index_is_stale(self, tmp_path):
        root = _seed_minimal_motor(tmp_path)
        is_stale, diag = check_index_stale(root)
        assert is_stale is True
        assert "does not exist" in diag

    def test_divergent_index_is_stale(self, tmp_path):
        root = _seed_minimal_motor(tmp_path)
        index = generate_index(root)
        index.write_text(
            index.read_text(encoding="utf-8") + "\nstale\n", encoding="utf-8"
        )
        is_stale, diag = check_index_stale(root)
        assert is_stale is True
        assert "stale" in diag.lower()

    def test_index_has_autogen_marker(self, tmp_path):
        root = _seed_minimal_motor(tmp_path)
        index = generate_index(root)
        first_line = index.read_text(encoding="utf-8").splitlines()[0]
        assert "AUTOGENERATED" in first_line

    def test_render_is_deterministic(self):
        catalog = build_catalog()
        assert render_index(catalog) == render_index(catalog)


class TestPromptLifecycle011d:
    """WOT-2026-011d: prompt status is derived from a real source in the file
    (frontmatter `status:`), not assumed active by layout. Regression: a stub
    declaring `status: deprecated` must NOT publish as active."""

    def _seed_prompts(self, tmp_path: Path) -> Path:
        (tmp_path / "skills" / "alpha").mkdir(parents=True)
        _make_skill(tmp_path / "skills", "alpha", triggers="/alpha", status="active")
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        # Plain prompt: no frontmatter -> active (backward compatible).
        (prompts / "canonical_one.md").write_text(
            "# Canonical Prompt" + NL_, encoding="utf-8"
        )
        # Deprecated stub: frontmatter status -> deprecated.
        (prompts / "legacy_stub.md").write_text(
            "---"
            + NL_
            + "status: deprecated"
            + NL_
            + "---"
            + NL_
            + "# Legacy alias"
            + NL_,
            encoding="utf-8",
        )
        return tmp_path

    def test_deprecated_prompt_not_active(self, tmp_path):
        root = self._seed_prompts(tmp_path)
        catalog = build_catalog(root)
        by_path = {e["path"]: e for e in catalog["entries"] if e["kind"] == "prompt"}
        assert by_path["prompts/legacy_stub.md"]["status"] == "deprecated"

    def test_plain_prompt_defaults_active(self, tmp_path):
        root = self._seed_prompts(tmp_path)
        catalog = build_catalog(root)
        by_path = {e["path"]: e for e in catalog["entries"] if e["kind"] == "prompt"}
        # Backward compatibility: a prompt without frontmatter stays active.
        assert by_path["prompts/canonical_one.md"]["status"] == "active"

    def test_lifecycle_uses_only_supported_vocabulary(self, tmp_path):
        # A draft prompt is honored; an invalid value falls back to active so a
        # typo never hides a prompt. Taxonomy is not widened.
        prompts = tmp_path / "prompts"
        prompts.mkdir(parents=True)
        (tmp_path / "skills").mkdir()
        (prompts / "drafty.md").write_text(
            "---" + NL_ + "status: draft" + NL_ + "---" + NL_ + "# d" + NL_,
            encoding="utf-8",
        )
        (prompts / "typo.md").write_text(
            "---" + NL_ + "status: retired" + NL_ + "---" + NL_ + "# t" + NL_,
            encoding="utf-8",
        )
        catalog = build_catalog(tmp_path)
        by_path = {e["path"]: e for e in catalog["entries"] if e["kind"] == "prompt"}
        assert by_path["prompts/drafty.md"]["status"] == "draft"
        assert by_path["prompts/typo.md"]["status"] == "active"


def _seed_minimal_motor(tmp_path: Path) -> Path:
    """Create a minimal motor layout so catalog/index functions have inputs."""
    (tmp_path / "skills" / "alpha").mkdir(parents=True)
    _make_skill(tmp_path / "skills", "alpha", triggers="/alpha", status="active")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.md").write_text("# p\n", encoding="utf-8")
    (tmp_path / "skills" / "_shared").mkdir()
    (tmp_path / "skills" / "_shared" / "s.md").write_text("# s\n", encoding="utf-8")
    return tmp_path
