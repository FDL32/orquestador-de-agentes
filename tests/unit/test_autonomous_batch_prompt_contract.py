"""Contract tests for prompts/orchestrator_autonomous_ticket_batch.md
(WOT-2026-022s).

Covers the DoD from design_autonomous_ticket_batch.md section 15
(portability) plus the executor-specific contract clauses (authority,
tier scope, seam guard against dangling references).

(a) Portability contract: the prompt contains no absolute path and none of
    the dogfooding-instance names. Parametrized over the forbidden tokens.
    Mutation the docstring must name: introduce "_dev" into the prompt ->
    RED (any single parametrized case flips).
(b) Mode routing is BIDIRECTIONAL and each half is a SEPARATE test so that
    wiring only one mode leaves the OTHER test red (branch isolation,
    lesson 021u -- mirrors tests/test_pipeline_adversarial_wiring.py).
(c) No reclassification: the prompt explicitly forbids the executor from
    reclassifying a ticket's class/autonomy_mode.
(d) Tier scope: the prompt states Tier 2/3 are NOT implemented.
(e) No dangling references: every prompts/*.md and scripts/*.py file the
    prompt cites exists on disk (seam guard). This is what would have
    caught the runtime.destination_context error from the frozen design;
    it also proves the prompt cites the REAL scripts/destination_context.py
    path, not the design's wrong one.
(f) contract_id + source_of_truth clause are declared.
(g) Hard-stop causes and the GROUP_STOP_REPORT required fields are present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
BATCH_PROMPT = PROMPTS / "orchestrator_autonomous_ticket_batch.md"


def _read() -> str:
    return BATCH_PROMPT.read_text(encoding="utf-8")


def test_prompt_file_exists() -> None:
    assert BATCH_PROMPT.is_file(), (
        "prompts/orchestrator_autonomous_ticket_batch.md must exist "
        "(WOT-2026-022s deliverable)"
    )


# ---------------------------------------------------------------------------
# (a) Portability contract
# ---------------------------------------------------------------------------

FORBIDDEN_TOKENS = [
    "_dev",
    "orquestador_de_agentes_workspace",
    "orquestador_de_agentes_dev",
    "C:" + chr(92),
    "c:" + chr(92),
]


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_prompt_has_no_dogfooding_instance_token(token: str) -> None:
    """Portability DoD (design section 15, mutation named explicitly):
    introduce `_dev` (or any sibling forbidden token) into the prompt -> RED.

    Each token is its OWN parametrized case: a single leaked token flips
    exactly that case, not the whole suite in one blob assertion.
    """
    text = _read()
    assert token not in text, (
        f"orchestrator_autonomous_ticket_batch.md must not contain the "
        f"dogfooding-instance token {token!r}; the executor is portable "
        f"across any repo_destino (design section 1/15)"
    )


def test_prompt_is_ascii_only() -> None:
    """Encoding guard: the prompt must be ASCII-only (strict guard elsewhere
    in this repo rejects non-ASCII in tracked prompts)."""
    text = _read()
    non_ascii = [c for c in text if ord(c) > 127]
    assert not non_ascii, (
        f"orchestrator_autonomous_ticket_batch.md must be ASCII-only; "
        f"found non-ascii chars: {set(non_ascii)!r}"
    )


# ---------------------------------------------------------------------------
# (b) Mode routing is BIDIRECTIONAL -- SEPARATE tests, branch isolation
# ---------------------------------------------------------------------------


def test_prompt_references_is_motor_code_only_detector() -> None:
    """The executor must detect the mode via is_motor_code_only(); it must
    never assume the topology. Mutation: remove the detector reference ->
    this test alone goes RED (does not touch the destino/codeonly branches)."""
    text = _read()
    assert "is_motor_code_only" in text, (
        "orchestrator_autonomous_ticket_batch.md must reference "
        "is_motor_code_only() to detect the deployment mode"
    )


def test_prompt_wires_codeonly_branch() -> None:
    """MODE MOTOR CODE-ONLY branch: delegates to orchestrator_pipeline_codeonly.md
    and closes via commit-directo.

    LOAD-BEARING / branch isolation (lesson 021u): if only the destino branch
    were wired, this test alone goes RED; it does not depend on the destino
    branch's assertions in test_prompt_wires_destino_branch below."""
    text = _read()
    assert "orchestrator_pipeline_codeonly.md" in text, (
        "the code-only mode must delegate to orchestrator_pipeline_codeonly.md"
    )
    assert "commit-directo" in text, (
        "the code-only mode must close tickets via commit-directo, not the bus"
    )


def test_prompt_wires_destino_branch() -> None:
    """MODE DESTINO branch: delegates to orchestrator_pipeline.md and closes
    via the bus ops (--bootstrap-ticket -> --mark-ready -> --manager-approve).

    LOAD-BEARING / branch isolation (lesson 021u): if only the code-only
    branch were wired, this test alone goes RED; it is independent of
    test_prompt_wires_codeonly_branch above -- wiring a single mode leaves
    exactly one of these two tests failing, never both, never neither."""
    text = _read()
    assert "orchestrator_pipeline.md" in text, (
        "the destino mode must delegate to orchestrator_pipeline.md"
    )
    for bus_op in ("--bootstrap-ticket", "--mark-ready", "--manager-approve"):
        assert bus_op in text, (
            f"the destino mode must close tickets via the bus op {bus_op!r}"
        )


def test_prompt_wires_chain_audit_per_mode() -> None:
    """Both chain-audit variants must be cited (one per mode)."""
    text = _read()
    assert "audit_pipeline.md" in text, "destino mode chain audit must be cited"
    assert "audit_pipeline_codeonly.md" in text, (
        "code-only mode chain audit must be cited"
    )


def test_codeonly_and_destino_prompts_are_distinct_files() -> None:
    """Guard against a symlink/alias collapsing the two pipeline files into
    one, which would let one branch's refs mask a missing other branch."""
    canonical = PROMPTS / "orchestrator_pipeline.md"
    codeonly = PROMPTS / "orchestrator_pipeline_codeonly.md"
    assert canonical != codeonly
    assert canonical.read_text(encoding="utf-8") != codeonly.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (c) No reclassification
# ---------------------------------------------------------------------------


def test_prompt_forbids_reclassification() -> None:
    text = _read()
    assert "NEVER reclassifies" in text or "never reclassifies" in text, (
        "the prompt must explicitly state the executor never reclassifies "
        "a ticket/group's class or autonomy_mode"
    )
    assert "falso_verde" in text, (
        "reclassifying to dodge a gate must be named as falso_verde "
        "(CEM contract), matching the design's authority rule (section 4)"
    )


# ---------------------------------------------------------------------------
# (d) Tier scope
# ---------------------------------------------------------------------------


def test_prompt_states_tier_scope() -> None:
    text = _read()
    assert "Tier 0" in text and "Tier 1" in text, (
        "the prompt must name Tier 0 and Tier 1 as the implemented scope"
    )
    assert re.search(r"Tier 2.{0,40}NOT IMPLEMENTED", text) or (
        "NOT IMPLEMENTED" in text and "Tier 2" in text
    ), "the prompt must explicitly state Tier 2 is NOT implemented"
    assert "Tier 3" in text, "the prompt must name Tier 3 as out of scope"


# ---------------------------------------------------------------------------
# (e) No dangling references (seam guard)
# ---------------------------------------------------------------------------


def _referenced_prompt_files(text: str) -> set[str]:
    return set(re.findall(r"prompts/([A-Za-z0-9_.\-]+\.md)", text))


def _referenced_script_files(text: str) -> set[str]:
    return set(re.findall(r"scripts/([A-Za-z0-9_.\-]+\.py)", text))


# audit_autonomous_ticket_batch.md is the sibling AUDITOR prompt (WOT-2026-022t),
# delivered as its own ticket per the frozen design ("T2 + T3 juntos"). The
# batch prompt names it deliberately (see test_prompt_names_its_sibling_auditor)
# even though it does not exist yet at the time 022s lands; it is the ONLY
# allowed exception to the dangling-reference seam guard below.
KNOWN_SIBLING_NOT_YET_DELIVERED = {"audit_autonomous_ticket_batch.md"}


def test_no_dangling_prompt_references() -> None:
    """Every prompts/*.md file cited in the batch prompt must exist on disk,
    except the one documented sibling-not-yet-delivered exception above."""
    text = _read()
    referenced = _referenced_prompt_files(text) - KNOWN_SIBLING_NOT_YET_DELIVERED
    assert referenced, "expected at least one prompts/*.md reference to check"
    missing = [name for name in referenced if not (PROMPTS / name).is_file()]
    assert not missing, f"dangling prompt references (do not exist): {missing}"


def test_no_dangling_script_references() -> None:
    """Every scripts/*.py file cited in the batch prompt must exist on disk.

    This is the seam guard that would have caught the frozen design's wrong
    path (runtime.destination_context, which does not exist): the prompt
    must cite the REAL scripts/destination_context.py instead.
    """
    text = _read()
    referenced = _referenced_script_files(text)
    assert referenced, "expected at least one scripts/*.py reference to check"
    missing = [name for name in referenced if not (SCRIPTS / name).is_file()]
    assert not missing, f"dangling script references (do not exist): {missing}"


def test_prompt_cites_the_real_destination_context_path() -> None:
    """The frozen design cited runtime.destination_context.resolve_motor_link,
    which does NOT exist. The real location is scripts/destination_context.py.
    This test proves the batch prompt cites the REAL path, not the design's
    dangling one; test_no_dangling_script_references above proves the file
    on disk actually exists."""
    text = _read()
    assert (
        "scripts.destination_context" in text
        or "scripts/destination_context.py" in text
    ), (
        "the prompt must cite the REAL location of resolve_motor_link: "
        "scripts/destination_context.py (NOT runtime.destination_context, "
        "which does not exist)"
    )
    assert "runtime.destination_context" not in text, (
        "the prompt must not repeat the frozen design's wrong import path "
        "runtime.destination_context (dangling reference)"
    )
    assert (SCRIPTS / "destination_context.py").is_file(), (
        "scripts/destination_context.py must exist on disk for the cited "
        "import to be real"
    )


def test_prompt_cites_validate_batch_dag_script() -> None:
    """The executor must invoke scripts/validate_batch_dag.py on the DAG
    before executing it (022r validator)."""
    text = _read()
    assert "validate_batch_dag.py" in text, (
        "the prompt must invoke scripts/validate_batch_dag.py on the DAG "
        "before executing it"
    )
    assert (SCRIPTS / "validate_batch_dag.py").is_file()


# ---------------------------------------------------------------------------
# (f) contract_id + source_of_truth clause
# ---------------------------------------------------------------------------


def test_prompt_declares_contract_id() -> None:
    text = _read()
    assert "cid-orchestrator-autonomous-ticket-batch-v1" in text, (
        "the prompt must declare contract_id: "
        "cid-orchestrator-autonomous-ticket-batch-v1"
    )


def test_prompt_declares_source_of_truth_clause() -> None:
    text = _read()
    assert "source_of_truth" in text, (
        "the prompt must declare a source_of_truth clause (this prompt "
        "prevails over the skill wrapper if they diverge)"
    )
    assert "skills/orchestrate-autonomous-ticket-batch/SKILL.md" in text, (
        "the prompt must point at its canonical skill wrapper"
    )


def test_prompt_names_its_sibling_auditor() -> None:
    """The prompt must state its audit is a SIBLING prompt (022t) and that
    the executor cannot audit itself (fresh-context isolation, CEM)."""
    text = _read()
    assert "audit_autonomous_ticket_batch.md" in text, (
        "the prompt must name its sibling auditor prompt "
        "audit_autonomous_ticket_batch.md"
    )
    assert "cannot audit itself" in text or "cannot self-audit" in text, (
        "the prompt must explicitly state the executor cannot audit itself"
    )


# ---------------------------------------------------------------------------
# (g) Hard-stop causes and GROUP_STOP_REPORT required fields
# ---------------------------------------------------------------------------

HARD_STOP_CAUSES = [
    "suite_roja_heredada",
    "flaky",
    "falso_verde",
    "bus_drift",
    "scope_dirty_no_atribuible",
    "estado_canonico_dividido",
]


@pytest.mark.parametrize("cause", HARD_STOP_CAUSES)
def test_prompt_lists_hard_stop_cause(cause: str) -> None:
    text = _read()
    assert cause in text, f"the prompt must list the hard-stop cause {cause!r}"


GROUP_STOP_REPORT_FIELDS = [
    "group",
    "ticket",
    "state",
    "stage",
    "cause_type",
    "evidence_level",
    "auditor_confidence",
    "evidence",
    "recovery_attempts",
    "repos",
    "fresh_sha_verified_at",
    "dirty_files_count",
    "last_bus_event",
    "last_confidence_checkpoint",
    "blocked_tickets",
    "independent_groups_available",
    "next_recommended_group",
]


@pytest.mark.parametrize("field", GROUP_STOP_REPORT_FIELDS)
def test_group_stop_report_has_required_field(field: str) -> None:
    text = _read()
    assert f'"{field}"' in text, (
        f"GROUP_STOP_REPORT schema in the prompt must include field {field!r}"
    )


def test_group_stop_report_evidence_level_and_confidence_are_separate() -> None:
    """evidence_level and auditor_confidence must be documented as SEPARATE
    fields (design section 9): confidence never substitutes for evidence."""
    text = _read()
    assert '"evidence_level"' in text and '"auditor_confidence"' in text
    idx_evidence = text.find('"evidence_level"')
    idx_confidence = text.find('"auditor_confidence"')
    assert idx_evidence != -1 and idx_confidence != -1
    # Both must appear inside the GROUP_STOP_REPORT block, and the prompt
    # must explicitly say confidence never substitutes for evidence.
    assert "never substitutes for evidence" in text or ("confidence never" in text), (
        "the prompt must state that auditor_confidence never substitutes "
        "for evidence_level"
    )
