#!/usr/bin/env python3
"""Guard: the repo_destino's dirty tree must be EXACTLY the expected operational
delta of its deployment mode (WOT-2026-040a).

Before (Pre-condiciones):
    - The batch PREDICATE v2 (`prompts/orchestrator_autonomous_ticket_batch.md`,
      mirrored by `prompts/audit_autonomous_ticket_batch.md`) splits the old
      single observable `arboles_limpios` into TWO: `repos_codigo_limpios` (the
      code repos are clean) and `estado_operativo_destino_atribuible` (the
      `repo_destino`'s dirty IS the expected operational transition). This script
      is the CONTENT validator of the SECOND one.
    - A `delta` document (schema `expected-operational-delta/v1`) describes what
      the batch observed as dirty: the changed paths, the tickets that left the
      live queue, the rows that entered the archive with their terminal state
      and `commit:<sha>`, the `landed` fact per commit, and the count of hunks
      beyond the expected transition. The delta is produced OUTSIDE this script:
      the changed paths from `git status --porcelain`, the row facts from a diff
      of the two tracked backlog files, and each `landed` fact from
      `scripts/check_backlog_commits_landed.py` (the authority on landing).

During (Proceso y Recursos):
    - Reads the delta JSON (BOM-tolerant: `utf-8-sig`).
    - Applies the mode's EXACT expected transition:
        * code-only: the close's backlog transition -- the closed ticket(s) leave
          the live queue (`backlog.md`) and enter `_archive/backlog_done.md` with
          a terminal state and a LANDED `commit:<sha>`; zero extra hunks; no third
          file dirty.
        * destino: the live ticket-cycle projections (`STATE.md`, `TURN.md`,
          `work_plan.md`, `execution_log.md`) plus the auditor's mandatory
          artifacts; zero extra hunks; no third file dirty.
    - No markdown parsing and no git invocation: it validates the CONTENT facts
      the caller extracted (ticket IDs, states, commits, hunk counts). A full
      markdown/git parser is an explicit NON-GOAL of this ticket.

After (Post-condiciones y Errores):
    - exit 0 = the delta IS exactly the expected operational transition for the
      mode (a `dirty` repo_destino is LEGITIMATE, not a blocker).
    - exit 1 = a content finding (third foreign file, extra mutation, ticket
      removed != archived, non-terminal state, missing/unlanded `commit:<sha>`,
      a code-only delta applied outside code-only, or a mode mismatch).
    - exit 2 = usage/parse error (unreadable delta, wrong shape).
    - Never mutates anything (read-only).

Contrato de invocacion (PREDICATE v2, cond 8):

    python <MOTOR_ROOT>/scripts/check_expected_operational_delta.py \
        --mode <code-only|destino> --delta <delta.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple


SCHEMA = "expected-operational-delta/v1"

EXIT_OK = 0
EXIT_VERDICT = 1
EXIT_USAGE = 2

CODE_ONLY_MODE = "code-only"
DESTINO_MODE = "destino"
MODES = (CODE_ONLY_MODE, DESTINO_MODE)

# Terminal states a row may carry when it MOVES to the archive (mirrors barrier 8
# of the executor prompt). A row archived while still `pending` is pending work
# filed as history -- the silent reverse the barrier forbids.
TERMINAL_STATES = frozenset(
    {
        "completed",
        "done",
        "closed",
        "absorbed",
        "superseded",
        "blocked-final",
        "not-pursued",
    }
)

# code-only: the close's backlog transition writes EXACTLY these two tracked
# files, relative to the repo_destino root (posix separators).
CODE_ONLY_LIVE_QUEUE = ".agent/collaboration/backlog.md"
CODE_ONLY_ARCHIVE = ".agent/collaboration/_archive/backlog_done.md"
CODE_ONLY_WRITE_SURFACE = (CODE_ONLY_LIVE_QUEUE, CODE_ONLY_ARCHIVE)

# destino: the live ticket-cycle projections the bus writes while a ticket is
# IN_PROGRESS, plus the auditor's MANDATORY artifacts. Those two families are the
# legitimate dirty of a destino-mode flight -- measured 2026-09-13: of 16 dirty
# entries, the 4 projections + the auditor's own 2 artifacts are legitimate.
DESTINO_PROJECTIONS = (
    ".agent/collaboration/STATE.md",
    ".agent/collaboration/TURN.md",
    ".agent/collaboration/work_plan.md",
    ".agent/collaboration/execution_log.md",
)
AUDITOR_ARTIFACT_PREFIX = "orchestrator_pipeline/reports/audit_autonomous_batch_"

# A Reactivation cell of the form `commit:<sha>` (7..40 hex). The `commits:<sha...>`
# plural form is deliberately out of scope (NON-GOAL): one row, one landed commit.
COMMIT_CELL = re.compile(r"^commit:([0-9a-fA-F]{7,40})$")


class Finding(NamedTuple):
    """A single content finding against the expected operational delta."""

    code: str
    detail: str


def _norm(path: Any) -> str:
    """Normalize a delta path to posix-relative form for set comparison."""
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _is_auditor_artifact(path: str) -> bool:
    """True iff the path is one of the auditor's mandatory report artifacts."""
    return path.startswith(AUDITOR_ARTIFACT_PREFIX) and path.endswith((".md", ".json"))


def _archive_row_findings(row: dict[str, Any]) -> list[Finding]:
    """Content findings for ONE row that entered the archive."""
    ticket = str(row.get("ticket"))
    findings: list[Finding] = []
    state = str(row.get("state", "")).lower()
    if state not in TERMINAL_STATES:
        findings.append(
            Finding(
                "non_terminal_state",
                f"archived row {ticket!r} carries state {state!r}, not a "
                f"terminal state {sorted(TERMINAL_STATES)}",
            )
        )
    reactivation = str(row.get("reactivation", ""))
    match = COMMIT_CELL.match(reactivation)
    if not match:
        findings.append(
            Finding(
                "missing_commit",
                f"archived row {ticket!r} carries reactivation {reactivation!r}, "
                f"not a `commit:<sha>` cell",
            )
        )
    elif not bool(row.get("landed")):
        findings.append(
            Finding(
                "not_landed",
                f"archived row {ticket!r} cites commit:{match.group(1)} but it "
                f"did NOT land (check_backlog_commits_landed.py)",
            )
        )
    return findings


def _transition_findings(removed: list, added: list) -> list[Finding]:
    """Findings about the backlog row move (ticket correspondence + rows)."""
    findings: list[Finding] = []
    if not removed:
        findings.append(
            Finding("empty_transition", "live_queue_removed is empty: no ticket left")
        )
    if not added:
        findings.append(
            Finding("empty_transition", "archive_added is empty: no row entered")
        )
    removed_tickets = {str(row.get("ticket")) for row in removed}
    added_tickets = {str(row.get("ticket")) for row in added}
    if removed_tickets != added_tickets:
        findings.append(
            Finding(
                "ticket_mismatch",
                "the ticket(s) removed from the live queue are NOT the ticket(s) "
                f"archived: removed={sorted(removed_tickets)} "
                f"archived={sorted(added_tickets)}",
            )
        )
    findings += [f for row in added for f in _archive_row_findings(row)]
    return findings


def _validate_code_only(changed: list[str], delta: dict[str, Any]) -> list[Finding]:
    findings = [
        Finding(
            "foreign_file",
            f"code-only delta carries a third foreign file {path!r}; the close "
            f"writes EXACTLY {sorted(CODE_ONLY_WRITE_SURFACE)}",
        )
        for path in changed
        if path not in CODE_ONLY_WRITE_SURFACE
    ]
    findings += [
        Finding(
            "missing_transition_file",
            f"the expected backlog transition requires {required!r} dirty; the "
            f"delta omits it",
        )
        for required in CODE_ONLY_WRITE_SURFACE
        if required not in changed
    ]
    removed = delta.get("live_queue_removed") or []
    added = delta.get("archive_added") or []
    findings += _transition_findings(removed, added)
    return findings


def _validate_destino(changed: list[str], delta: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    allowed = set(DESTINO_PROJECTIONS)

    for path in changed:
        if path in allowed or _is_auditor_artifact(path):
            continue
        if path in (CODE_ONLY_LIVE_QUEUE, CODE_ONLY_ARCHIVE):
            findings.append(
                Finding(
                    "outside_mode",
                    f"a code-only backlog transition ({path!r}) was applied in "
                    f"destino mode: the code-only exception does not apply here",
                )
            )
        else:
            findings.append(
                Finding(
                    "foreign_file",
                    f"destino delta carries a third foreign file {path!r}; the "
                    f"legitimate dirty is the live projections {sorted(allowed)} "
                    f"plus the auditor artifacts",
                )
            )

    if delta.get("live_queue_removed") or delta.get("archive_added"):
        findings.append(
            Finding(
                "outside_mode",
                "a code-only backlog transition payload (live_queue_removed / "
                "archive_added) was applied outside code-only",
            )
        )
    return findings


def validate_delta(mode: str, delta: dict[str, Any]) -> list[Finding]:
    """Validate a `expected-operational-delta/v1` document against `mode`.

    Before: `mode` in {code-only,destino}; `delta` a parsed JSON object.
    During: checks the declared mode, the extra-hunk counter, and the mode's
        exact write-surface + content facts. Pure and side-effect free.
    After: returns the list of findings ([] means the delta IS the expected
        transition). Never raises for a well-formed dict.
    """
    findings: list[Finding] = []

    declared_mode = delta.get("mode")
    if declared_mode != mode:
        findings.append(
            Finding(
                "mode_mismatch",
                f"delta declares mode {declared_mode!r} but was validated as {mode!r}",
            )
        )

    try:
        extra_hunks = int(delta.get("extra_hunks") or 0)
    except (TypeError, ValueError):
        extra_hunks = -1
    if extra_hunks != 0:
        findings.append(
            Finding(
                "extra_mutation",
                f"{extra_hunks} hunk(s) beyond the expected transition: a permitted "
                f"file was mutated outside the canonical row move",
            )
        )

    raw_paths = delta.get("changed_paths") or []
    if not isinstance(raw_paths, list):
        findings.append(Finding("bad_shape", "changed_paths must be a list of paths"))
        return findings
    changed = [_norm(path) for path in raw_paths]

    if mode == CODE_ONLY_MODE:
        findings.extend(_validate_code_only(changed, delta))
    else:
        findings.extend(_validate_destino(changed, delta))
    return findings


def _load_delta(path: Path) -> dict[str, Any]:
    """Read the delta JSON, BOM-tolerant (utf-8-sig covers both cases)."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("delta must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument(
        "--delta",
        required=True,
        help="path to the expected-operational-delta/v1 JSON document",
    )
    parser.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    args = parser.parse_args(argv)

    try:
        delta = _load_delta(Path(args.delta))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"[expected-operational-delta] USAGE: cannot read delta "
            f"{args.delta!r}: {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if delta.get("schema") not in (None, SCHEMA):
        print(
            f"[expected-operational-delta] USAGE: unknown schema "
            f"{delta.get('schema')!r} (expected {SCHEMA!r})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    findings = validate_delta(args.mode, delta)
    ok = not findings

    if args.json:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "mode": args.mode,
                    "ok": ok,
                    "findings": [
                        {"code": f.code, "detail": f.detail} for f in findings
                    ],
                },
                indent=2,
            )
        )
    else:
        if ok:
            print(
                f"[expected-operational-delta] OK: the repo_destino's dirty IS "
                f"exactly the expected {args.mode} transition."
            )
        else:
            print(
                f"[expected-operational-delta] FAIL: {len(findings)} finding(s) "
                f"against the expected {args.mode} transition:"
            )
            for finding in findings:
                print(f"    - [{finding.code}] {finding.detail}")

    return EXIT_OK if ok else EXIT_VERDICT


if __name__ == "__main__":
    sys.exit(main())
