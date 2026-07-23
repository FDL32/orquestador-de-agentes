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
SKILLS = Path(__file__).resolve().parents[2] / "skills"
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


def _referenced_skill_files(text: str) -> set[str]:
    """skills/<name>/SKILL.md references.

    This regex did not exist until the chain meta-audit of 022u/r/s/t: the
    seam guard covered prompts/ and scripts/ but NOT skills/, so the prompt
    could declare `Skill canonica: skills/orchestrate-autonomous-ticket-batch/
    SKILL.md` while that file did not exist. It did not exist. Any reference
    class left unguarded is a reference class that will eventually dangle.
    """
    return set(re.findall(r"skills/([A-Za-z0-9_.\-]+)/SKILL\.md", text))


def test_no_dangling_prompt_references() -> None:
    """Every prompts/*.md file cited in the batch prompt must exist on disk.

    NOTE: an exception constant (KNOWN_SIBLING_NOT_YET_DELIVERED) used to
    whitelist audit_autonomous_ticket_batch.md here, because 022s landed on
    disk before its sibling 022t. Both shipped in the same commit, so the
    exception is RETIRED: keeping it would silently mask a real regression if
    the auditor prompt were ever deleted.
    """
    text = _read()
    referenced = _referenced_prompt_files(text)
    assert referenced, "expected at least one prompts/*.md reference to check"
    missing = [name for name in referenced if not (PROMPTS / name).is_file()]
    assert not missing, f"dangling prompt references (do not exist): {missing}"


def test_no_dangling_skill_references() -> None:
    """Every skills/<name>/SKILL.md cited in the batch prompt must exist.

    LOAD-BEARING: the executor declares `Skill canonica:
    skills/orchestrate-autonomous-ticket-batch/SKILL.md`. The chain meta-audit
    found that file MISSING -- the auditor got a skill, the executor did not --
    and no test caught it, because the seam guard never looked at skills/.

    Mutation: delete skills/orchestrate-autonomous-ticket-batch/SKILL.md -> RED.
    """
    text = _read()
    referenced = _referenced_skill_files(text)
    assert referenced, "the batch prompt must declare its canonical skill"
    missing = [n for n in referenced if not (SKILLS / n / "SKILL.md").is_file()]
    assert not missing, f"dangling skill references (do not exist): {missing}"


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


# ---------------------------------------------------------------------------
# WOT-2026-024b: barrier 3 must enumerate a CLOSED gate list, not a trust
# instruction. The leak (2026-07-14): the executor ran `ruff check` green and
# shipped, but `ruff format --check` -- a SEPARATE gate -- was red. A partial
# gate run is falso_verde; the list must be explicit so omitting one is visible.
# ---------------------------------------------------------------------------

REQUIRED_GATE_TOKENS = [
    "ruff check",
    "ruff format --check",
    "run_pytest_safe.py",
    "pip_audit_project.py",
]


def _barrier3_block() -> str:
    """The text of barrier 3 only (between the '3.' and '4.' headings), so the
    assertion is scoped to the ENUMERATION, not any prose mention elsewhere in
    the prompt (the incident narrative also names the gates)."""
    text = _read()
    start = text.index("3. **Gates run by the orchestrator")
    end = text.index("4. **Mutation", start)
    return text[start:end]


@pytest.mark.parametrize("gate", REQUIRED_GATE_TOKENS)
def test_barrier3_enumerates_gate(gate: str) -> None:
    """Barrier 3 must enumerate each closed-list gate AS A BULLET, not merely
    mention it in prose. Mutation: drop a gate's bullet from barrier 3 -> that
    parametrized case flips RED (even though the incident narrative still names
    the gate, so a whole-file grep would NOT have teeth)."""
    bullet_lines = [
        ln for ln in _barrier3_block().splitlines() if ln.lstrip().startswith("-")
    ]
    assert any(gate in ln for ln in bullet_lines), (
        f"barrier 3 must ENUMERATE the gate {gate!r} as a bullet (WOT-2026-024b):"
        " a partial gate run is falso_verde, so the list cannot be left to memory"
    )


# ---------------------------------------------------------------------------
# WOT-2026-023v: mandatory outputs get a MECHANICAL barrier. In the inaugural
# run the executor omitted batch_run_<ts>.json (written retrospectively) and
# self-evaluated condition 6, and nothing detected either. The barrier is the
# sibling audit's fail-closed input contract + this blocking DONE step.
# ---------------------------------------------------------------------------


def test_prompt_declares_blocking_done_step() -> None:
    """The batch cannot be declared DONE without batch_run_<ts>.json ON DISK
    (read back by command, not from memory) and the sibling audit LAUNCHED.
    Mutation: drop the blocking-step section -> RED."""
    text = _read()
    assert "Blocking close step" in text, (
        "the prompt must carry the WOT-2026-023v blocking close step"
    )
    assert "may NOT be declared `DONE`" in text
    assert "READING the actual file back" in text, (
        "existence of batch_run must be verified by command, never by memory"
    )


def test_predicate_cond6_is_dual_contract_pending() -> None:
    """Cond 6 (auditor_emitido) is DUAL CONTRACT (P5): the executor emits it
    as PENDING -- it cannot self-certify -- and only the sibling audit
    resolves it. Mutation: drop the annotation from the PREDICATE row -> RED."""
    text = _read()
    assert "DUAL CONTRACT" in text
    assert "PENDING" in text
    assert "self-certify" in text


# ---------------------------------------------------------------------------
# WOT-2026-023t: the 'Validate the DAG' section wires the FRESHNESS gate. A
# schema-valid DAG can be DEAD (inaugural run: its recommended_start ticket
# was already closed and archived; only a human caught it).
# ---------------------------------------------------------------------------


def test_validate_section_wires_live_backlog_freshness_gate() -> None:
    """The validation command must carry --live-backlog (semantic freshness:
    every DAG ticket still pending in the live queue). Mutation: drop the flag
    from the section -> RED."""
    text = _read()
    assert "--live-backlog" in text, (
        "the 'Validate the DAG' section must wire the WOT-2026-023t freshness"
        " gate via --live-backlog"
    )
    assert "Freshness gate" in text


def test_freshness_head_sha_is_warn_never_block() -> None:
    """state_at_triage.motor != HEAD must be documented as WARN, never a
    block: the motor HEAD advances with every close of the batch itself, so an
    equality gate would self-block after the first ticket."""
    text = _read()
    assert "--head-sha" in text
    assert "self-block" in text


def test_dag_regeneration_is_forensic_seam1() -> None:
    """SEAM-1 (DoD-EXTRA): a DAG regenerated after a stop must bump
    generated_at and ship a NEW narrative .md -- the only forensic distinction
    between a real re-triage and the executor editing the DAG to unblock its
    own path. Mutation: drop the clause -> RED."""
    text = _read()
    assert "bump `generated_at`" in text
    assert "narrative" in text


# ---------------------------------------------------------------------------
# WOT-2026-023w (DoD d): the prompt cites the schema the ledger REALLY
# persists. Before 023w, LEDGER_FIELDS silently scrubbed every anti-loop
# field; a prompt citing an aspirational spelling would recreate the gap.
# ---------------------------------------------------------------------------


def test_ledger_cites_real_batch_retry_schema() -> None:
    """The anti-loop record is event=batch_retry with the allowlisted keys
    (ticket_id, subtipo_cem -- not ticket / subtipo_CEM). Mutation: revert the
    citation to the pre-023w spelling -> RED."""
    text = _read()
    assert "batch_retry" in text
    assert "ticket_id" in text
    assert "subtipo_cem" in text
    assert "LEDGER_FIELDS" in text


# ---------------------------------------------------------------------------
# WOT-2026-025p: the canonical-suite gate must carry --level all EXPLICITLY,
# in barrier 3 AND in PREDICATE row 5, and executor<->auditor must stay in
# PARITY on it. Split contract, measured: run_pytest_safe WITHOUT the flag
# runs the unit level only (integration deselected), and the executor
# declared green three times FOLLOWING ITS OWN PROMPT (F1/F2 of the sibling
# audit 20260716-1427) while the auditor's cond-5 did require --level all.
# ---------------------------------------------------------------------------

AUDITOR_PROMPT = PROMPTS / "audit_autonomous_ticket_batch.md"


def test_barrier3_suite_gate_carries_level_all() -> None:
    """Every barrier-3 bullet that enumerates the canonical suite must carry
    --level all. Mutation: drop --level all from the run_pytest_safe bullet
    in barrier 3 -> RED."""
    bullet_lines = [
        ln for ln in _barrier3_block().splitlines() if ln.lstrip().startswith("-")
    ]
    suite_bullets = [ln for ln in bullet_lines if "run_pytest_safe.py" in ln]
    assert suite_bullets, "barrier 3 must enumerate the canonical suite gate"
    assert all("--level all" in ln for ln in suite_bullets), (
        "barrier 3 must cite `run_pytest_safe.py --level all` explicitly "
        "(WOT-2026-025p): without the flag the wrapper runs the unit level "
        "and a green there is a formal false-green for a batch close"
    )


def _predicate_row(n: int) -> str:
    """The PREDICATE table row for condition `n` (single line starting
    '| n |'), so assertions are scoped to the table, not prose elsewhere."""
    rows = [ln for ln in _read().splitlines() if ln.strip().startswith(f"| {n} |")]
    assert len(rows) == 1, f"expected exactly one PREDICATE row for cond {n}"
    return rows[0]


def _predicate_row_command(n: int) -> str:
    """The `python .agent/agent_controller.py ...` COMMAND span of row `n`.

    WOT-2026-039a (floor-assertion fix caught by the MANAGER_REVIEW loop): each
    flag of row 8 appears TWICE -- once in the command and once in the prose
    that justifies it ("`--no-heal` is MANDATORY: ..."). A substring assertion
    over the whole row is therefore satisfied by the PROSE ALONE: dropping the
    flag from the real command left the suite GREEN (measured: 188 passed),
    contradicting the docstring's promise that the mutation goes RED. Scoping
    to the command span is what gives the assertion teeth.
    """
    row = _predicate_row(n)
    commands = re.findall(r"`(python [^`]+)`", row)
    assert commands, f"PREDICATE row {n} must carry a backticked command"
    # Select by IDENTITY, never by position (Codex refutation of the first fix):
    # `commands[0]` would let a decoy command earlier in the row satisfy the
    # flag assertions while the REAL agent_controller command loses them.
    # Anchored at the START of the command (Codex 2nd refutation): a substring
    # match would accept a decoy that merely CARRIES the string as an argument.
    controller = [
        c
        for c in commands
        if re.match(r"python [^ ]*agent_controller\.py --validate", c)
    ]
    assert len(controller) == 1, (
        f"PREDICATE row {n} must carry EXACTLY ONE "
        f"`agent_controller.py --validate` command (found {len(controller)}); "
        f"more than one makes the flag assertions ambiguous"
    )
    return controller[0]


def test_predicate_row8_mandates_no_heal_and_project_root() -> None:
    """PREDICATE row 8 (estado_operativo_valido) must pin BOTH guards.

    LOAD-BEARING (WOT-2026-039a). The condition exists because a close left the
    destino with a CLEAN tree and an INVALID operational state: cond-7 only
    reads `dirty==0`, so it passed straight through and only remote CI caught
    it. Two measured facts make the bare command unsafe:

    - WITHOUT `--no-heal`, `--validate` heals bus drift and WRITES the
      git-TRACKED `STATE.md` (agent_controller `_handle_validate` ->
      `sync_state_projection`, WOT-2026-024a). The check would DIRTY the
      destino and break cond-7 in the same run.
    - WITHOUT an explicit `--project-root`, pointing at the wrong repo returns
      GREEN, not RED (measured: the code-only motor also reports
      `total_errors: 0`; `is_motor_code_only()` gates only WRITE flags).
    - WITHOUT `--json` there is no JSON to parse, so the stated criterion
      ("`total_errors == 0` read from the REAL JSON") becomes unexecutable and
      the condition degrades into prose. Measured: dropping `--json` from the
      command left the whole suite GREEN before this assertion existed.

    Mutation: drop any of the three flags from row 8 -> RED.
    """
    row8 = _predicate_row(8)
    assert "estado_operativo_valido" in row8, (
        "PREDICATE row 8 must be the estado_operativo_valido condition"
    )
    # Scoped to the COMMAND span, never the whole row: the prose that justifies
    # each flag also names it, so a row-wide substring check is a floor
    # assertion (it survives dropping the flag from the real command).
    command8 = _predicate_row_command(8)
    assert "--no-heal" in command8, (
        "PREDICATE row 8's COMMAND must carry `--no-heal`: without it "
        "`--validate` writes the tracked STATE.md, dirtying the destino and "
        "breaking cond-7 in the same run. Naming it only in the prose does not "
        "count -- the executor copies the command, not the justification"
    )
    assert "--project-root" in command8, (
        "PREDICATE row 8's COMMAND must carry `--project-root <DESTINO_ROOT>`: "
        "pointed at the wrong repo this check returns GREEN, so the root is "
        "load-bearing and must live in the command itself"
    )
    assert "--json" in command8, (
        "PREDICATE row 8's COMMAND must carry `--json`: the criterion is read "
        "from the REAL JSON, and without the flag `--validate` prints prose, "
        "leaving `total_errors == 0` unparseable and the condition toothless"
    )
    # Scoped to the CRITERION clause, not the row: `total_errors` also appears
    # in the row's two justifying parentheticals (the wrong-repo measurement and
    # the exit-code clause), so a row-wide check is a floor assertion -- measured
    # GREEN with the criterion itself gutted, while a decoy occurrence survived.
    assert re.search(r"total_errors\s*==\s*0`?\s*read from the REAL JSON", row8), (
        "PREDICATE row 8 must state the CRITERION as `total_errors == 0` READ "
        "FROM THE REAL JSON. The bare token is a decoy: the row names "
        "total_errors three times (the criterion, the wrong-repo measurement, "
        "and the exit-code clause `0 if total_errors == 0`), so anything looser "
        "survives gutting the criterion itself -- measured GREEN"
    )


def test_executor_auditor_parity_on_cond8_guards() -> None:
    """PARITY (WOT-2026-039a): both prompts must pin cond-8's two guards.

    Reads BOTH files so the parity cannot silently diverge in either
    direction, mirroring the cond-5 parity test above. Mutation: drop
    `--no-heal` or `--project-root` from either side -> RED.
    """
    audit_text = (PROMPTS / "audit_autonomous_ticket_batch.md").read_text(
        encoding="utf-8"
    )
    assert "estado_operativo_valido" in audit_text, (
        "the auditor must reproduce cond-8; otherwise the executor declares a "
        "condition nobody re-derives"
    )
    # Both sides are scoped to their COMMAND, not to the file/row: `--no-heal`
    # and `--project-root` also occur in each prompt's justifying prose, so a
    # file-wide check cannot fail on a real parity divergence (floor
    # assertion caught by the MANAGER_REVIEW loop, WOT-2026-039a).
    # The auditor writes its command inside a fenced block, split across lines
    # with a `\` continuation, so the span is joined before asserting -- a
    # single-line scope would fail on the legitimate wrapped form.
    audit_lines = audit_text.splitlines()
    starts = [
        i
        for i, line in enumerate(audit_lines)
        if re.search(r"python [^ ]*agent_controller\.py --validate", line)
    ]
    assert len(starts) == 1, (
        "the auditor must spell out the cond-8 command EXACTLY ONCE (found "
        f"{len(starts)}); a decoy occurrence would make the flag assertions "
        "ambiguous, the same falsifiability Codex refuted on the executor side"
    )
    start = starts[0]
    span = [audit_lines[start]]
    while span[-1].rstrip().endswith("\\") and start + len(span) < len(audit_lines):
        span.append(audit_lines[start + len(span)])
    audit_command = " ".join(part.rstrip("\\ ").strip() for part in span)
    executor_command = _predicate_row_command(8)
    for flag in ("--no-heal", "--project-root", "--json"):
        assert flag in audit_command, (
            f"the auditor's cond-8 COMMAND must carry {flag}: the executor "
            f"already does, and a split contract between the two is the "
            f"false-green class this pair of prompts exists to prevent"
        )
        assert flag in executor_command, (
            f"the executor's PREDICATE row 8 COMMAND must carry {flag}"
        )


def test_predicate_row5_cites_level_all() -> None:
    """PREDICATE row 5 (suite_final_verde) must cite --level all explicitly,
    not 'canonical suite' prose. Mutation: drop --level all from row 5 ->
    RED."""
    row5 = _predicate_row(5)
    assert "--level all" in row5, (
        "PREDICATE row 5 must cite `run_pytest_safe.py --level all` "
        "(WOT-2026-025p): 'canonical suite' without the flag is the exact "
        "split contract that produced the F1 false-green"
    )


def test_executor_auditor_parity_on_level_all_cond5() -> None:
    """PARITY (WOT-2026-025p): the auditor's cond-5 requires --level all;
    the executor's row 5 must require it too. This test reads BOTH prompts,
    so the parity cannot silently diverge in either direction. Mutation:
    drop --level all from either file's cond-5 -> RED.

    WOT-2026-026i: the auditor side is anchored by the section HEADER
    (`_auditor_predicate_section()`), not the fragile `idx : idx+400` window
    on the FIRST occurrence of `suite_final_verde` (the same anti-pattern
    025u(b) removed for cond-3). cond-5 lives in the same `## 4. PREDICATE`
    section as cond-3, so the header-anchored helper scopes it robustly."""
    section4 = _auditor_predicate_section()
    assert "suite_final_verde" in section4, (
        "cond-5 (suite_final_verde) must live in the '## 4 PREDICATE' section"
    )
    assert "--level all" in section4, (
        "the auditor's cond-5 (suite_final_verde) must require --level all"
    )
    assert "--level all" in _predicate_row(5), (
        "the executor's PREDICATE row 5 must require --level all: the "
        "auditor already does, and a split contract between the two is the "
        "measured cause of the F1 false-green (sibling audit 20260716-1427)"
    )


def test_cond5_anchor_is_robust_to_prose_growth() -> None:
    """WOT-2026-026i MUTATION (mirror of cond-3's 025u(b) robustness proof):
    the OLD cond-5 anchor was `text.index("suite_final_verde")` + a fixed
    400-char window. `suite_final_verde` appears multiple times in the file
    (PREDICATE cond-5 AND the OUTPUT-template rows), so a first-occurrence +
    fixed-window anchor is fragile: if the PREDICATE prose grew so `--level all`
    sat past the 400-char window, the check would read the wrong region and
    pass on a split contract (parity false-green).

    Proof the section-anchor is not window-bound: it must still locate cond-5's
    `--level all` even when the PREDICATE section is padded FAR beyond 400 chars
    between the `suite_final_verde` token and its `--level all`. The old idx+400
    window would miss it; the header-anchored section does not.
    """
    text = AUDITOR_PROMPT.read_text(encoding="utf-8")
    assert text.count("suite_final_verde") >= 2, (
        "premise: the token is not unique -- a first-occurrence anchor is unsafe"
    )
    section4 = _auditor_predicate_section()
    # Pad the section between the token and its --level all with >400 chars,
    # inserted right AFTER the first token occurrence so the old window (which
    # starts AT that token) is pushed past `--level all`.
    padded_section = section4.replace(
        "suite_final_verde", "suite_final_verde" + (" (relleno)" * 60), 1
    )
    padded = text.replace(section4, padded_section, 1)

    # NEGATIVE assertion (mirror of cond-3): the OLD idx+400 window MISSES
    # --level all in the padded variant -- the concrete failure the anchor fixes.
    old_idx = padded.index("suite_final_verde")
    old_window = padded[old_idx : old_idx + 400]
    assert "--level all" not in old_window, (
        "the padded variant must push --level all outside the old 400-char "
        "window so the contrast is real (else the test proves nothing)"
    )

    # POSITIVE assertion: the header-anchored section STILL contains --level all.
    s = padded.index("## 4. El PREDICATE machine-checkable")
    m = re.search(r"\n##\s+(\d+)\.", padded[s + 1 :])
    while m and int(m.group(1)) <= 4:
        m = re.search(
            r"\n##\s+(\d+)\.", padded[s + 1 + m.end() :]
        )  # pragma: no cover - no 4.x today
    e = (s + 1 + m.start()) if m else len(padded)
    padded_section4 = padded[s:e]
    assert "--level all" in padded_section4, (
        "the header-anchored section still contains cond-5's --level all even "
        "when it sits >400 chars from the token -- the idx+400 window (asserted "
        "above) missed it"
    )


# ---------------------------------------------------------------------------
# WOT-2026-025q: the cond-3 accounting universe is the tickets of groups[].
# tickets[] entries that belong to NO group are triage context: never counted
# (neither closed nor lost), but ENUMERATED as excluded -- never silently
# omitted. Measured case (F3, sibling audit 20260716-1427): WOT-2026-020t sat
# in tickets[] of the consumed DAG belonging to no group and reached no
# terminal state; "every ticket of the DAG" was ambiguous about it.
# ---------------------------------------------------------------------------


def test_predicate_row3_universe_is_groups() -> None:
    """PREDICATE row 3 must anchor the accounting universe to the literal
    `groups[]` AND require visible enumeration of the excluded tickets[]
    entries. Mutation: drop either anchor from row 3 -> RED."""
    row3 = _predicate_row(3)
    assert "groups[]" in row3, (
        "PREDICATE row 3 must fix the accounting universe = tickets listed "
        "in groups[] (WOT-2026-025q): 'every ticket of the DAG' was "
        "ambiguous about tickets[] entries with no group (F3)"
    )
    assert "ENUMERATED" in row3, (
        "row 3 must require the excluded tickets[] entries to be ENUMERATED "
        "as context (in the DAG or the batch_run accounting note): a silent "
        "omission is the F3 silhouette legitimized"
    )


def _auditor_predicate_section() -> str:
    """The auditor's PREDICATE section (## 4 ... until the next TOP-LEVEL section
    heading ``## <n>.`` with n > 4), so cond-3 assertions are scoped to the
    machine-checkable PREDICATE, not a stray `contabilidad_completa` mention in
    the OUTPUT template later in the file. WOT-2026-025u(b): replaces the fragile
    `idx : idx+900` window, which (a) anchored on the FIRST occurrence of the
    token and (b) assumed cond-3's `groups[]` sat within 900 chars of it -- both
    break if the prose shifts. Header-anchored, like _barrier3_block.

    The delimiter matches the next ``## <n>.`` whose number is > 4 (Codex-FS:
    a hypothetical ``## 4.5`` subsection must NOT truncate the section early).
    """
    text = AUDITOR_PROMPT.read_text(encoding="utf-8")
    start = text.index("## 4. El PREDICATE machine-checkable")
    # Delimiter: the next TOP-LEVEL heading '## <n>.' with n > 4. Scanning for
    # n > 4 (not merely the next '## ') means a hypothetical '## 4.5' subsection
    # does NOT truncate the section early (Codex-FS).
    for m in re.finditer(r"\n##\s+(\d+)\.", text[start + 1 :]):
        if int(m.group(1)) > 4:
            return text[start : start + 1 + m.start()]
    return text[start:]


def test_executor_auditor_parity_on_cond3_universe() -> None:
    """PARITY (WOT-2026-025q): both prompts must anchor cond-3's universe to
    the literal `groups[]` (each in its own language). WOT-2026-025u(b): the
    auditor side is now anchored by the section HEADER, not idx+900.
    Mutation: drop the token from either file's cond-3 -> RED."""
    section4 = _auditor_predicate_section()
    # cond-3 lives in the PREDICATE section; its universe must be groups[].
    assert "contabilidad_completa" in section4, (
        "cond-3 (contabilidad_completa) must live in the '## 4 PREDICATE' section"
    )
    assert "groups[]" in section4, (
        "the auditor's cond-3 must fix the accounting universe = tickets of "
        "groups[]; tickets[] entries with no group are context, not accounting"
    )
    assert "groups[]" in _predicate_row(3), (
        "the executor's PREDICATE row 3 must fix the same groups[] universe: "
        "a split contract between executor and auditor on cond-3 recreates F3"
    )


def test_cond3_anchor_is_robust_to_multiple_token_occurrences() -> None:
    """WOT-2026-025u(b) MUTATION ENDURECIDA (Codex): the OLD anchor was
    `text.index("contabilidad_completa")` + a fixed 900-char window. That token
    appears 3x in the file (PREDICATE cond-3 AND the OUTPUT-template rows), so
    the first-occurrence + fixed-window anchor is fragile: if the PREDICATE
    prose grew past the window, or the occurrence order changed, the check would
    read the wrong region.

    Proof the section-anchor is not window-bound: it must still locate cond-3's
    `groups[]` even when the PREDICATE section is padded FAR beyond 900 chars
    between the `contabilidad_completa` token and its `groups[]`. The old
    idx+900 window would miss it; the header-anchored section does not.
    """
    text = AUDITOR_PROMPT.read_text(encoding="utf-8")
    assert text.count("contabilidad_completa") >= 2, (
        "premise: the token is not unique -- a first-occurrence anchor is unsafe"
    )
    section4 = _auditor_predicate_section()
    # Pad the section between the token and its groups[] with >900 chars.
    padded_section = section4.replace("groups[]", ("(relleno) " * 120) + "groups[]", 1)
    padded = text.replace(section4, padded_section, 1)

    # NEGATIVE assertion (Codex-FS): the OLD idx+900 window MISSES groups[] in the
    # padded variant -- this is the concrete failure the section-anchor fixes.
    old_idx = padded.index("contabilidad_completa")
    old_window = padded[old_idx : old_idx + 900]
    assert "groups[]" not in old_window, (
        "the padded variant must push groups[] outside the old 900-char window "
        "so the contrast is real (else the test proves nothing)"
    )

    # POSITIVE assertion: the header-anchored section STILL contains groups[].
    s = padded.index("## 4. El PREDICATE machine-checkable")
    m = re.search(r"\n##\s+(\d+)\.", padded[s + 1 :])
    while m and int(m.group(1)) <= 4:
        m = re.search(
            r"\n##\s+(\d+)\.", padded[s + 1 + m.end() :]
        )  # pragma: no cover - no 4.x today
    e = (s + 1 + m.start()) if m else len(padded)
    padded_section4 = padded[s:e]
    assert "groups[]" in padded_section4, (
        "the header-anchored section still contains cond-3's groups[] even when "
        "it sits >900 chars from the token -- the idx+900 window (asserted above) "
        "missed it"
    )


def test_predicate_section_survives_a_45_subsection() -> None:
    """WOT-2026-025u(b) (Codex-FS finding 2): a hypothetical `## 4.5` subsection
    between cond-3 and `## 5` must NOT truncate the extracted PREDICATE section.
    Inject a `## 4.5 ...` header right after cond-3's groups[] and assert the
    section still reaches it (a naive `next '## '` delimiter would cut early)."""
    text = AUDITOR_PROMPT.read_text(encoding="utf-8")
    section4 = _auditor_predicate_section()
    marker = "groups[]"
    injected = section4.replace(
        marker, marker + "\n\n## 4.5. Subseccion nueva\n\ncontenido.\n", 1
    )
    variant = text.replace(section4, injected, 1)
    # Re-extract with the SAME robust delimiter logic the helper uses.
    s = variant.index("## 4. El PREDICATE machine-checkable")
    end = None
    for mm in re.finditer(r"\n##\s+(\d+)\.", variant[s + 1 :]):
        if int(mm.group(1)) > 4:
            end = s + 1 + mm.start()
            break
    section4_variant = variant[s:end] if end else variant[s:]
    assert "## 4.5. Subseccion nueva" in section4_variant, (
        "the '## 4.5' subsection must remain INSIDE the extracted section, not "
        "act as its terminator (n>4 delimiter, not next-'## ')"
    )
    assert "groups[]" in section4_variant


# ---------------------------------------------------------------------------
# WOT-2026-026h: Paso 0 backend-accessibility gate. The prompt had NO
# pre-flight barrier over backend reachability before this ticket (grep for
# "check_agents_accessible" returned nothing); the mechanism already existed
# (scripts/check_agents_accessible.py::collect_accessibility, wired into
# scripts/preflight_codeonly_pipeline.py by WOT-2026-026e) but no prompt
# layer mandated it for the autonomous batch executor.
# ---------------------------------------------------------------------------


def test_prompt_wires_backend_accessibility_gate() -> None:
    """The prompt must reference the canonical Nivel 0 accessibility script
    and its binary --require criterion as a HARD-STOP before any ticket runs.

    Mutation: drop the Paso 0 section (or the --require reference) -> RED.
    """
    text = _read()
    assert "check_agents_accessible.py" in text, (
        "the prompt must invoke the canonical Nivel 0 accessibility script "
        "scripts/check_agents_accessible.py before executing any ticket"
    )
    assert "--require" in text, (
        "the prompt must wire the --require binary criterion: every REQUIRED "
        "profile must be ACCESIBLE or the batch hard-stops"
    )
    assert "HARD-STOP" in text and "Nivel 0" in text, (
        "the accessibility gate must be framed as a Nivel 0 HARD-STOP before "
        "any ticket runs, not an advisory warning"
    )


def test_backend_accessibility_gate_script_reference_is_real() -> None:
    """Seam guard: scripts/check_agents_accessible.py, cited by the Paso 0
    gate, must actually exist on disk (mirrors the existing dangling-script
    seam guard pattern for this prompt)."""
    assert (SCRIPTS / "check_agents_accessible.py").is_file(), (
        "the Paso 0 gate cites scripts/check_agents_accessible.py, which "
        "must exist on disk for the reference to be real"
    )


# --- WOT-2026-037a: ensemble governance loops wired into the 3 gov stages ---
# These tests EXECUTE the contract (verify the loop wiring + that every source
# prompt the loop table cites resolves on disk), not just grep for prose
# (lesson 026g: pinning prose is a norm, not a barrier).


def test_037a_governance_loops_section_exists() -> None:
    """The ensemble governance loops section is declared."""
    txt = _read()
    assert "Ensemble governance loops" in txt, (
        "WOT-2026-037a: the prompt must declare the ensemble governance "
        "loops section wiring the fan-out at the 3 governance stages"
    )


def test_037a_contract_audit_loop_is_1_9_2() -> None:
    """CONTRACT_AUDIT (pre-Builder) runs a 1->9->2 loop with audit_cf."""
    txt = _read()
    # the CONTRACT_AUDIT row must pair the 1->9->2 loop with audit_cf_ticket_contract
    assert re.search(
        r"CONTRACT_AUDIT.*1->9->2.*audit_cf_ticket_contract\.md",
        txt,
    ), "037a: CONTRACT_AUDIT must run 1->9->2 with audit_cf_ticket_contract.md"


def test_037a_manager_review_loop_is_1_9_2() -> None:
    """MANAGER_REVIEW (post-Builder) runs a 1->9->2 loop with manager_review."""
    txt = _read()
    assert re.search(
        r"MANAGER_REVIEW.*1->9->2.*manager_review\.md",
        txt,
    ), "037a: MANAGER_REVIEW must run 1->9->2 with manager_review.md"


def test_037a_close_has_phase2_challenge() -> None:
    """CLOSE = phase 1 (1->9->2) + phase 2 challenge, with the exact close
    chain Claude -> glm -> Codex and iterations until total green."""
    txt = _read()
    # phase 2 challenge fan-out and the exact close chain
    assert "challenge" in txt and "phase 2" in txt.lower(), (
        "037a: CLOSE must add a phase 2 challenge after phase 1's 1->9->2"
    )
    assert re.search(r"Claude\s*->\s*glm\s*->\s*Codex", txt), (
        "037a: CLOSE phase 2 must close with Claude -> glm -> Codex (final)"
    )
    assert "UNTIL TOTAL GREEN" in txt or "until every gate is" in txt, (
        "037a: CLOSE must iterate until total green after the verdict"
    )


def test_037a_loops_are_parallel_never_chain_to_verify() -> None:
    """The governance loops verify by independence (mode=parallel)."""
    txt = _read()
    assert "mode=parallel" in txt and "NEVER" in txt and "chain" in txt, (
        "037a: governance loops must use mode=parallel (independence is the "
        "guarantee); chain must be forbidden for verification"
    )


def test_037a_nine_lens_shape_is_exact() -> None:
    """The '9' is (4 nan comun + 4 nan dif) + 1 Claude reader -- exact."""
    txt = _read()
    assert re.search(r"4 nan comun.*4 nan dif.*Claude reader", txt, re.DOTALL), (
        "037a: the 9 fan-out must be (4 nan comun + 4 nan dif) + 1 Claude reader"
    )


def test_037a_synthesis_is_claude_claude_codex() -> None:
    """The '2' synthesis is Claude -> Claude -> Codex -- exact."""
    txt = _read()
    assert re.search(r"Claude\s*->\s*Claude\s*->\s*Codex", txt), (
        "037a: the 2 synthesis must be Claude -> Claude -> Codex"
    )


def test_037a_close_loop_source_prompts_exist_on_disk() -> None:
    """Seam guard (EXECUTES, not greps): every source prompt the CLOSE loop
    cites must resolve on disk -- a dangling reference would silently break
    the close loop (mutation: rename any of them -> RED)."""
    close_sources = [
        "orchestrator_session_close_full_audit.md",
        "memory_upload.md",
        "audit_autonomous_ticket_batch.md",
    ]
    txt = _read()
    for src in close_sources:
        assert src in txt, f"037a: CLOSE loop must cite {src}"
        assert (PROMPTS / src).is_file(), (
            f"037a seam guard: CLOSE loop cites prompts/{src} but it does "
            f"not exist on disk (dangling reference breaks the close loop)"
        )


def test_037a_contract_and_review_source_prompts_exist_on_disk() -> None:
    """Seam guard: the per-ticket loop source prompts resolve on disk."""
    for src in ("audit_cf_ticket_contract.md", "manager_review.md"):
        assert (PROMPTS / src).is_file(), (
            f"037a seam guard: governance loop cites prompts/{src} but it "
            f"does not exist on disk"
        )


# ---------------------------------------------------------------------------
# WOT-2026-023u: both prompts must break the depends_on_groups ambiguity --
# it models REAL dependency (consumes artifact/state or shares a serialized
# surface), never mere order preference. The executor's schema legend and the
# triage's Phase 2 must SAY this, so a re-triage cannot silently chain groups
# by preference again (inaugural incident 2026-07-13: G1->G2->G3 by preference
# would have frozen independent G2/G3 when G1 stopped).
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = PROMPTS / "backlog_triage.md"


def test_023u_executor_depends_on_is_real_dependency_not_order() -> None:
    """The executor's schema legend for `depends_on_groups` must say it is a
    REAL dependency, not 'execution order'. Mutation: revert l.473 back to
    '(execution order)' -> RED."""
    text = _read()
    assert "depends_on_groups" in text
    assert "real dependency" in text, (
        "the executor must legend depends_on_groups as a REAL dependency "
        "(consumes artifact/state or shares a serialized surface), not "
        "'execution order' (WOT-2026-023u): the ambiguity chained G1->G2->G3 "
        "by preference in the inaugural run"
    )
    assert (
        "execution-order preference" in text or "execution order preference" in text
    ), (
        "the executor must NAME the excluded meaning (order preference) so the "
        "contrast is explicit, not just assert the included one"
    )


def test_023u_triage_phase2_separates_dependency_from_preference() -> None:
    """backlog_triage Phase 2 must define depends_on_groups = real dependency
    and forbid order-preference edges (MUST NOT). Mutation: drop the MUST NOT
    clause -> RED."""
    text = TRIAGE_PROMPT.read_text(encoding="utf-8")
    assert "depends_on_groups" in text
    assert "dependencia" in text.lower() and "preferencia de orden" in text.lower(), (
        "Phase 2 must contrast REAL dependency vs order preference (WOT-2026-023u)"
    )
    assert "NO DEBE" in text, (
        "Phase 2 must forbid (NO DEBE / MUST NOT) putting an order-preference "
        "edge into depends_on_groups: a false edge turns a local stop into a "
        "global cascade (inaugural incident 2026-07-13)"
    )
    assert TRIAGE_PROMPT.is_file()
