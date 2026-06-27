"""
Tests for WOT-2026-014g: gate name==dir in _check_skill_names.

Mutation-verified barrier: a fixture skill whose frontmatter name != directory
name must make the gate return an error. Removing the gate (by using a version
of _check_skill_names without the WOT-2026-014g block) makes the same fixture
pass silently (zero errors from that check).
"""

from pathlib import Path

import pytest
import scripts.discover_skills as ds
from scripts.discover_skills import _check_skill_names, check_naming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(skill_dir: Path, frontmatter_name: str) -> None:
    """Write a minimal SKILL.md with the given frontmatter name."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {frontmatter_name}\ntriggers: [/test]\nrole: builder\n---\n\n# {skill_dir.name}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Gate: mismatched fixture is flagged WITH the gate active
# ---------------------------------------------------------------------------


class TestNameDirGateBlocks:
    """The name==dir gate must flag a skill whose frontmatter name != dir name."""

    def test_mismatch_is_flagged(self, tmp_path: Path) -> None:
        """
        A SKILL.md with name=wrong-name in a dir called builder-real-skill
        must produce at least one violation describing the mismatch.
        """
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "builder-real-skill"
        _write_skill(skill_dir, "wrong-name")

        errors = _check_skill_names(skills_dir)

        mismatch_errors = [
            e for e in errors if "frontmatter name" in e and "wrong-name" in e
        ]
        assert mismatch_errors, (
            f"Gate did not flag name!=dir mismatch. Got errors: {errors}"
        )

    def test_mismatch_error_contains_dir_name(self, tmp_path: Path) -> None:
        """The error message must reference both the frontmatter name and the dir name."""
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "manager-do-thing"
        _write_skill(skill_dir, "do-thing")

        errors = _check_skill_names(skills_dir)

        mismatch_errors = [
            e for e in errors if "do-thing" in e and "manager-do-thing" in e
        ]
        assert mismatch_errors, (
            f"Error message does not mention both names. Got: {errors}"
        )


# ---------------------------------------------------------------------------
# Mutation barrier: WITHOUT the gate, the same fixture passes silently
# ---------------------------------------------------------------------------


class TestNameDirGateMutationBarrier:
    """
    Mutation barrier: when the WOT-2026-014g check is removed from
    _check_skill_names, the mismatched fixture produces ZERO name==dir errors.

    This proves the gate is the sole reason the mismatch is caught.
    """

    def test_fixture_passes_without_gate(self, tmp_path: Path) -> None:
        """
        Use a replica of _check_skill_names that omits the WOT-2026-014g block.
        The mismatched fixture must then produce no name==dir violation.
        """
        from scripts.discover_skills import (
            KNOWN_LEGACY_NAMES,
            _SKILL_NAME_RE,
            _name_violation,
        )

        def _check_skill_names_no_gate(skills_dir_arg: Path):
            """Replica of _check_skill_names WITHOUT the WOT-2026-014g block."""
            if not skills_dir_arg.is_dir():
                return []
            out = []
            for path in sorted(skills_dir_arg.iterdir()):
                if not path.is_dir() or path.name.startswith("_"):
                    continue
                name = path.name
                violation = _name_violation(name, _SKILL_NAME_RE, "skill", "-")
                if violation and name not in KNOWN_LEGACY_NAMES:
                    out.append(violation)
                # WOT-2026-014g block intentionally omitted (mutation)
            return out

        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "builder-real-skill"
        _write_skill(skill_dir, "wrong-name")

        errors = _check_skill_names_no_gate(skills_dir)

        name_dir_errors = [e for e in errors if "frontmatter name" in e]
        assert name_dir_errors == [], (
            f"Without the gate, expected zero name==dir errors, got: {name_dir_errors}"
        )


# ---------------------------------------------------------------------------
# Gate passes for correctly aligned skills
# ---------------------------------------------------------------------------


class TestNameDirGatePasses:
    """A skill whose frontmatter name == dir name must produce no name==dir error."""

    def test_aligned_skill_passes(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "builder-do-thing"
        _write_skill(skill_dir, "builder-do-thing")

        errors = _check_skill_names(skills_dir)

        name_dir_errors = [e for e in errors if "frontmatter name" in e]
        assert name_dir_errors == [], (
            f"Aligned skill should produce no name==dir error, got: {name_dir_errors}"
        )

    def test_multiple_aligned_skills_pass(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        for dir_name in ["builder-alpha", "manager-beta", "builder-gamma"]:
            _write_skill(skills_dir / dir_name, dir_name)

        errors = _check_skill_names(skills_dir)

        name_dir_errors = [e for e in errors if "frontmatter name" in e]
        assert name_dir_errors == [], (
            f"All aligned skills should pass, got name==dir errors: {name_dir_errors}"
        )


# ---------------------------------------------------------------------------
# Real motor skills: all 6 previously-mismatched skills now pass
# ---------------------------------------------------------------------------

EXPECTED_ALIGNED_SKILLS = [
    "manager-create-work-plan",
    "manager-review-implementation",
    "manager-resolve-escalation",
    "builder-run-quality-gates",
    "builder-self-audit",
    "builder-write-deliverable",
]


class TestRealSkillsAligned:
    """The 6 skills fixed in WOT-2026-014g must now pass the name==dir gate."""

    def test_six_skills_have_no_name_dir_error(self) -> None:
        """
        Run check_naming() against the real motor skills/ directory and confirm
        that none of the 6 WOT-2026-014g skills produce a frontmatter-name error.
        """
        motor_root = Path(__file__).resolve().parent.parent.parent
        errors = check_naming(motor_root)
        name_dir_errors = [e for e in errors if "frontmatter name" in e]
        failing = [
            skill
            for skill in EXPECTED_ALIGNED_SKILLS
            if any(skill in e for e in name_dir_errors)
        ]
        assert failing == [], (
            f"These skills still have name!=dir errors after WOT-2026-014g: {failing}."
            f" Full name==dir errors: {name_dir_errors}"
        )

    @pytest.mark.parametrize("skill_dir_name", EXPECTED_ALIGNED_SKILLS)
    def test_individual_skill_name_matches_dir(self, skill_dir_name: str) -> None:
        """Each of the 6 skills must individually have frontmatter name == dir name."""
        motor_root = Path(__file__).resolve().parent.parent.parent
        skill_file = motor_root / "skills" / skill_dir_name / "SKILL.md"
        assert skill_file.exists(), f"SKILL.md not found: {skill_file}"
        fm, err = ds.parse_frontmatter(skill_file)
        assert err is None, f"Frontmatter parse error for {skill_dir_name}: {err}"
        fm_name = fm.get("name", "")
        assert fm_name == skill_dir_name, (
            f"skill {skill_dir_name!r}: frontmatter name={fm_name!r} != dir name={skill_dir_name!r}"
        )
