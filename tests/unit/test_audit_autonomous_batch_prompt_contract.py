"""Contract tests for prompts/audit_autonomous_ticket_batch.md
(WOT-2026-022t).

Covers the DoD: this is the AUDITOR sibling of
prompts/orchestrator_autonomous_ticket_batch.md (WOT-2026-022s, the
EXECUTOR). Without an isolated auditor, the batch's autonomy is
self-report, which prompts/audit_agent_output.md (CEM v0) forbids.

(a) ISOLATION (the load-bearing DoD test): the prompt states the auditor is
    fresh-context / isolated and that the executor cannot audit itself.
    Mutation named explicitly: allow the executor to self-audit -> RED.
(b) Form: contract_id, source_of_truth clause, READ-ONLY restriction, double
    output (.md + .json), verdict enum limited to the 4 canonical values.
(c) PREDICATE: all 7 named conditions appear. Parametrized.
(d) The 8 own-layer audit points are present. Parametrized.
(e) Inheritance without reimplementation: audit_agent_output.md,
    manager_review.md, BOTH audit_pipeline.md and audit_pipeline_codeonly.md
    (mode-dependent), and audit_goal_completion.md.
(f) The close remains owned by session-close: references
    orchestrator_session_close_full_audit.md and states the batch does NOT
    close the session itself.
(g) No dangling references: every prompts/*.md and scripts/*.py cited
    exists on disk. Exception: prompts/orchestrator_autonomous_ticket_batch.md
    (the sibling executor, WOT-2026-022s) -- asserted to exist; if it is
    missing this test documents that explicitly rather than silently
    weakening.
(h) Portability: no absolute paths / dogfooding names. Parametrized over
    forbidden tokens (mirrors test_autonomous_batch_prompt_contract.py).
(i) Skill is a pointer: SKILL.md references the prompt and declares it the
    source of truth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SKILLS = Path(__file__).resolve().parents[2] / "skills"

AUDIT_PROMPT = PROMPTS / "audit_autonomous_ticket_batch.md"
EXECUTOR_PROMPT = PROMPTS / "orchestrator_autonomous_ticket_batch.md"
SKILL_FILE = SKILLS / "audit-autonomous-ticket-batch" / "SKILL.md"


def _read() -> str:
    return AUDIT_PROMPT.read_text(encoding="utf-8")


def _read_skill() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _section_zero() -> str:
    """The text of section 0 ONLY (the nuclear isolation rule).

    Scoping is what gives the isolation barrier teeth. The isolation tokens
    ("fresh-context", "OBLIGATORIO") also occur INCIDENTALLY elsewhere in the
    prompt, so a whole-document substring check can be satisfied by text that
    has nothing to do with the rule.
    """
    text = _read()
    start = text.index("## 0.")
    end = text.index("## 1.", start)
    return text[start:end]


def test_prompt_file_exists() -> None:
    assert AUDIT_PROMPT.is_file(), (
        "prompts/audit_autonomous_ticket_batch.md must exist "
        "(WOT-2026-022t deliverable)"
    )


def test_skill_file_exists() -> None:
    assert SKILL_FILE.is_file(), (
        "skills/audit-autonomous-ticket-batch/SKILL.md must exist "
        "(WOT-2026-022t deliverable)"
    )


# ---------------------------------------------------------------------------
# SEAM 022s <-> 022t: the auditor must not audit a GHOST
#
# The chain meta-audit found the auditor evaluating a PREDICATE block that the
# executor was never instructed to emit (grep -c PREDICATE: auditor=8,
# executor=0). An auditor checking an artifact no producer emits is not a
# barrier -- it is a barrier-shaped hole. Per-ticket reviews cannot see this:
# each prompt is internally coherent. Only the seam is wrong.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [
        "GROUP_STOP_REPORT",
        "batch_run_",
    ],
)
def test_audited_artifacts_are_declared_emissions_of_the_executor(
    artifact: str,
) -> None:
    """Every artifact the AUDITOR checks must be one the EXECUTOR emits.

    LOAD-BEARING (cross-prompt seam): an auditor that checks an artifact no
    producer emits is not a barrier, it is a barrier-shaped hole.
    """
    audit_text = _read()
    exec_text = EXECUTOR_PROMPT.read_text(encoding="utf-8")
    if artifact not in audit_text:
        pytest.skip(f"{artifact} is not audited by this prompt")
    assert artifact in exec_text, (
        f"the auditor checks {artifact!r} but the executor prompt "
        f"(orchestrator_autonomous_ticket_batch.md) never declares or emits "
        f"it: the auditor is checking a ghost"
    )


# The 7 conditions of the machine-checkable predicate (design 12.bis.2.b).
PREDICATE_CONDITIONS = (
    "schema_valido",
    "dag_aciclico",
    "contabilidad_completa",
    "cierres_auditables",
    "suite_final_verde",
    "auditor_emitido",
    "arboles_limpios",
)


@pytest.mark.parametrize("condition", PREDICATE_CONDITIONS)
def test_executor_declares_every_predicate_condition_the_auditor_evaluates(
    condition: str,
) -> None:
    """The executor must DECLARE the 7-condition PREDICATE the auditor evaluates.

    LOAD-BEARING, and deliberately NOT a `"PREDICATE" in text` check: the token
    alone is a substring proxy. A first attempt at this test asserted exactly
    that, and stripping the whole PREDICATE *section* from the executor left it
    GREEN -- the word survived in an unrelated Outputs bullet. That is the same
    false-green class as the derogation attack on section 0 above: assert the
    PROPERTY, never the token.

    So this asserts every condition NAME is present. Mutation: remove the
    PREDICATE section from the executor prompt -> RED (7 of these fail).
    """
    exec_text = EXECUTOR_PROMPT.read_text(encoding="utf-8")
    assert condition in exec_text, (
        f"the auditor evaluates predicate condition {condition!r}, but the "
        f"executor prompt never declares it: the auditor audits a ghost"
    )


@pytest.mark.parametrize(
    "dag_field",
    ["stop_policy", "budget", "depends_on_groups", "shared_surfaces"],
)
def test_executor_consumes_the_dag_fields_the_schema_emits(dag_field: str) -> None:
    """The DAG schema (022r) emits these; the executor (022s) is their only
    consumer. A field the schema mandates and the executor ignores is a dead
    contract -- and the triage would be filling it for nobody.

    Mutation: remove the 'What the batch consumes from the DAG' section from
    the executor -> RED.
    """
    exec_text = EXECUTOR_PROMPT.read_text(encoding="utf-8")
    assert dag_field in exec_text, (
        f"the DAG schema autonomous-batch-dag/v1 emits {dag_field!r}, but the "
        f"executor prompt never mentions consuming it"
    )


# ---------------------------------------------------------------------------
# (a) ISOLATION -- the load-bearing DoD test
# ---------------------------------------------------------------------------

# Tokens that would REPEAL the isolation rule rather than state it. Their
# presence inside section 0 means the rule has been derogated, no matter how
# faithfully the section still quotes the original wording.
DEROGATION_TOKENS = (
    "DEROGADA",
    "derogada",
    "queda sin efecto",
    "SI PUEDE auditarlo",
    "SI PUEDE auditar",
    "PUEDE auditar su propia",
    "es opcional",
    "es OPCIONAL",
    "meramente recomendable",
)


def test_isolation_rule_lives_in_section_zero() -> None:
    """The prohibition must live INSIDE section 0, not merely somewhere in the
    document.

    LOAD-BEARING (structural, not substring): the sibling assertions below are
    whole-document `in text` checks, and the isolation tokens recur incidentally
    elsewhere in the prompt (e.g. "Review 2 fresh-context" in the close-proposal
    table). Anchoring to the section is what makes them mean what they say.
    """
    s0 = _section_zero()
    assert "NO PUEDE auditarlo" in s0, (
        "section 0 must carry the prohibition itself; a rule stated only "
        "elsewhere in the document is not the nuclear rule"
    )


@pytest.mark.parametrize("token", DEROGATION_TOKENS)
def test_isolation_rule_cannot_be_derogated(token: str) -> None:
    """LOAD-BEARING -- this is the barrier the DoD actually needs.

    The DoD's named mutation (invert the clause) goes RED, but that is NOT
    enough: a prompt can QUOTE the rule in order to REPEAL it -- keeping every
    grep-token intact -- and every substring assertion still passes. The chain
    meta-audit demonstrated exactly this: a section 0 reading "Historicamente se
    dijo: 'El agente que EJECUTO el batch NO PUEDE auditarlo' ... Esa regla queda
    DEROGADA: el ejecutor SI PUEDE auditar su propia corrida" passed all 72
    tests. That is a falso_verde: the prompt permits self-audit and the suite is
    green.

    So the assertion must be about the RULE, not about the words: no derogating
    token may appear inside section 0.

    Mutation: add "Esa regla queda DEROGADA" to section 0 -> RED.
    """
    s0 = _section_zero()
    assert token not in s0, (
        f"section 0 (the nuclear isolation rule) contains the derogating token "
        f"{token!r}: the rule is being repealed, not stated. The executor must "
        f"NEVER be permitted to audit its own run (CEM v0: no self-report)."
    )


def test_prompt_states_executor_cannot_audit_itself() -> None:
    """LOAD-BEARING: the prompt must explicitly forbid the executor from
    auditing its own run.

    DoD mutation named explicitly: strip this clause (or invert it to allow
    self-audit) -> this test goes RED. This is the single strongest
    assertion in this file: it is the entire reason this auditor exists as
    a SIBLING prompt instead of a section inside the executor.
    """
    text = _read()
    self_audit_forbidden = (
        "EJECUTO el batch NO PUEDE auditarlo" in text
        or "cannot audit itself" in text
        or "no puede auditarlo" in text
    )
    assert self_audit_forbidden, (
        "audit_autonomous_ticket_batch.md must explicitly state the agent "
        "that executed the batch cannot audit it (self-certification is "
        "forbidden by CEM)"
    )


def test_prompt_requires_fresh_context_isolation() -> None:
    """LOAD-BEARING: fresh-context (or model-distinct) isolation must be
    MANDATORY, not optional advice.

    Mutation: remove "OBLIGATORIO"/mandatory language around fresh-context
    -> RED.
    """
    text = _read()
    assert "FRESH CONTEXT" in text.upper() or "fresh-context" in text.lower(), (
        "the prompt must require fresh-context isolation for the auditor"
    )
    assert "OBLIGATORIO" in text or "MANDATORY" in text.upper(), (
        "fresh-context isolation must be stated as mandatory, not optional"
    )


def test_prompt_invalidates_verdict_without_isolation() -> None:
    """LOAD-BEARING: if isolation cannot be demonstrated, no verdict may be
    emitted at all -- this is stronger than "the verdict is weak"."""
    text = _read()
    assert "NO AUDITABLE POR FALTA" in text or "invalido" in text.lower(), (
        "the prompt must state that a verdict emitted without demonstrated "
        "isolation is invalid / the run is not auditable"
    )


def test_prompt_references_goal_completion_isolation_pattern() -> None:
    """The isolation pattern is inherited from audit_goal_completion.md's
    'checker isolated from the orchestrator-executor', not invented here."""
    text = _read()
    assert "audit_goal_completion.md" in text
    assert "B1" in text and "B3" in text, (
        "the prompt must reproduce the B1 (real isolation) and B3 "
        "(read-only privilege isolation) conditions from "
        "audit_goal_completion.md"
    )


# ---------------------------------------------------------------------------
# (b) Form
# ---------------------------------------------------------------------------


def test_prompt_declares_contract_id() -> None:
    text = _read()
    assert "cid-audit-autonomous-ticket-batch-v1" in text, (
        "the prompt must declare contract_id: cid-audit-autonomous-ticket-batch-v1"
    )


def test_prompt_declares_source_of_truth_clause() -> None:
    text = _read()
    assert "source_of_truth" in text, "the prompt must declare a source_of_truth clause"
    assert "skills/audit-autonomous-ticket-batch/SKILL.md" in text, (
        "the prompt must point at its canonical skill wrapper"
    )


def test_prompt_states_read_only_restriction() -> None:
    text = _read()
    assert "READ-ONLY" in text.upper() or "READ ONLY" in text.upper(), (
        "the prompt must state an explicit READ-ONLY restriction"
    )
    assert "NUNCA modifica" in text or "never modif" in text.lower(), (
        "the prompt must state the auditor never mutates the audited repo"
    )


def test_prompt_declares_double_output_md_and_json() -> None:
    """The prompt must declare BOTH a .md report AND a .json artifact."""
    text = _read()
    assert ".md" in text and ".json" in text
    assert "audit_autonomous_batch_" in text, (
        "the prompt must name the output artifact prefix "
        "audit_autonomous_batch_<timestamp> for both .md and .json"
    )


VERDICT_ENUM = [
    "APROBADO",
    "APROBADO CON NITS",
    "CAMBIOS NECESARIOS",
    "NO ACEPTAR TODAVIA",
]


@pytest.mark.parametrize("verdict", VERDICT_ENUM)
def test_prompt_lists_canonical_verdict(verdict: str) -> None:
    text = _read()
    assert verdict in text, f"the prompt must list the canonical verdict {verdict!r}"


def test_prompt_blocks_verdict_on_false_green_or_closure_not_landed() -> None:
    """A confirmed falso_verde or CLOSURE_NOT_LANDED must BLOCK the verdict."""
    text = _read()
    assert "falso_verde" in text
    assert "CLOSURE_NOT_LANDED" in text
    assert (
        "BLOQUEAN el veredicto" in text
        or "BLOCKS the verdict" in text.upper()
        or ("bloquean" in text.lower() and "veredicto" in text.lower())
    ), (
        "the prompt must state that a confirmed falso_verde or "
        "CLOSURE_NOT_LANDED blocks the verdict"
    )


# ---------------------------------------------------------------------------
# (c) PREDICATE: all 7 named conditions
# ---------------------------------------------------------------------------

PREDICATE_CONDITIONS = [
    "schema_valido",
    "dag_aciclico",
    "contabilidad_completa",
    "cierres_auditables",
    "suite_final_verde",
    "auditor_emitido",
    "arboles_limpios",
]


@pytest.mark.parametrize("condition", PREDICATE_CONDITIONS)
def test_prompt_names_predicate_condition(condition: str) -> None:
    text = _read()
    assert condition in text, (
        f"the prompt must reproduce the PREDICATE condition {condition!r} "
        f"(design section 12.bis.2.b)"
    )


def test_predicate_conditions_are_command_by_command() -> None:
    """The predicate must be evaluated command-by-command (real exit codes),
    not narrative -- design section 12.bis.2.b's core requirement."""
    text = _read()
    assert "exit code" in text.lower() or "exit_code" in text.lower()
    assert (
        "comando a comando" in text.lower()
        or "command-by-command" in text.lower()
        or ("comando" in text.lower() and "exit" in text.lower())
    )


def test_predicate_has_mutation_demo() -> None:
    """The DoD requires a mutation-demo of the predicate: falsifying one
    condition (e.g. a row archived without a commit: cell) must make the
    predicate FALSE and be reported by the auditor."""
    text = _read()
    assert "Mutation-demo" in text or "mutation-demo" in text
    assert "commit:" in text


def test_predicate_cierres_auditables_requires_counter_to_rise() -> None:
    """LOAD-BEARING nuance from the DoD: ERROR=0 != audited; the guard used
    to skip rows lacking a commit: cell in silence (class H1)."""
    text = _read()
    assert "audited" in text
    assert "ERROR=0" in text or "ERROR = 0" in text
    assert (
        "no suficiente" in text.lower()
        or "not suffi" in text.lower()
        or ("necesario" in text.lower() and "suficiente" in text.lower())
    ), (
        "the prompt must state that ERROR=0 is necessary but NOT sufficient "
        "for cierres_auditables -- the audited counter must be seen to rise"
    )


def test_predicate_suite_final_verde_reads_real_output_not_wrapper_exit() -> None:
    """LOAD-BEARING nuance: a suite run pre-commit yields the parent's
    tested_sha; the wrapper's exit code is not trustworthy on its own."""
    text = _read()
    assert "tested_sha == HEAD" in text or "tested_commit_sha == HEAD" in text
    assert "wrapper" in text.lower()


# ---------------------------------------------------------------------------
# (d) The 8 own-layer audit points
# ---------------------------------------------------------------------------

OWN_LAYER_POINTS = [
    "Decisiones de PARADA",
    "Exclusiones duras",
    "Recovery loops",
    "Checkpoints de confianza",
    "Contencion",
    "Autoridad",
    "Portabilidad",
    "objetivo_huerfano",
]


@pytest.mark.parametrize("point", OWN_LAYER_POINTS)
def test_prompt_names_own_layer_point(point: str) -> None:
    text = _read()
    assert point in text, (
        f"the prompt must reproduce the own-layer audit point {point!r} "
        f"(design section 12.bis.1, the 8 points no existing audit covers)"
    )


def test_own_layer_has_exactly_eight_enumerated_points() -> None:
    """The prompt must present the 8 points as a numbered list 1-8 (design
    fidelity: this is a fixed inventory, not an open-ended list)."""
    text = _read()
    for n in range(1, 9):
        assert re.search(rf"^{n}\.\s", text, re.MULTILINE), (
            f"expected an enumerated point {n!r} in the own-layer audit list"
        )


def test_stop_decisions_point_covers_the_worse_case_of_continuing() -> None:
    """LOAD-BEARING nuance from the DoD: the worse case is not just a noisy
    stop, but the batch CONTINUING where it should have stopped."""
    text = _read()
    assert (
        "CONTINUO" in text or "CONTINUED" in text.upper() or "continued" in text.lower()
    ), (
        "the prompt must cover the case where the batch continued past a "
        "point where it should have stopped (the more serious failure mode)"
    )


def test_recovery_loops_point_requires_distinct_enfoque() -> None:
    text = _read()
    assert "enfoque_intentado" in text
    assert "DISTINTO" in text.upper() or "distinct" in text.lower()


def test_checkpoints_point_names_class_h1() -> None:
    """LOAD-BEARING: the H1 class (guard skipping rows without commit: cell
    in silence) is the concrete false-green this point exists to catch."""
    text = _read()
    assert "H1" in text
    assert "commit:" in text


# ---------------------------------------------------------------------------
# (e) Inheritance without reimplementation
# ---------------------------------------------------------------------------


def test_prompt_inherits_audit_agent_output_philosophy() -> None:
    text = _read()
    assert "audit_agent_output.md" in text


def test_prompt_inherits_manager_review_mechanic() -> None:
    text = _read()
    assert "manager_review.md" in text


def test_prompt_inherits_both_chain_audit_variants() -> None:
    """Both audit_pipeline.md and audit_pipeline_codeonly.md must be cited
    (mode-dependent inheritance) -- neither one alone is sufficient because
    the auditor must handle either mode the executor might have run in."""
    text = _read()
    assert "audit_pipeline.md" in text
    assert "audit_pipeline_codeonly.md" in text


def test_prompt_inherits_goal_completion_isolation() -> None:
    text = _read()
    assert "audit_goal_completion.md" in text


def test_prompt_declares_mode_detection_for_inheritance() -> None:
    """The prompt must route WHICH chain-audit base it inherits via
    is_motor_code_only(), not assume one mode."""
    text = _read()
    assert "is_motor_code_only" in text


# ---------------------------------------------------------------------------
# (f) The close remains owned by session-close
# ---------------------------------------------------------------------------


def test_prompt_references_session_close_full_audit() -> None:
    text = _read()
    assert "orchestrator_session_close_full_audit.md" in text


def test_prompt_states_batch_never_closes_session_itself() -> None:
    """LOAD-BEARING: the report PROPOSES; the batch never closes the
    session on its own (design section 12.bis.2 hard rule)."""
    text = _read()
    assert "PROPONE" in text or "PROPOSES" in text.upper()
    assert (
        "nunca cierra la sesion" in text.lower()
        or "never close" in text.lower()
        or "no cierra la sesion" in text.lower()
    ), (
        "the prompt must state the batch/auditor never closes the session "
        "by itself -- only the human/Manager decides"
    )


def test_prompt_reproduces_close_proposal_mapping_table() -> None:
    """The mapping table from design 12.bis.2 (session-close block -> what
    the batch report contributes) must be reproduced, not just referenced."""
    text = _read()
    for token in (
        "Salud del sistema",
        "Adversarial sobre los diffs",
        "Rendimiento de la suite",
        "Publicacion",
        "Memoria",
        "Follow-ups",
    ):
        assert token in text, f"close-proposal mapping table missing row: {token!r}"


def test_prompt_mentions_known_nit_022l() -> None:
    """The DoD explicitly asks to mention the known nit: a false critical
    from a stale last-run of the destino."""
    text = _read()
    assert "last-run" in text.lower() or "last_run" in text.lower()
    assert "stale" in text.lower() or "viejo" in text.lower()


# ---------------------------------------------------------------------------
# (g) No dangling references
# ---------------------------------------------------------------------------


def _referenced_prompt_files(text: str) -> set[str]:
    return set(re.findall(r"prompts/([A-Za-z0-9_.\-]+\.md)", text))


def _referenced_script_files(text: str) -> set[str]:
    return set(re.findall(r"scripts/([A-Za-z0-9_.\-]+\.py)", text))


def test_no_dangling_prompt_references() -> None:
    """Every prompts/*.md file cited in the audit prompt must exist on disk.

    orchestrator_autonomous_ticket_batch.md is the sibling EXECUTOR
    (WOT-2026-022s). It is expected to exist by commit time (concurrent
    sibling ticket); this test asserts it directly rather than silently
    excluding it, per the task instructions ("prefer writing the test so
    it asserts existence").
    """
    text = _read()
    referenced = _referenced_prompt_files(text)
    assert referenced, "expected at least one prompts/*.md reference to check"
    missing = [name for name in referenced if not (PROMPTS / name).is_file()]
    assert not missing, f"dangling prompt references (do not exist): {missing}"


def test_sibling_executor_prompt_referenced_and_exists() -> None:
    """The audit prompt must name its sibling executor
    orchestrator_autonomous_ticket_batch.md, and that file must exist on
    disk (022s sibling ticket)."""
    text = _read()
    assert "orchestrator_autonomous_ticket_batch.md" in text, (
        "the audit prompt must reference its executor sibling "
        "orchestrator_autonomous_ticket_batch.md"
    )
    assert EXECUTOR_PROMPT.is_file(), (
        "prompts/orchestrator_autonomous_ticket_batch.md (WOT-2026-022s, "
        "the sibling executor) does not exist on disk yet; this test "
        "documents that as a real premise-not-yet-true rather than "
        "weakening the assertion"
    )


def test_no_dangling_script_references() -> None:
    text = _read()
    referenced = _referenced_script_files(text)
    assert referenced, "expected at least one scripts/*.py reference to check"
    missing = [name for name in referenced if not (SCRIPTS / name).is_file()]
    assert not missing, f"dangling script references (do not exist): {missing}"


def test_prompt_cites_the_real_destination_context_path_if_at_all() -> None:
    """Ground truth (verified by executed probe, per task instructions): the
    frozen design's runtime.destination_context module does not exist; the
    real path is scripts/destination_context.py. If this prompt cites
    resolve_motor_link at all, it must cite the REAL path."""
    text = _read()
    if "resolve_motor_link" in text:
        assert (
            "scripts.destination_context" in text
            or "scripts/destination_context.py" in text
        ), (
            "if the prompt cites resolve_motor_link, it must cite the REAL "
            "path scripts/destination_context.py, not the frozen design's "
            "wrong runtime.destination_context"
        )
    assert "runtime.destination_context" not in text, (
        "the prompt must never repeat the frozen design's wrong import "
        "path runtime.destination_context (does not exist)"
    )


def test_prompt_cites_validate_batch_dag_script() -> None:
    text = _read()
    assert "validate_batch_dag.py" in text
    assert (SCRIPTS / "validate_batch_dag.py").is_file()


def test_prompt_cites_check_backlog_commits_landed_script() -> None:
    text = _read()
    assert "check_backlog_commits_landed.py" in text
    assert (SCRIPTS / "check_backlog_commits_landed.py").is_file()


# ---------------------------------------------------------------------------
# (h) Portability
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
    text = _read()
    assert token not in text, (
        f"audit_autonomous_ticket_batch.md must not contain the "
        f"dogfooding-instance token {token!r}; the auditor is portable "
        f"across any repo_destino"
    )


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_skill_has_no_dogfooding_instance_token(token: str) -> None:
    text = _read_skill()
    assert token not in text, (
        f"SKILL.md must not contain the dogfooding-instance token {token!r}"
    )


def test_prompt_is_ascii_only() -> None:
    text = _read()
    non_ascii = [c for c in text if ord(c) > 127]
    assert not non_ascii, (
        f"audit_autonomous_ticket_batch.md must be ASCII-only; "
        f"found non-ascii chars: {set(non_ascii)!r}"
    )


def test_skill_is_ascii_only() -> None:
    text = _read_skill()
    non_ascii = [c for c in text if ord(c) > 127]
    assert not non_ascii, (
        f"SKILL.md must be ASCII-only; found non-ascii chars: {set(non_ascii)!r}"
    )


def test_prompt_does_not_hardcode_fixed_repo_count() -> None:
    """The prompt must enumerate repos from the RESOLVED topology, never
    hardcode a fixed number (design section 1.2/15)."""
    text = _read()
    assert "resolved topology".lower() in text.lower() or (
        "topologia" in text.lower() and "resuelt" in text.lower()
    )
    assert "hardcode" in text.lower() or "hardcodee" in text.lower(), (
        "the prompt must explicitly forbid hardcoding a fixed repo count"
    )


# ---------------------------------------------------------------------------
# (i) Skill is a pointer
# ---------------------------------------------------------------------------


def test_skill_references_the_prompt() -> None:
    text = _read_skill()
    assert "prompts/audit_autonomous_ticket_batch.md" in text


def test_skill_declares_prompt_as_source_of_truth() -> None:
    text = _read_skill()
    assert "fuente de verdad" in text.lower() or "source of truth" in text.lower()
    assert "prevalece" in text.lower() or "prevails" in text.lower()


def test_skill_declares_contract_id_matching_prompt() -> None:
    prompt_text = _read()
    skill_text = _read_skill()
    match = re.search(r"contract_id:\s*(\S+)", prompt_text)
    assert match, "prompt must declare a contract_id line"
    assert match.group(1) in skill_text, (
        "SKILL.md frontmatter contract_id must match the prompt's contract_id"
    )


def test_skill_states_isolation_requirement_too() -> None:
    """The skill wrapper must not silently drop the isolation requirement --
    it should point a reader at the rule even though the prompt is the
    source of truth."""
    text = _read_skill()
    assert "aislamiento" in text.lower() or "isolation" in text.lower()


# ---------------------------------------------------------------------------
# Distinctness / seam guards
# ---------------------------------------------------------------------------


def test_audit_and_executor_prompts_are_distinct_files() -> None:
    """Guard against a symlink/alias collapsing the auditor and executor
    prompts into the same content, which would defeat isolation entirely."""
    assert AUDIT_PROMPT != EXECUTOR_PROMPT
    if EXECUTOR_PROMPT.is_file():
        assert AUDIT_PROMPT.read_text(encoding="utf-8") != EXECUTOR_PROMPT.read_text(
            encoding="utf-8"
        ), "the auditor prompt must not be identical to the executor prompt"


def test_skill_collision_name_is_distinct_from_executor_skill() -> None:
    """The auditor skill name must not collide with the executor's skill
    name (orchestrate-autonomous-ticket-batch, per the sibling 022s test
    file's referenced skill path)."""
    skill_dir = SKILL_FILE.parent
    assert skill_dir.name == "audit-autonomous-ticket-batch"
    executor_skill_dir = SKILLS / "orchestrate-autonomous-ticket-batch"
    assert skill_dir != executor_skill_dir
