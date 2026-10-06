"""
DEC-router-skills-001 D-S5: .claude/agents/{manager,builder}.md must not
declare a `skills:` frontmatter field.

Context (tramo 2 probes, variante i): writing a unique marker at the end of
a real SKILL.md listed under `skills:` never surfaced in the subagent's own
transcript for the one case probed (manager-review-implementation + manager
agent) -- no precarga observada en ese caso. The decision to remove `skills:`
from both agents does not rest on generalizing that single probe to all 6
references; it rests on D-S4 (native stubs) making the field redundant as a
discovery mechanism regardless of what `skills:` itself does. There is no
behavioural test possible here (absence of a side effect already measured);
this is a FORM test, per tramo 3 PASO 1 pieza 4.
"""

from pathlib import Path

import yaml


AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "agents"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} has no frontmatter block"
    _, fm_text, _ = text.split("---", 2)
    return yaml.safe_load(fm_text) or {}


def test_manager_agent_declares_no_skills_field() -> None:
    fm = _frontmatter(AGENTS_DIR / "manager.md")
    assert "skills" not in fm


def test_builder_agent_declares_no_skills_field() -> None:
    fm = _frontmatter(AGENTS_DIR / "builder.md")
    assert "skills" not in fm
