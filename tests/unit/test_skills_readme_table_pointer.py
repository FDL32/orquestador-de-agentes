"""
DEC-router-skills-001 D-S6: skills/README.md no longer maintains a hand-kept
operational table (it drifted to 25/43 and a stale AP-01..AP-14 count). This
guards that the pointer to the generated router stays in place and that the
old-style markdown table does not silently creep back in.
"""

from pathlib import Path


README = Path(__file__).resolve().parent.parent.parent / "skills" / "README.md"


def test_points_to_generated_router() -> None:
    text = README.read_text(encoding="utf-8")
    assert "docs/registry/ROUTER.md" in text
    assert "D-S6" in text


def test_no_hand_kept_skill_table_rows() -> None:
    """Regression guard: the old table had rows like
    `| `grill-work-plan` | `manager` | `plan` | ...`. If someone pastes a new
    hand-kept table back in, this should go red."""
    text = README.read_text(encoding="utf-8")
    assert "| Skill | Role | Stage | writes_memory | quality_gate" not in text
