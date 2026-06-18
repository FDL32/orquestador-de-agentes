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
    _check_naming,
    check_naming,
)


def _seed(root: Path, *, prompts: list[str], skills: list[str]) -> Path:
    """Create an isolated motor-like tree with the given prompt/skill names."""
    pdir = root / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    for name in prompts:
        (pdir / f"{name}.md").write_text("# x\n", encoding="utf-8")
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
            skills=["bui-implement-from-plan", "man-review-implementation", "graphify"],
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


class TestKnownLegacyException:
    def test_legacy_name_tolerated(self, tmp_path):
        # review_manager is declared legacy debt (DEC-008D-001, deferred to 008e).
        assert "review_manager" in KNOWN_LEGACY_NAMES
        root = _seed(tmp_path, prompts=["review_manager"], skills=["good-skill"])
        # Even though review_manager is technically snake_case-valid, this proves
        # the exception path does not crash and keeps the tree clean.
        assert check_naming(root) == []

    def test_legacy_skill_name_tolerated_even_if_nonconforming(self, tmp_path):
        # A genuinely non-conforming name in the legacy set must be tolerated.
        bad = next(iter(KNOWN_LEGACY_NAMES))
        root = _seed(tmp_path, prompts=["ok"], skills=[bad])
        assert check_naming(root) == []


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
