"""Contract test: prompts carry routing metadata + a greppable summary header.

WOT-2026-022o defined the summary format (the canonical spec of the block):

    <!-- PROMPT-SUMMARY
    what: <one line: what this prompt is>
    when: <one line: when to use it>
    not: <one line: when NOT to use it / where to go instead>
    -->

placed right after the ``# Title``, so an agent navigating by grep finds the
right prompt without reading 200-1300 line files whole. 022o kept its allowlist
BOUNDED and asked for a successor ticket to widen it.

DEC-router-prompts-001 (Plan A, approved 2026-10-06) is that successor:

- Routing metadata lives in YAML frontmatter -- ``role`` (scalar),
  ``cycle_phase`` (set of phases) and ``route_kind`` (closed enum) -- and is
  validated by ``discover_skills.validate_route_metadata`` (T1-T4, T6).
- CONSCIOUS CHANGE vs 022o (T5): the summary window is the 12 lines AFTER the
  frontmatter, computed with the production cut ``read_prompt_parts``; 022o
  counted from the start of the file.
- Every ``modulo`` is cited at least once (T9, ``module_citations``).
- RATCHET (replaces 022o's ``test_allowlist_is_bounded``): ``ADOPTED`` only
  grows batch by batch (``PILOT_FLOOR`` is the floor); when it equals the
  universe the test becomes universal and both lists disappear.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.discover_skills import (
    EXTERNAL_ALLOWLIST,
    module_citations,
    prompt_summary,
    read_prompt_parts,
    validate_route_metadata,
)


ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"
REQUIRED_KEYS = ("what", "when", "not")

# Prompts adopted into the router (relative to prompts/). Only grows.
ADOPTED = (
    "audit_ticket_contract.md",
    "manager_review.md",
    "ensemble_loop.md",
    "_shared/loop_readiness.md",
    "orchestrator_pipeline.md",
    "doc_optimization.md",
    "audit_git_publication.md",
    "audit_post_change_system_health.md",
    "suite_optimization.md",
    "orchestrator_session_close_full_audit.md",
    "audit_pipeline.md",
    "audit_pipeline_codeonly.md",
    "audit_autonomous_ticket_batch.md",
    "backlog_admit.md",
    "backlog_triage.md",
    "escalate_to_motor.md",
    "session_hop.md",
    "orchestrator_pipeline_codeonly.md",
    "orchestrator_autonomous_ticket_batch.md",
    "orchestrator_destination_batch.md",
    "orchestrator_launch_builder.md",
)
# Floor of the ratchet: the pilot of DEC-router-prompts-001 (6 files, one per kind).
PILOT_FLOOR = frozenset(ADOPTED)
# 022o pilot not yet adopted: keeps its original guarantee (summary present).
SUMMARY_ONLY = ("orchestrator_session_bootstrap.md",)


def _universe() -> list[str]:
    """prompts/*.md + prompts/_shared/*.md as names relative to prompts/."""
    top = [p.name for p in sorted(PROMPTS_DIR.glob("*.md"))]
    shared = [
        f"_shared/{p.name}" for p in sorted((PROMPTS_DIR / "_shared").glob("*.md"))
    ]
    return top + shared


@pytest.mark.parametrize("name", ADOPTED)
def test_adopted_prompt_has_valid_routing_frontmatter(name: str) -> None:
    """T1-T4: frontmatter parses and its routing metadata is valid.

    Mutation (teeth): delete the frontmatter, set ``route_kind: entrada``, give a
    ``modulo`` a ``cycle_phase`` or turn ``role`` into a list -> this FAILS.
    """
    fm, error, _body, _offset = read_prompt_parts(PROMPTS_DIR / name)
    assert error is None, f"{name}: frontmatter error {error}"
    assert validate_route_metadata(name, fm) == []


@pytest.mark.parametrize("name", ADOPTED)
def test_adopted_prompt_has_summary_after_frontmatter(name: str) -> None:
    """T5: PROMPT-SUMMARY with what/when/not within 12 lines after the frontmatter."""
    _fm, _error, body, _offset = read_prompt_parts(PROMPTS_DIR / name)
    summary = prompt_summary(body)
    missing = [k for k in REQUIRED_KEYS if not summary.get(k)]
    assert not missing, f"{name}: PROMPT-SUMMARY missing {missing}"


@pytest.mark.parametrize("name", ADOPTED)
def test_adopted_module_is_cited(name: str) -> None:
    """T9: a ``modulo`` must be cited by prompts/, prompts/_shared/ or AGENTS.md."""
    path = PROMPTS_DIR / name
    fm, _error, _body, _offset = read_prompt_parts(path)
    if fm.get("route_kind") != "modulo":
        pytest.skip("not a modulo")
    assert module_citations(path, ROOT), f"{name}: modulo without any citation"


@pytest.mark.parametrize("name", SUMMARY_ONLY)
def test_summary_only_prompt_keeps_the_022o_block(name: str) -> None:
    """The 022o pilot keeps its summary until it is adopted with frontmatter."""
    _fm, _error, body, _offset = read_prompt_parts(PROMPTS_DIR / name)
    summary = prompt_summary(body)
    assert all(summary.get(k) for k in REQUIRED_KEYS), f"{name}: {summary}"


def test_ratchet_only_grows_and_stays_in_the_universe() -> None:
    """The adopted list is a superset of the pilot and points to real files."""
    universe = set(_universe())
    assert len(set(ADOPTED)) == len(ADOPTED), "duplicated entries in ADOPTED"
    assert set(ADOPTED) >= PILOT_FLOOR
    assert set(ADOPTED) <= universe, sorted(set(ADOPTED) - universe)
    assert not set(SUMMARY_ONLY) & set(ADOPTED)


def test_every_routed_file_is_listed_in_adopted() -> None:
    """A file that declares ``route_kind`` must be in ADOPTED (no silent adoption)."""
    declared = {
        name
        for name in _universe()
        if read_prompt_parts(PROMPTS_DIR / name)[0].get("route_kind")
    }
    assert declared <= set(ADOPTED), sorted(declared - set(ADOPTED))


def test_externo_files_carry_no_routing_frontmatter() -> None:
    """T6: the exempt external artifacts stay untouched (Hermes exports them whole)."""
    for name in EXTERNAL_ALLOWLIST:
        fm, _error, _body, _offset = read_prompt_parts(PROMPTS_DIR / name)
        assert "route_kind" not in fm, name
