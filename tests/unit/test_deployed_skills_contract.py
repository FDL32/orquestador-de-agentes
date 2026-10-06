"""
DEC-router-skills-001 DoD: every DEPLOYED skill (one with a stub under
.claude/skills/) keeps the two invariants the batch rollout must not erode.

- Its `description` carries the guide phrases "Usar cuando" and "No usar para"
  (the ratchet: coverage may only grow as more skills get a stub).
- Its `cycle_phase` resolves (own declaration, or inherited from `source_prompt`).

Neither invariant had an executable guard before the rollout: the stub
generator only scopes by deployment, it never inspects the description.
"""

import re
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from discover_skills import (  # noqa: E402
    _deployed_stub_names,
    _derive_cycle_phase,
    parse_frontmatter,
)


GUIDE_PHRASES = ("Usar cuando", "No usar para")


def _missing_phrases(description: str) -> list[str]:
    return [p for p in GUIDE_PHRASES if p not in description]


def _deployed_frontmatters() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for name in _deployed_stub_names(ROOT):
        fm, error = parse_frontmatter(ROOT / "skills" / name / "SKILL.md")
        assert not error, f"{name}: {error}"
        out.append((name, fm))
    return out


def test_helper_flags_a_description_without_the_guide_phrases() -> None:
    assert _missing_phrases("Hace algo.") == list(GUIDE_PHRASES)
    assert _missing_phrases("Hace algo. Usar cuando X.") == ["No usar para"]
    assert _missing_phrases("Hace algo. Usar cuando X. No usar para Y.") == []


def test_there_are_deployed_skills_to_check() -> None:
    assert _deployed_frontmatters(), "no deployed stubs: the guard would be vacuous"


@pytest.mark.parametrize("name,fm", _deployed_frontmatters())
def test_deployed_skill_description_has_guide_phrases(
    name: str, fm: dict[str, Any]
) -> None:
    assert _missing_phrases(str(fm.get("description", ""))) == [], name


@pytest.mark.parametrize("name,fm", _deployed_frontmatters())
def test_deployed_skill_cycle_phase_resolves(name: str, fm: dict[str, Any]) -> None:
    assert _derive_cycle_phase(fm, ROOT), f"{name}: cycle_phase not resolvable"


# "(ver X)" targets: a skill dir, a prompt, or a script. A dead cross-reference in a
# description rots silently (nobody opens it until the model follows it).
_SEE_RE = re.compile(r"\(ver ([^)]*)\)")


def _dead_see_references(description: str) -> list[str]:
    dead = []
    for group in _SEE_RE.findall(description):
        for token in re.split(r"\s+o\s+|,\s*", group):
            token = token.strip()
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", token):
                continue  # prose such as "(ver mas abajo)" is not a reference
            candidates = (
                ROOT / "skills" / token,
                ROOT / "prompts" / token,
                ROOT / "prompts" / f"{token}.md",
                ROOT / "scripts" / token,
            )
            if not any(c.exists() for c in candidates):
                dead.append(token)
    return dead


def test_see_reference_checker_flags_a_dead_target() -> None:
    assert _dead_see_references("X. No usar para Y (ver skill-que-no-existe).") == [
        "skill-que-no-existe"
    ]
    assert _dead_see_references("X. No usar para Y (ver systematic-debugging).") == []


@pytest.mark.parametrize("name,fm", _deployed_frontmatters())
def test_deployed_skill_see_references_resolve(name: str, fm: dict[str, Any]) -> None:
    assert _dead_see_references(str(fm.get("description", ""))) == [], name
