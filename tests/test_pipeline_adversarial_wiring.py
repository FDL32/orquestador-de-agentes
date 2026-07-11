# WOT-2026-021y: Contract test for adversarial cross-wiring in the pipeline prompts.
#
# Both orchestrator_pipeline.md (canonico, bus) and
# orchestrator_pipeline_codeonly.md (code-only, commit-directo) must reference
# the canonical adversarial-review method (manager_review.md) and the
# chain-close meta-audit method (audit_pipeline*.md) -- cross-reference, not
# reimplementation.
#
# The DoD warns EXPLICITLY that this test must NOT false-green by only checking
# the canonical pipeline.md (which already had the refs before 021y): the
# load-bearing assertion is that the CODE-ONLY variant carries them too. The
# isolation tests below force the state where the codeonly assertion is the ONLY
# thing that can fail (branch-isolation, leccion 021u): a test that passes purely
# on pipeline.md's pre-existing refs has no teeth for 021y.

from __future__ import annotations

from pathlib import Path

import pytest


PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
CANONICAL = PROMPTS / "orchestrator_pipeline.md"
CODEONLY = PROMPTS / "orchestrator_pipeline_codeonly.md"
BOOTSTRAP = PROMPTS / "orchestrator_session_bootstrap.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical pipeline.md: regression pin (these refs pre-date 021y; 021y is a
# NO-OP here). Kept so a future edit that strips them is caught.
# ---------------------------------------------------------------------------


def test_canonical_references_manager_review() -> None:
    assert "manager_review.md" in _read(CANONICAL), (
        "orchestrator_pipeline.md must reference manager_review.md for Review 1/2"
    )


def test_canonical_references_audit_pipeline() -> None:
    assert "audit_pipeline.md" in _read(CANONICAL), (
        "orchestrator_pipeline.md must reference audit_pipeline.md for chain close"
    )


# ---------------------------------------------------------------------------
# Code-only variant: THE load-bearing assertions of 021y. Before 021y the
# codeonly prompt had 0 refs to either. These are what the ticket delivers.
# ---------------------------------------------------------------------------


def test_codeonly_references_manager_review() -> None:
    """The code-only pipeline must cross-reference the Review method (021y)."""
    assert "manager_review.md" in _read(CODEONLY), (
        "orchestrator_pipeline_codeonly.md must reference manager_review.md "
        "for the intra-ticket Review 1/2 mechanic (021y wiring)"
    )


def test_codeonly_references_chain_audit_method() -> None:
    """The code-only pipeline must cross-reference its chain-close method (021y).

    The natural fit is the code-only variant audit_pipeline_codeonly.md (created
    by 021z); it inherits from the base audit_pipeline.md, so either token proves
    the chain-audit wiring is present.
    """
    text = _read(CODEONLY)
    assert "audit_pipeline_codeonly.md" in text or "audit_pipeline.md" in text, (
        "orchestrator_pipeline_codeonly.md must reference the chain-close "
        "meta-audit method (audit_pipeline_codeonly.md and/or its base "
        "audit_pipeline.md) (021y wiring)"
    )


def test_codeonly_references_codeonly_variant_specifically() -> None:
    """The code-only pipeline should point at the CODE-ONLY variant, not only the
    generic base -- the code-only close uses audit_pipeline_codeonly.md (021z).

    This is stronger than test_codeonly_references_chain_audit_method: it would
    NOT be satisfied by a stray mention of the generic base alone.
    """
    assert "audit_pipeline_codeonly.md" in _read(CODEONLY), (
        "orchestrator_pipeline_codeonly.md must reference the code-only variant "
        "audit_pipeline_codeonly.md for chain close (dogfood of 021z)"
    )


# ---------------------------------------------------------------------------
# Branch-isolation / anti-false-green (leccion 021u): prove the codeonly
# assertions are load-bearing and NOT a redundant restatement of the canonical
# refs. If a reader thinks "the canonical prompt already has the refs, so the
# codeonly check is redundant", these tests refute that: the two files are
# distinct, and the codeonly assertions must be able to fail independently.
# ---------------------------------------------------------------------------


def test_two_prompt_files_are_distinct() -> None:
    """Guard against a symlink/alias that would make canonical and codeonly the
    same content -- which would let pipeline.md's refs mask a missing codeonly."""
    assert CANONICAL != CODEONLY
    assert _read(CANONICAL) != _read(CODEONLY), (
        "canonical and code-only pipelines must be distinct files; if they were "
        "identical, the codeonly refs would false-green off pipeline.md"
    )


def test_referenced_prompt_files_exist() -> None:
    """No dangling reference: every prompt the codeonly cross-references exists
    on disk (seam guard -- 021y depends on 021z having created the variant)."""
    for name in (
        "manager_review.md",
        "audit_pipeline.md",
        "audit_pipeline_codeonly.md",
    ):
        assert (PROMPTS / name).is_file(), f"referenced prompt {name} does not exist"


@pytest.mark.parametrize("token", ["manager_review.md", "audit_pipeline_codeonly.md"])
def test_codeonly_ref_survives_removal_of_canonical(token: str, tmp_path: Path) -> None:
    """Isolation: a checker that scanned ONLY the canonical pipeline.md would
    still pass its own refs -- but that says NOTHING about the codeonly. This
    asserts the codeonly file itself carries `token`, independent of the
    canonical file. Mutation: strip `token` from CODEONLY -> this fails; strip it
    from CANONICAL -> this still passes (proving it reads the codeonly, not the
    canonical)."""
    codeonly_text = _read(CODEONLY)
    # Simulate "canonical loses the ref" by NOT reading canonical at all here.
    assert token in codeonly_text, (
        f"code-only pipeline must independently reference {token}; the canonical "
        f"pipeline's refs must not be what makes this pass"
    )


# ---------------------------------------------------------------------------
# WOT-2026-022d: wire init_session_scratch.py (022c) into both pipelines and
# make the bootstrap read from the session scratch before falling back to
# C:\tmp. Before 022d neither pipeline referenced the script at all (0 refs).
# ---------------------------------------------------------------------------


def test_codeonly_references_init_session_scratch() -> None:
    """The code-only pipeline must invoke init_session_scratch.py (022d wiring).

    LOAD-BEARING: before 022d, orchestrator_pipeline_codeonly.md had 0 refs to
    init_session_scratch.py (022c left the script inert). This is what 022d
    delivers on the codeonly side.
    """
    assert "init_session_scratch" in _read(CODEONLY), (
        "orchestrator_pipeline_codeonly.md must reference "
        "scripts/init_session_scratch.py to initialize the session scratch dir"
    )


def test_canonical_references_init_session_scratch() -> None:
    """The canonical pipeline must invoke init_session_scratch.py (022d wiring).

    LOAD-BEARING: before 022d, orchestrator_pipeline.md had 0 refs to
    init_session_scratch.py. This is what 022d delivers on the canonical side.
    """
    assert "init_session_scratch" in _read(CANONICAL), (
        "orchestrator_pipeline.md must reference scripts/init_session_scratch.py "
        "to initialize the session scratch dir"
    )


def test_bootstrap_reads_session_before_tmp() -> None:
    """The session bootstrap must read the session scratch BEFORE falling back
    to C:\\tmp (022d wiring, part b of the seam).

    LOAD-BEARING: before 022d, Paso 0 punto 1 of orchestrator_session_bootstrap.md
    searched ONLY C:\\tmp\\HANDOFF_*.md. The fallback to C:\\tmp MUST remain
    present and intact (022c/022d do not break pre-existing handoffs); the new
    session/ reference must appear BEFORE it (by text position) so a reader
    (and an agent following the prompt) tries session/ first.
    """
    text = _read(BOOTSTRAP)
    assert ".agent/runtime/session/" in text, (
        "orchestrator_session_bootstrap.md must reference .agent/runtime/session/ "
        "as the primary handoff source (022d wiring)"
    )
    assert "C:\\tmp" in text, (
        "orchestrator_session_bootstrap.md must still reference C:\\tmp as the "
        "fallback handoff source (022c/022d must not break pre-existing handoffs)"
    )
    session_idx = text.find(".agent/runtime/session/")
    tmp_idx = text.find("C:\\tmp")
    assert session_idx < tmp_idx, (
        "the .agent/runtime/session/ reference must appear BEFORE the C:\\tmp "
        "fallback reference in Paso 0 (session-first, tmp as fallback)"
    )
