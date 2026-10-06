"""
DEC-router-skills-001 DoD: every DEPLOYED skill (one with a stub under
.claude/skills/) keeps the two invariants the batch rollout must not erode.

- Its `description` carries the guide phrases "Usar cuando" and "No usar para"
  (the ratchet: coverage may only grow as more skills get a stub).
- Its `cycle_phase` resolves (own declaration, or inherited from `source_prompt`),
  EXCEPT a pointer whose prompt is `mantenimiento`: that route_kind sits outside
  the cycle and its prompt carries no phase (DEC-router-prompts-001 D2/D4), so
  there is nothing to inherit and nothing honest to force (DEC-router-skills-001,
  enmienda 2026-10-06). The exemption is read from the prompt's REAL frontmatter.

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
    _resolve_skill_path,
    parse_frontmatter,
    read_prompt_parts,
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


def _phase_missing(fm: dict[str, Any], root: Path) -> bool:
    """True when a skill must resolve a `cycle_phase` and does not.

    Resolves exactly like production (`_derive_cycle_phase`, own phase wins). The
    only exemption is a pointer whose source prompt declares `route_kind:
    mantenimiento`; an unreadable or missing prompt is NOT exempt (fail closed).
    """
    if _derive_cycle_phase(fm, root):
        return False
    source = fm.get("source_prompt")
    if not isinstance(source, str) or not source:
        return True
    prompt_path = _resolve_skill_path(source, root)
    if prompt_path is None:
        return True
    return read_prompt_parts(prompt_path)[0].get("route_kind") != "mantenimiento"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_phase_rule_exempts_only_maintenance_pointers(tmp_path: Path) -> None:
    fm_prompt = "---\nrole: auditor\nroute_kind: {kind}\n---\n# P\n"
    _write(tmp_path / "prompts" / "m.md", fm_prompt.format(kind="mantenimiento"))
    _write(tmp_path / "prompts" / "e.md", fm_prompt.format(kind="entry"))
    assert _phase_missing({"source_prompt": "prompts/m.md"}, tmp_path) is False
    # Mutation: the same pointer shape aimed at an `entry` prompt with no phase -> red.
    assert _phase_missing({"source_prompt": "prompts/e.md"}, tmp_path) is True
    assert _phase_missing({}, tmp_path) is True  # autocontenida sin fase
    assert _phase_missing({"source_prompt": "prompts/ausente.md"}, tmp_path) is True
    own = {"source_prompt": "prompts/m.md", "cycle_phase": ["F7-cierre-sesion"]}
    assert _phase_missing(own, tmp_path) is False  # fase propia sigue permitida


@pytest.mark.parametrize("name,fm", _deployed_frontmatters())
def test_deployed_skill_cycle_phase_resolves(name: str, fm: dict[str, Any]) -> None:
    assert not _phase_missing(fm, ROOT), f"{name}: cycle_phase not resolvable"


def _duplicate_pointers(root: Path) -> list[tuple[str, str, str]]:
    """(prompt, first skill, second skill) for every prompt with 2+ pointer skills."""
    seen: dict[str, str] = {}
    dups = []
    for skill_dir in sorted(p for p in (root / "skills").iterdir() if p.is_dir()):
        fm, _error = parse_frontmatter(skill_dir / "SKILL.md")
        source = fm.get("source_prompt")
        if not source:
            continue
        if source in seen:
            dups.append((source, seen[source], skill_dir.name))
        seen.setdefault(source, skill_dir.name)
    return dups


def test_duplicate_pointer_checker_flags_two_skills_on_one_prompt(
    tmp_path: Path,
) -> None:
    skill = "---\nname: {n}\nsource_prompt: prompts/p.md\n---\n# {n}\n"
    _write(tmp_path / "skills" / "a" / "SKILL.md", skill.format(n="a"))
    assert _duplicate_pointers(tmp_path) == []
    _write(tmp_path / "skills" / "b" / "SKILL.md", skill.format(n="b"))
    assert _duplicate_pointers(tmp_path) == [("prompts/p.md", "a", "b")]


def test_each_prompt_has_at_most_one_pointer_skill() -> None:
    """D-S6: ROUTER.md shows ONE skill per prompt (`skill_pointer_for_prompt`
    picks the first by dir name), so a second pointer to the same prompt would
    vanish from the router without any error."""
    assert _duplicate_pointers(ROOT) == []


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
