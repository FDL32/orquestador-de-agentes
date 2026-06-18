"""Tests for the naming convention gate — WOT-2026-008d / DEC-008D-001.

check_naming() validates prompts (snake_case) and skills (kebab-case) on the
live surface and fails closed on a new non-conforming name. Authority lives in
discover_skills.py; check_skill_collisions.py is untouched.

[NON-REVERSE-CLASSICAL: new convention gate, not a bug fix]
"""

from __future__ import annotations

from pathlib import Path

from scripts.discover_skills import (
    KNOWN_LEGACY_NAMES,
    _actor_order_violation,
    _check_naming,
    _declared_prompt_aliases,
    check_naming,
    parse_frontmatter,
)


def _seed(
    root: Path,
    *,
    prompts: list[str],
    skills: list[str],
    prompt_aliases: dict[str, list[str]] | None = None,
) -> Path:
    """Create an isolated motor-like tree with the given prompt/skill names.

    prompt_aliases maps a prompt stem to the legacy_aliases it declares in its
    YAML frontmatter (WOT-2026-008e). A canonical prompt declaring an alias
    makes --check-naming tolerate a stub whose stem is that alias.
    """
    prompt_aliases = prompt_aliases or {}
    pdir = root / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    for name in prompts:
        aliases = prompt_aliases.get(name)
        if aliases:
            alias_list = ", ".join(aliases)
            body = f"---\nlegacy_aliases: [{alias_list}]\n---\n# x\n"
        else:
            body = "# x\n"
        (pdir / f"{name}.md").write_text(body, encoding="utf-8")
    sdir = root / "skills"
    sdir.mkdir(parents=True, exist_ok=True)
    for name in skills:
        d = sdir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\nbody\n", encoding="utf-8")
    return root


class TestCheckNamingClean:
    def test_conforming_tree_has_no_violations(self, tmp_path):
        root = _seed(
            tmp_path,
            prompts=["launch_builder", "session_bootstrap", "audit_bus"],
            skills=[
                "bui-implement-from-plan",
                "manager-review-implementation",
                "graphify",
            ],
        )
        assert check_naming(root) == []

    def test_shared_dirs_and_non_md_skipped(self, tmp_path):
        root = _seed(tmp_path, prompts=["ok_name"], skills=["good-skill"])
        # _shared dir (underscore prefix) must be ignored, not flagged.
        (root / "skills" / "_shared").mkdir()
        (root / "skills" / "_shared" / "s.md").write_text("# s\n", encoding="utf-8")
        # A non-.md file in prompts/ is not a prompt.
        (root / "prompts" / "README.txt").write_text("x\n", encoding="utf-8")
        assert check_naming(root) == []


class TestCheckNamingFailClosed:
    def test_bad_skill_name_flagged(self, tmp_path):
        root = _seed(tmp_path, prompts=["ok"], skills=["Bad_Name"])
        violations = check_naming(root)
        assert len(violations) == 1
        assert "Bad_Name" in violations[0]
        assert "kebab-case" in violations[0]

    def test_bad_prompt_name_flagged(self, tmp_path):
        # CamelCase / hyphen in a prompt stem violates snake_case.
        root = _seed(tmp_path, prompts=["Launch-Builder"], skills=["good-skill"])
        violations = check_naming(root)
        assert len(violations) == 1
        assert "Launch-Builder" in violations[0]
        assert "snake_case" in violations[0]

    def test_multiple_violations_all_reported(self, tmp_path):
        root = _seed(
            tmp_path,
            prompts=["BadPrompt"],
            skills=["BadSkill", "another_bad"],
        )
        assert len(check_naming(root)) == 3


class TestActorFirstRule:
    """DEC-008D-001 central rule: actor precedes the pipeline action."""

    def test_action_actor_order_flagged(self):
        # review_manager (action_actor) violates; manager_review is the fix.
        assert _actor_order_violation("review_manager", "_") is not None
        assert _actor_order_violation("manager_review", "_") is None

    def test_new_actor_last_case_fails_closed(self):
        # A brand-new actor-last name (not legacy) must be detected.
        assert _actor_order_violation("review_builder", "_") is not None
        assert _actor_order_violation("audit-builder", "-") is not None

    def test_head_noun_not_flagged(self):
        # refactor-manager: manager is a head noun, no pipeline action present.
        # Must NOT flag (AP-16 over-matching guard).
        assert _actor_order_violation("refactor-manager", "-") is None

    def test_launch_builder_exception(self):
        # launch is not a pipeline action the actor performs -> clean.
        assert _actor_order_violation("launch_builder", "_") is None

    def test_short_form_actor_first_clean(self):
        assert _actor_order_violation("man-review-implementation", "-") is None
        assert _actor_order_violation("bui-implement-from-plan", "-") is None

    def test_new_invalid_actor_name_flagged_via_check_naming(self, tmp_path):
        # End-to-end: a non-legacy actor-last prompt is reported by check_naming.
        root = _seed(tmp_path, prompts=["approve_manager"], skills=["good-skill"])
        violations = check_naming(root)
        assert len(violations) == 1
        assert "actor-first" in violations[0]
        assert "approve_manager" in violations[0]


class TestDeclarativeLegacyAlias:
    """WOT-2026-008e: legacy stubs are tolerated via `legacy_aliases:` frontmatter
    on the canonical prompt, NOT via the hardcoded KNOWN_LEGACY_NAMES."""

    def test_known_legacy_names_is_empty(self):
        # 008e moved tolerance from hardcode to frontmatter; the set is now empty.
        assert frozenset() == KNOWN_LEGACY_NAMES

    def test_stub_tolerated_when_canonical_declares_alias(self, tmp_path):
        # manager_review.md declares legacy_aliases: [review_manager]; the stub
        # review_manager.md is then tolerated even though it violates actor-first.
        root = _seed(
            tmp_path,
            prompts=["manager_review", "review_manager"],
            skills=["good-skill"],
            prompt_aliases={"manager_review": ["review_manager"]},
        )
        assert check_naming(root) == []

    def test_stub_fails_without_declared_alias(self, tmp_path):
        """The barrier: the stub is tolerated ONLY because the alias is declared.

        Remove the declaration (canonical with no legacy_aliases) and the stub
        review_manager.md must be detected as an actor-first violation. This
        proves the gate enforces the DEC rule and the tolerance is a real,
        declared compatibility surface — not a silent pass.
        """
        # With declaration -> clean.
        root = _seed(
            tmp_path,
            prompts=["manager_review", "review_manager"],
            skills=["ok"],
            prompt_aliases={"manager_review": ["review_manager"]},
        )
        assert check_naming(root) == []
        # Without declaration -> the stub re-surfaces as a violation.
        root2 = _seed(
            tmp_path / "nodecl",
            prompts=["manager_review", "review_manager"],
            skills=["ok"],
        )
        violations = check_naming(root2)
        assert len(violations) == 1
        assert "review_manager" in violations[0]
        assert "actor-first" in violations[0]

    def test_parse_frontmatter_reads_real_legacy_aliases(self, tmp_path):
        """parse_frontmatter() (reused, not a new parser) extracts legacy_aliases
        from a canonical prompt's YAML frontmatter."""
        root = _seed(
            tmp_path,
            prompts=["manager_review"],
            skills=["ok"],
            prompt_aliases={"manager_review": ["review_manager"]},
        )
        fm, err = parse_frontmatter(root / "prompts" / "manager_review.md")
        assert err is None
        assert fm.get("legacy_aliases") == ["review_manager"]
        # And the collector surfaces it.
        assert "review_manager" in _declared_prompt_aliases(root / "prompts")


class TestCheckNamingCLI:
    def test_cli_returns_zero_on_real_tree(self, capsys):
        # The real motor tree must be clean (gate is green at baseline).
        rc = _check_naming()
        out = capsys.readouterr().out
        assert rc == 0
        assert "conform" in out

    def test_check_naming_missing_dirs_is_clean(self, tmp_path):
        # No prompts/ or skills/ at all => nothing to validate => clean.
        assert check_naming(tmp_path) == []


class TestNoLiveManSkillRefs008i:
    """WOT-2026-008i barrier: no live operational consumer may reference the old
    man-* skill dir names after the rename to manager-*. Mirrors the 008h prose
    barrier. History/memory/DEC/changelog/tests are tolerated."""

    def test_no_live_ref_to_legacy_man_skill_dirs(self):
        import re

        root = Path(__file__).resolve().parents[1]
        legacy = (
            "man-create-work-plan",
            "man-resolve-escalation",
            "man-review-implementation",
            "man-session-closeout",
        )
        pat = re.compile(
            r"\bman-(?:create-work-plan|resolve-escalation|"
            r"review-implementation|session-closeout)\b"
        )
        # Tolerated: history, runtime, memory, DEC, changelog, backups, tests.
        tolerated_parts = (
            "/sandbox/",
            "/_archive/",
            "/.git/",
            "/backups/",
            "/runtime/",
            "graphify-out",
            ".venv",
            "__pycache__",
            "/memory/",
            "CHANGELOG.md",
            "DEC-008B-002",
            "DEC-008D-001",
            "/tests/",
            "baseline_008i",
            "/.agent/context/",
        )
        offenders = []
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in (
                ".md",
                ".py",
                ".txt",
                ".json",
                ".toml",
            ):
                continue
            s = str(p).replace("\\", "/")
            if any(t in s for t in tolerated_parts):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if pat.search(line):
                    offenders.append(f"{s}:{i}: {line.strip()}")
        assert not offenders, "live man-* skill refs survive:\n" + "\n".join(offenders)
        assert legacy  # names documented for traceability
