# Orchestrator Autonomous Ticket Batch (Executor)

> Executor that consumes the DAG produced by `/backlog-triage`
> (`prompts/backlog_triage.md`, schema `autonomous-batch-dag/v1`) and closes
> the maximum number of tickets WITH GUARANTEES, stopping clean instead of
> lowering barriers. Frozen design:
> `design_autonomous_ticket_batch.md` (workspace planning), sections 1, 2, 4,
> 5, 6, 7, 8, 9, 10, 11, 12, 15 are load-bearing for this prompt.

contract_id: cid-orchestrator-autonomous-ticket-batch-v1
Skill canonica: skills/orchestrate-autonomous-ticket-batch/SKILL.md
source_of_truth: this prompt. The skill is an operational wrapper; if they
diverge, this prompt (`prompts/orchestrator_autonomous_ticket_batch.md`)
prevails.

**Its audit is a SIBLING, not itself:** `prompts/audit_autonomous_ticket_batch.md`
verifies this executor's runs with fresh-context isolation (CEM: a checker
cannot audit its own output). This prompt never claims its own runs are
audited; it only produces the artifacts the auditor consumes.

---

## Scope: Tier 0 and Tier 1 ONLY

This prompt implements:

- **Tier 0**: hard-stop + `GROUP_STOP_REPORT` + re-triage between tickets.
- **Tier 1**: DAG of groups: if a group falls, freeze ONLY its subgraph and
  CONTINUE with independent groups.

**Tier 2 (recovery per owner-stage + confidence checkpoints) and Tier 3
(advanced rollback/repair) are explicitly NOT IMPLEMENTED here.** Tier 2 may
be described as future design work once there is at least one real run of
Tier 0-1; Tier 3 is not even designed yet. Do not build machinery for either
tier under this contract_id.

---

## Frontera y herencia (does NOT reimplement anything)

This executor decides WHAT group runs next and WHEN to stop. It does not
reimplement tickets, does not rewrite the per-ticket pipeline, does not
create a parallel authority, and does **not duplicate the close logic of
either deployment mode** (below). The per-ticket implantation still lives in
`prompts/orchestrator_pipeline.md` (destino mode) or
`prompts/orchestrator_pipeline_codeonly.md` (motor code-only mode); contract
formation in `prompts/contract_formation_pipeline.md`; the adversarial
contract audit in `prompts/audit_cf_ticket_contract.md`; the intra-ticket
Review mechanic in `prompts/manager_review.md`; the CEM v0 auditor philosophy
in `prompts/audit_agent_output.md`.

```
/backlog-triage           (READ-ONLY)   -> produces the DAG-JSON. Still the planner.
/autonomous-ticket-batch  (EXECUTOR)    -> consumes the DAG-JSON. THIS prompt.
   |-- detects MODE (is_motor_code_only) and delegates to the matching pipeline
   |-- per ticket:  orchestrator_launch_builder.md  (Builder)
   |-- verification: manager_review.md              (Review 1/2)
   |-- contract:     audit_cf_ticket_contract.md    (pre-Builder)
   |-- chain:        audit_pipeline.md / audit_pipeline_codeonly.md (per mode)
   `-- auditor:      audit_agent_output.md          (CEM v0, evidence over narrative)
```

Acyclic graph (verified by design): `triage -> executor -> {builder, reviewer,
auditor} -> executor`. The return to the executor is a CONTROL return (it
receives a verdict), never an INVOCATION: builder/reviewer/auditor never
invoke the executor. No cycle.

---

## PORTABILITY (root requirement) -- this executor is of the MOTOR, not of any single dogfooding instance

This is a portable tool: it must be able to run against **any `repo_destino`**,
not only a code-only dogfooding instance. This prompt therefore:

- **DETECTS the deployment mode, never assumes it.**
- **Contains no absolute paths and no name of any specific dogfooding
  instance.** Rewrite any concrete path you need for illustration in terms
  of roles (`<MOTOR_ROOT>`, `<DESTINO_ROOT>`), the same convention used by
  `prompts/orchestrator_destination_batch.md`. A prompt edit that reintroduces
  a literal machine path or the name of one specific workspace instance is a
  portability defect, not a detail: `prompts/audit_autonomous_ticket_batch.md`
  and its contract tests treat it as a hard failure.

### Two deployment MODES (the executor detects, never assumes)

Canonical detection: **`is_motor_code_only()`**, imported as
`from runtime.project_root import is_motor_code_only`. The executor routes by
mode and **delegates**; it duplicates the close logic of neither mode.

| | **MODE DESTINO** (general case, portable) | **MODE MOTOR CODE-ONLY** (dogfooding) |
|---|---|---|
| Trigger | `repo_destino` with a live bus | `is_motor_code_only() == True` |
| Per-ticket pipeline | `prompts/orchestrator_pipeline.md` (canonical) | `prompts/orchestrator_pipeline_codeonly.md` |
| Ticket close | **via BUS**: `--bootstrap-ticket` -> `--mark-ready` -> `--manager-approve` | **commit-directo** (bus is blocked) |
| Chain meta-audit | `prompts/audit_pipeline.md` | `prompts/audit_pipeline_codeonly.md` |
| Backlog | `<DESTINO_ROOT>/.agent/collaboration/backlog.md` | the workspace of the dogfooding instance (illustrative aside only -- no literal path here) |
| Session close | `--session-close` | N/A (blocked) |

Neither branch is optional: a run that only wires one mode is a portability
regression (see the mode-routing contract tests in
`tests/unit/test_autonomous_batch_prompt_contract.py`, which fail
independently per branch -- lesson 021u, branch isolation).

### Topology RESOLVED, never assumed

- Active root: `AGENT_PROJECT_ROOT` / `--project-root`.
- Motor<->destino link: **`resolve_motor_link(project_root)`**, imported as
  `from scripts.destination_context import resolve_motor_link`.
- The triage is already portable (`prompts/backlog_triage.md`: in a generic
  `repo_destino` the backlog lives in the destino itself).
- Do NOT hardcode "N repos" in any report or checkpoint: enumerate them from
  the resolved topology.

### Hard portability rules

- **The executor NEVER writes backlog, reports, follow-ups, or ledger into
  `repo_motor`.** Everything goes to the **destino-rol** (the `repo_destino`;
  in a code-only dogfooding run, its workspace). The motor stays agnostic.
- The **learning ledger** uses `init_session_scratch.py --project-root
  <destino-rol>`, which is already portable by design (`--project-root` is
  MANDATORY; `repo_role` = motor/no_motor/unknown).
- Any machine-specific path or dogfooding-instance name inside this prompt is
  a portability defect, not a detail.

---

## Authority (design section 4): the executor NEVER reclassifies

`class` and `autonomy_mode` are assigned by the **TRIAGE**
(`prompts/backlog_triage.md`), never by this executor. The executor consumes
those fields as given. **Reclassifying a group or ticket to dodge a gate
(e.g. downgrading `hard-stop-with-recovery` to `autonomous`, or `S` to `M`,
to avoid a stricter `common_gate`) is, by definition, `falso_verde`** under
`prompts/audit_agent_output.md`'s CEM contract. If the executor believes a
classification is wrong, it stops and returns the group to the triage for
re-classification; it never overrides the field itself.

---

## State machine and fault routing to the OWNER-STAGE (design section 6)

```
TRIAGE -> CONTRACT_FORMATION -> CONTRACT_AUDIT -> BOOTSTRAP_RUNTIME
       -> BUILDER -> BUILDER_SELF_CHECK -> MANAGER_REVIEW -> CHAIN_AUDIT -> CLOSE
```

Each fault returns to the stage that OWNS the problem, never "breaks" at the
symptom:

| Fault | Owner-stage (return point) |
|---|---|
| unfrozen contract / false premise | `CONTRACT_FORMATION` (+ `audit_cf_ticket_contract.md`) |
| a Forbidden Surface is required | `CONTRACT_FORMATION` (widen the contract or split the ticket; **never** override) |
| `validate` has unclassified errors/warnings | `BOOTSTRAP_RUNTIME` (repair with the canonical tool) |
| wrong topology | `BOOTSTRAP_RUNTIME` (do not touch code until `check_worktree_topology` is OK) |
| focal tests fail | `BUILDER` (if the fix fits the contract); if it reveals a false premise -> `CONTRACT_FORMATION` |
| **mutation without teeth** | `TEST_DESIGN` (rewrite the barrier; **never** close) |
| bus/projection drift | `RUNTIME_RECONCILE` (canonical tool; never hand-edit the bus) |
| git dirty out of scope | `SCOPE_GIT_CHECKPOINT` |

**No identifiable owner-stage -> HARD STOP.** Do not improvise the return point.

---

## Recovery points (Tier 1 scope) and the anti-loop rule

A retry that repeats the same approach is noise. Value comes from returning
to a trusted state and re-approaching with a different, failure-informed
approach.

- **Learning ledger (append-only)**: each failed attempt writes an
  `event=batch_retry` record to the session's `manifest.jsonl`
  (`.agent/runtime/session/<id>/`, wired by `scripts/init_session_scratch.py
  add`). REAL persisted schema (WOT-2026-023w: these keys are allowlisted in
  `LEDGER_FIELDS`; any other key is silently scrubbed, so cite THESE, not an
  aspirational spelling): `{ticket_id, stage, gate_fallante, subtipo_cem,
  evidencia, enfoque_intentado, refutacion}`. `enfoque_intentado` is
  MANDATORY (the anti-loop discriminator); `ticket` maps to `ticket_id` and
  `subtipo_CEM` to `subtipo_cem`.
- **Retry rule**: a new attempt MUST declare an `enfoque_intentado` DIFFERENT
  from every one already recorded for that `(ticket, gate)`. A retry with the
  same approach does not execute: that is the operational definition of an
  infinite loop.
- **Anti-loop (operational definition)**: not by state hash (it changes with
  whitespace). Stop if, after a repair attempt, all three coincide:
  `gate_fallante` + `subtipo_CEM` + `archivo`. That is: the same failure with
  no new evidence of progress.

Tier 2 (confidence checkpoints, recovery-per-owner-stage machinery beyond
this) is out of scope for this prompt; see the "Scope" section above.

---

## HARD-STOP causes (never recovery, design section 8)

These always go to a stop + follow-up. Putting them in a recovery loop
fabricates false-greens:

- `suite_roja_heredada` (a red suite inherited from before this run is
  classified and blocked, never "recovered")
- `flaky` (reproducible only sometimes)
- `falso_verde` detected by an auditor
- `bus_drift` **without a canonical tool** to fix it
- `scope_dirty_no_atribuible` (dirty git that cannot be attributed)
- `estado_canonico_dividido` (measured **against the bus**, not against
  STATE/TURN projections)
- **owner-stage not identifiable**
- **same error class after N attempts** (anti-loop rule above)
- **recovery without proof/mutation** (a repair that is not demonstrated
  does not count)
- **non-restorable git state**

### The recovery loop can NEVER

Touch Forbidden Surfaces; widen scope; change the DoD; reclassify the ticket
to dodge a gate; continue with warnings "because they look inherited"
without evidence.

---

## Containment rule (design section 10)

If a ticket fails and does not recover, ONLY its subgraph freezes:

- the ticket itself;
- its direct dependents (`blocks_groups`);
- groups sharing an affected `shared_surfaces`.

**The batch continues with the independent groups.** A local failure never
becomes global chaos.

---

## `GROUP_STOP_REPORT` (mandatory on every stop, design section 9)

```json
{
  "group": "G-EXAMPLE", "ticket": "WOT-2026-XXXa", "state": "BLOCKED_GROUP",
  "stage": "MANAGER_REVIEW",
  "cause_type": "CONTRACT_GAP|TEST_FAIL|TOPOLOGY|SCOPE|SUITE_RED|BUS_DRIFT|FALSE_GREEN|UNCLASSIFIED",
  "evidence_level": "verified|inferred|unverified",
  "auditor_confidence": "low|medium|high",
  "evidence": ["<command + real output>"],
  "recovery_attempts": [{"enfoque": "...", "refutacion": "..."}],
  "repos": "<enumerated from the resolved topology, never hardcoded>",
  "fresh_sha_verified_at": "<iso>", "dirty_files_count": 0,
  "last_bus_event": "<real event from events.jsonl>",
  "last_confidence_checkpoint": "<sha>",
  "blocked_tickets": ["..."], "independent_groups_available": ["..."],
  "next_recommended_group": "G-EXAMPLE-2"
}
```

`evidence_level` and `auditor_confidence` are **separate fields**: confidence
never substitutes for evidence (a confident opinion without an artifact is
still `unverified`).

---

## The 7 non-negotiable per-ticket barriers (design section 11)

The executor MUST run these for every ticket it processes; each one caught a
real false-green in the evidence that informed this design:

1. **Live premise with an EXECUTED PROBE** (never a read). A premise "verified"
   by reading only is not verified.
2. **Adversarial plan-audit of the contract BEFORE the Builder.**
3. **Gates run by the orchestrator, from a CLOSED enumerated list** (never the
   Builder's self-report, and never "ran ruff and moved on"). The project gate
   is MORE than one command; a partial run is `falso_verde` (WOT-2026-024b,
   2026-07-14: the executor ran `ruff check` green, declared "gates green", and
   shipped -- but `ruff format --check` was RED, caught only by Review 2, and it
   would have broken CI and prepush). The closed, verifiable list, ALL required
   GREEN before the per-ticket commit:
   - `ruff check .`
   - `ruff format --check .`  -- a SEPARATE gate from `ruff check`; this is the
     one that leaked. Running only `ruff check` is NOT running the gates.
   - `python scripts/run_pytest_safe.py --level all`  -- the flag is part of
     the gate (WOT-2026-025p): WITHOUT `--level all` the wrapper runs the
     unit level only (integration tests DESELECTED), and the executor once
     declared green three times following this prompt to the letter -- a
     formal false-green caught only by the sibling audit. Read "N passed"
     from the real output, never the wrapper's exit code (barrier:
     WOT-2026-021m), and expect 0 deselected.
   - `python scripts/pip_audit_project.py`  -- CONDITIONAL: run iff the ticket's
     Files Likely Touched include a dependency manifest (`pyproject.toml`,
     `uv.lock`, `requirements*.txt`); otherwise emit an AUDITABLE skip, never a
     silent one.
   Where a `work_plan.md` exists, `scripts/run_gates_dispatch.py` runs this exact
   set by `deliverable_type` and returns a single verdict; in code-only batch
   (no work_plan) run the enumerated list above explicitly. Omitting any gate is
   `falso_verde`.
4. **Mutation-to-prove with teeth**, isolating the branch (lesson 021u): the
   mutation fixture must force the state where the branch under test is the
   ONLY thing deciding the verdict.
5. **Canonical suite POST-commit** with `tested_sha == HEAD`. A suite run
   PRE-commit is a contract false-green.
6. **Landing guard that SEES the row**: `ERROR=0` is not the same as audited;
   verify the guard's counter actually rose for this ticket's row.
7. **Never read `$?` after a pipe.** Use `subprocess` + `returncode`, or
   `PIPESTATUS`, for any git/exit-code check.

---

## Outputs (design section 12)

1. `batch_run_<ts>.json` -- per ticket: final state, checkpoint, evidence.
   It MUST carry the `PREDICATE` block declared below.
2. `GROUP_STOP_REPORT` per stop.
3. Learning-ledger records in the session's `manifest.jsonl` (append-only).
4. Final chain meta-audit (`audit_pipeline.md` or `audit_pipeline_codeonly.md`
   per mode) -- a safety net, **not the main guarantee**. The guarantee is
   the intermediate barriers above.

All of these are written to the **destino-rol**, never to `repo_motor`
(portability rule above).

### Blocking close step (WOT-2026-023v): DONE requires the outputs ON DISK

In the inaugural run the executor OMITTED `batch_run_<ts>.json` (it was written
retrospectively, a day later) and condition 6 was self-evaluated during the
run -- and nothing detected either. The executor's own outputs get the same
discipline as barrier 3: verified by command, never by memory ("guard que no
ve la fila").

The batch may NOT be declared `DONE` until ALL of:

1. `batch_run_<ts>.json` EXISTS on disk in the destino-rol reports dir, with
   its `PREDICATE` block -- verified by READING the actual file back (listing
   or parse command), not from the executor's recollection of writing it.
2. The sibling audit (`prompts/audit_autonomous_ticket_batch.md`) has been
   LAUNCHED in fresh context over that file. The sibling's input contract is
   fail-closed: without `batch_run_<ts>.json` it declares the run not
   auditable, so a batch that skipped the file can never reach `DONE` -- that
   is the mechanical barrier, not the executor's discipline.
3. Condition 6 (`auditor_emitido`) is DUAL-CONTRACT by design (precision P5):
   the executor records it as `PENDING` in `batch_run_<ts>.json` -- the
   executor CANNOT self-certify it -- and ONLY the sibling audit resolves it
   to pass. A `batch_run` with condition 6 self-marked as pass by the executor
   is self-certification: `falso_verde`.

---

## The PREDICATE: declare it BEFORE running, emit it in `batch_run_<ts>.json`

The batch declares a machine-checkable predicate BEFORE it runs, and the
isolated auditor (`prompts/audit_autonomous_ticket_batch.md`) evaluates it
**command by command, on real exit codes, not on narrative**. A run may be
declared `DONE` only if ALL 7 conditions hold:

| # | Condition | How it is checked |
|---|---|---|
| 1 | `schema_valido` | the DAG-JSON validates against `autonomous-batch-dag/v1` (`scripts/validate_batch_dag.py`, exit 0) |
| 2 | `dag_aciclico` | the same validator reports no cycle (exit 0) |
| 3 | `contabilidad_completa` | every ticket of the DAG ends in EXACTLY ONE state: closed, frozen-with-`GROUP_STOP_REPORT`, or not-reached-by-budget. No ticket is lost |
| 4 | `cierres_auditables` | per closed ticket, an archived row with a `commit:` cell AND the `audited` counter of `check_backlog_commits_landed` WENT UP; final `ERROR=0` |
| 5 | `suite_final_verde` | `python scripts/run_pytest_safe.py --level all` post-last-commit with `tested_sha == HEAD`, read from the REAL output ("N passed / N failed"), NEVER the wrapper's exit code (WOT-2026-025p: without `--level all` the run is unit-only and its green is a formal false-green) |
| 6 | `auditor_emitido` | the isolated auditor's report exists, verdict != `NO ACEPTAR TODAVIA`. DUAL CONTRACT (P5, WOT-2026-023v): the executor emits this row as `PENDING` -- it cannot self-certify it; only the sibling audit resolves it to pass |
| 7 | `arboles_limpios` | dirty=0 across the repos ENUMERATED from the resolved topology (never a hardcoded count) |

Conditions 4 and 5 encode real false-greens: `ERROR=0` is **not** the same as
audited (the landing guard used to SKIP rows lacking a `commit:` cell), and a
suite run PRE-commit reports the PARENT's `tested_sha`.

Emit it as a `PREDICATE` block inside `batch_run_<ts>.json`, one entry per
condition -> command -> real exit/value.

---

## What the batch consumes from the DAG (`autonomous-batch-dag/v1`)

The DAG is produced by `/backlog-triage` and validated with
`scripts/validate_batch_dag.py` BEFORE the batch executes anything. The
executor reads, and never rewrites:

- per group: `id`, `tickets`, `depends_on_groups` (execution order),
  `blocks_groups` and `shared_surfaces` (containment, see the freeze rule),
  `class` and `autonomy_mode` (**assigned by the triage; the executor NEVER
  reclassifies**), `common_gate`, `recovery_owner_stage`,
  `max_recovery_attempts`.
- `stop_policy`: `hard_stop_causes`, `recoverable_causes`,
  `max_unclassified_stops`.
- `budget`: `max_tickets_closed`, `max_group_recoveries`. When the budget is
  exhausted, remaining tickets end as `not-reached-by-budget` -- an explicit
  state in the accounting of condition 3, never a silent drop.

---

## Validate the DAG before executing it

Before consuming any DAG produced by `/backlog-triage`, run:

```
python <MOTOR_ROOT>/scripts/validate_batch_dag.py \
    <destino>/orchestrator_pipeline/reports/backlog_triage_output.json \
    --live-backlog <destino>/.agent/collaboration/backlog.md \
    --head-sha <HEAD actual del motor>
```

Require exit 0. A DAG that does not validate is not a valid input: return it
to the triage for correction; do not patch around it in the executor.

### Freshness gate (WOT-2026-023t): a valid-but-DEAD DAG must not run

Schema + acyclicity are NOT enough: the inaugural run consumed a DAG whose
`recommended_start` ticket was already closed and archived, and only a human
caught it -- the executor runs AUTONOMOUS. Freshness is SEMANTIC and runs when
the batch STARTS:

- `--live-backlog` requires every ticket of `groups` to still be a `pending`
  row (cell-based, never substring) in the live queue; a DAG citing an
  archived/completed/absent ticket is DEAD -> exit != 0, return to re-triage.
- `state_at_triage.motor != HEAD` is only a WARN (`--head-sha`), NEVER a
  block: the motor HEAD advances with every close of the batch itself, so an
  equality gate would self-block after the first ticket. Between tickets,
  Tier 0's re-triage already covers staleness.
- **Regeneration is forensic (SEAM-1)**: every DAG regenerated after a stop
  MUST bump `generated_at` and ship a NEW narrative `.md` alongside it. That
  pair is the only forensic way to distinguish a real re-triage from the
  executor editing the DAG to unblock its own path (the inaugural DAG kept
  its predecessor's `generated_at`).

---

## Auditing this executor

This prompt's audit lives in `prompts/audit_autonomous_ticket_batch.md`
(sibling ticket). **The executor cannot audit itself** -- fresh-context
isolation is mandatory, the same pattern as
`prompts/audit_goal_completion.md`'s "checker isolated from the
orchestrator-executor". Any claim that a batch run is verified without that
sibling audit having run is self-certification, and CEM prohibits it.

---

## Que NO hacer

- Do NOT implement Tier 2 or Tier 3 under this contract_id.
- Do NOT reclassify `class`/`autonomy_mode` for any group or ticket.
- Do NOT write backlog/reports/ledger into `repo_motor`.
- Do NOT assume the dogfooding topology; resolve it via
  `is_motor_code_only()` and `resolve_motor_link()`.
- Do NOT duplicate the close logic of either mode; delegate.
- Do NOT execute `REQUIERE_HUMANO` or `DISENO_PRIMERO` tickets. Ever.
- Do NOT treat the final chain meta-audit as a substitute for the
  intermediate per-ticket barriers.
- Do NOT read `$?` after a pipe for any git/exit-code decision.
