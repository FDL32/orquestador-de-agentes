#!/usr/bin/env python3
# ruff: noqa: S603
"""Preflight collector for the code-only motor pipeline (collector, NOT executor).

Witness for `prompts/orchestrator_pipeline_codeonly.md` (Paso 0). Runs read-only
deterministic checks and reports SIGNALS; the AGENT judges whether to proceed. It
NEVER mutates the tree, NEVER closes a ticket, NEVER decides on its own.

Checks:
    - SHAs of the 3 repos (_dev, principal, workspace) + _dev tree cleanliness.
    - `agent_controller.py --validate --json --force` -> 0 errors, plus a DERIVED
      warnings taxonomy (see below): accepted_advisories vs actionable_warnings.
    - Worktree topology guard (check_worktree_topology.py): _dev/main correct.
    - BARRIER "0 runtime consumers": case-insensitive `git grep -i` of --retire-token
      across the tree, EXCLUDING the file that owns the symbol (--retire-owner) and
      deliberate history (CHANGELOG/DEC/.agent/collaboration). Empty result = 0
      consumers = safe to retire. This is the check that makes a deprecated-code
      retirement safe; topology + SHAs alone are not enough.

Warnings taxonomy (WOT-2026-021u): `validate --json` emits `warnings` as a dict
keyed by CATEGORY (`ticket_prose`, `bus_drift`, `invariants`, ...); `ticket_prose`
entries carry a `[TP-XXX-NN]` code as a text PREFIX (no structured rule_id for the
other categories). This module classifies each raw warning into exactly one of:
    - `accepted_advisories`: a KNOWN STRUCTURAL signal of code-only mode that does
      NOT require action (bus/invariants warnings while running code-only; ticket
      prose warnings on an ALREADY-TERMINAL work_plan). Never counted as critical.
    - `actionable_warnings`: everything else, including `TP-FATAL-01` (missing
      work_plan.md) UNCONDITIONALLY -- a fatal prose signal is never advisory.
This is a DERIVED, read-only judgment layer; it does NOT mutate `validate`'s
schema or its consumers (collect_system_health/pre_handoff_guard read
`total_errors`/`exit_code` only, never `warnings[]`, so this addition is safe).

Exit codes (collect_system_health.py convention):
    0 = collection OK, no automatic criticals (safe to proceed; agent still judges).
    1 = collection OK, automatic criticals present (dirty tree / validate errors /
        actionable warnings / topology fail / consumers found). STOP and
        reconcile before proceeding.
    2 = execution/collection error (bad paths, git unavailable).

session_state (WOT-2026-022f): reports the session-scratch lifecycle signal
(`none` / `active` / `stale`) by CONSUMING the canonical 022c entry point
(`scripts/init_session_scratch.py list --project-root <workspace-root>`), never
re-deriving the session path by hand. The session lives in `--workspace-root`
(the active repo_destino), NOT in the motor `--dev-root` -- looking for it in the
motor would report `none` unconditionally (a structural false-green). `stale` is
authoritative on the lock TTL (`expires_at`), exactly as `_lock_is_live` in
init_session_scratch.py; a dead pid is an AUXILIARY, best-effort signal only,
never a standalone fixture. Also reports (path only, never content) the most
recently archived session summary under `_archive/`, if any, to close the N->N+1
bootstrap loop without inflating context.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# Canonical bootstrap (matches other scripts/*.py): this script lives inside the
# motor repo at scripts/preflight_codeonly_pipeline.py, so its own parent IS the
# motor root regardless of what --dev-root points to (the two coincide in real
# invocations per prompts/orchestrator_pipeline_codeonly.md; --dev-root can point
# elsewhere only in tests, which patch is_motor_code_only directly instead).
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from runtime.project_root import clear_cache, is_motor_code_only  # noqa: E402
from scripts.init_session_scratch import _archive_root  # noqa: E402
from scripts.validate_ticket_prose import is_completed_plan  # noqa: E402


SCHEMA_VERSION = "codeonly-preflight-collector/v1"

# Matches the `[TP-XXX-NN]` prefix that validate_ticket_prose.py bakes into every
# ticket_prose warning string (see agent_controller._handle_validate: f"[{rule_id}]
# {rule_name}: {suggestion}").
_TP_CODE_RE = re.compile(r"^\[(?P<code>TP-[A-Z]+-\d+)\]")

# Paths excluded from the "0 runtime consumers" grep: deliberate history + the
# collaboration projections. The owner file is added dynamically from --retire-owner.
HISTORY_EXCLUDES = [
    ":(exclude)CHANGELOG.md",
    ":(exclude).agent/collaboration/",
    ":(exclude).agent/planning/decisions.md",
]


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> dict:
    """Run a command read-only; capture rc/stdout/stderr. Never raises on rc!=0."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except FileNotFoundError as exc:
        return {"cmd": cmd, "returncode": 127, "stdout": "", "stderr": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {"cmd": cmd, "returncode": 124, "stdout": "", "stderr": str(exc)}


def _head(cwd: Path) -> str | None:
    r = _run(["git", "rev-parse", "HEAD"], cwd)
    return r["stdout"].strip() if r["returncode"] == 0 else None


def _tree_clean(cwd: Path) -> bool | None:
    r = _run(["git", "status", "--short"], cwd)
    if r["returncode"] != 0:
        return None
    return r["stdout"].strip() == ""


def _check_shas(findings: dict, args, dev, principal, workspace) -> None:
    dev_head = _head(dev)
    dev_clean = _tree_clean(dev)
    findings["checks"]["dev"] = {
        "head": dev_head,
        "tree_clean": dev_clean,
        "expected_sha": args.expect_dev_sha,
        "sha_matches": (dev_head == args.expect_dev_sha)
        if args.expect_dev_sha
        else None,
    }
    if dev_clean is False:
        findings["automatic_criticals"].append("dev_tree_dirty")
    if args.expect_dev_sha and dev_head != args.expect_dev_sha:
        findings["automatic_criticals"].append("dev_sha_mismatch")
    if principal:
        findings["checks"]["principal"] = {
            "head": _head(principal),
            "expected_sha": args.expect_principal_sha,
        }
    if workspace:
        findings["checks"]["workspace"] = {
            "head": _head(workspace),
            "expected_sha": args.expect_workspace_sha,
        }


def classify_warnings(
    raw_warnings: dict[str, list[str]],
    *,
    code_only: bool,
    work_plan_content: str | None,
) -> dict[str, list[str]]:
    """Classify raw `validate --json` warnings into accepted vs actionable.

    Before: `raw_warnings` is the dict-by-category structure emitted by
        `agent_controller.py --handle_validate` (e.g. {"ticket_prose": [...],
        "bus_drift": [...], "invariants": [...]}); `code_only` reflects the
        LIVE result of `runtime.project_root.is_motor_code_only()` for the run
        being classified; `work_plan_content` is the raw text of the motor's
        work_plan.md, or None if it does not exist (never classify as accepted
        in that case: TP-FATAL-01 handles the missing-file signal explicitly).
    During: Iterates every category and every warning string. `bus_drift` and
        `invariants` entries are accepted only when `code_only` is True (a
        destination run with a broken/absent bus is NOT advisory). `ticket_prose`
        entries are parsed for a `[TP-XXX-NN]` prefix: `TP-FATAL-01` is ALWAYS
        actionable (the plan-audit correction: a fatal signal is never
        advisory); other `TP-PROSE-*`/`TP-STRUCT-*` codes are accepted only if
        `work_plan_content` is not None AND
        `validate_ticket_prose.is_completed_plan(work_plan_content)` is True.
        Any other category or unrecognized code defaults to actionable
        (fail-closed: unknown signals are never silently swallowed).
    After: Returns {"accepted_advisories": [...], "actionable_warnings": [...]}.
        Every input warning string appears in exactly one of the two lists;
        counts are always derived, never hardcoded.
    """
    plan_is_terminal = work_plan_content is not None and is_completed_plan(
        work_plan_content
    )

    accepted: list[str] = []
    actionable: list[str] = []

    for category, warns in raw_warnings.items():
        for warning in warns:
            if category in ("bus_drift", "invariants"):
                (accepted if code_only else actionable).append(warning)
                continue
            if category == "ticket_prose":
                match = _TP_CODE_RE.match(warning)
                code = match.group("code") if match else None
                if code == "TP-FATAL-01" or code is None:
                    actionable.append(warning)
                elif plan_is_terminal:
                    accepted.append(warning)
                else:
                    actionable.append(warning)
                continue
            # Unknown category (e.g. work_plan.md deliverable_type, scope,
            # contract_gap): fail-closed, never silently accepted.
            actionable.append(warning)

    return {"accepted_advisories": accepted, "actionable_warnings": actionable}


def _check_validate(findings: dict, dev) -> None:
    validate = _run(
        [
            sys.executable,
            str(dev / ".agent" / "agent_controller.py"),
            "--validate",
            "--json",
            "--force",
        ],
        dev,
        timeout=300,
    )
    total_errors = None
    raw_warnings: dict[str, list[str]] = {}
    if validate["returncode"] in (0, 1) and validate["stdout"].strip():
        try:
            payload = json.loads(validate["stdout"])
            total_errors = payload.get("total_errors")
            raw_warnings = payload.get("warnings") or {}
        except json.JSONDecodeError:
            total_errors = None

    clear_cache()
    code_only = is_motor_code_only()

    work_plan_path = dev / ".agent" / "collaboration" / "work_plan.md"
    work_plan_content = (
        work_plan_path.read_text(encoding="utf-8") if work_plan_path.exists() else None
    )

    classification = classify_warnings(
        raw_warnings, code_only=code_only, work_plan_content=work_plan_content
    )
    accepted = classification["accepted_advisories"]
    actionable = classification["actionable_warnings"]

    findings["checks"]["validate"] = {
        "returncode": validate["returncode"],
        "total_errors": total_errors,
        "raw_warnings": raw_warnings,
        "accepted_advisories": accepted,
        "actionable_warnings": actionable,
        "note": "accepted_advisories are known code-only structural signals "
        "(bus absent / terminal work_plan prose); actionable_warnings require "
        "action and are never silently accepted",
    }
    if total_errors not in (0, None):
        findings["automatic_criticals"].append("validate_errors")
    elif total_errors is None and validate["returncode"] not in (0, 1):
        findings["automatic_criticals"].append("validate_unparseable")
    if actionable:
        findings["automatic_criticals"].append("validate_actionable_warnings")


def derive_session_state(sessions: list[dict]) -> str:
    """Derive the aggregate `session_state` signal from `init_session_scratch list`.

    Before: `sessions` is the `sessions` array of the JSON emitted by
        `scripts/init_session_scratch.py list --include-archive
        --project-root <workspace-root>` (schema: `{"session_id", "record_count",
        "lock_state", "archived"}` per entry). `lock_state` is one of
        `"live"`/`"stale"`/`"none"` as computed by `_lock_is_live` (022c), which is
        TTL-pure on `expires_at` -- never a pid-liveness check.
    During: filters out archived entries (`archived=True`) and entries with
        `record_count == 0` (no session with ledger activity == no session, per
        the contract). Among the remaining ACTIVE, non-empty sessions: if any has
        `lock_state == "live"`, the aggregate is `"active"` (a live session takes
        priority: it is currently in use). Else, if any remains, the aggregate is
        `"stale"` (expired/corrupt/reclaimable lock, or no lock at all on a
        non-empty session). If none remain, `"none"`.
    After: returns exactly one of `"none"` / `"active"` / `"stale"`. Never raises;
        an empty or malformed `sessions` list yields `"none"` (fail-closed to the
        least alarming signal, consistent with a collector that must never invent
        state).
    """
    candidates = [
        s
        for s in sessions
        if not s.get("archived") and (s.get("record_count") or 0) > 0
    ]
    if not candidates:
        return "none"
    if any(s.get("lock_state") == "live" for s in candidates):
        return "active"
    return "stale"


def _latest_archived_summary_path(workspace: Path, sessions: list[dict]) -> str | None:
    """Path (never content) of the most recently archived session, if any.

    Session IDs sort lexicographically by their `YYYYMMDD-HHMM-...` prefix, so the
    max of the archived subset is the most recent. Uses `_archive_root` (022c's own
    helper) to build the path -- never re-derives the `_archive/` layout by hand.
    """
    archived_ids = sorted(s["session_id"] for s in sessions if s.get("archived"))
    if not archived_ids:
        return None
    return str(_archive_root(workspace) / archived_ids[-1])


def _check_session_state(findings: dict, args, dev, workspace) -> None:
    """Report `session_state` by consuming the 022c `list` entry point.

    The session lives in `--workspace-root` (the active repo_destino), NOT in
    `--dev-root` (the motor): a code-only pipeline run has no session of its own,
    so looking in the motor would report `none` unconditionally regardless of
    reality (structural false-green, EJE ESCRITOR/LECTOR). Falls back to `dev`
    only when no `--workspace-root` was supplied, so the check still runs (with a
    `root_source` marker) for callers that operate entirely inside the motor.
    """
    session_root = workspace if workspace is not None else dev
    root_source = "workspace" if workspace is not None else "dev_fallback"

    list_result = _run(
        [
            sys.executable,
            str(dev / "scripts" / "init_session_scratch.py"),
            "--project-root",
            str(session_root),
            "list",
            "--include-archive",
        ],
        dev,
    )

    sessions: list[dict] = []
    parse_ok = False
    if list_result["returncode"] == 0 and list_result["stdout"].strip():
        try:
            payload = json.loads(list_result["stdout"])
            sessions = payload.get("sessions") or []
            parse_ok = True
        except json.JSONDecodeError:
            parse_ok = False

    state = derive_session_state(sessions) if parse_ok else "none"
    archived_summary_path = (
        _latest_archived_summary_path(session_root, sessions) if parse_ok else None
    )

    findings["checks"]["session_state"] = {
        "session_state": state,
        "root_source": root_source,
        "root": str(session_root),
        "returncode": list_result["returncode"],
        "parse_ok": parse_ok,
        "session_count": len(sessions),
        "latest_archived_summary_path": archived_summary_path,
    }
    if not parse_ok and list_result["returncode"] != 0:
        findings["automatic_criticals"].append("session_state_list_failed")


def _check_topology(findings: dict, args, dev, principal, workspace) -> None:
    topo_cmd = [
        sys.executable,
        str(dev / "scripts" / "check_worktree_topology.py"),
        "--ticket",
        args.ticket,
        "--motor-root",
        str(principal) if principal else str(dev),
    ]
    if workspace:
        topo_cmd += ["--project-root", str(workspace)]
    topo = _run(topo_cmd, dev)
    findings["checks"]["topology"] = {
        "returncode": topo["returncode"],
        "ok": topo["returncode"] == 0,
        "stdout": topo["stdout"].strip()[:400],
    }
    if topo["returncode"] != 0:
        findings["automatic_criticals"].append("topology_fail")


def _check_consumers(findings: dict, args, dev) -> None:
    """BARRIER: 0 runtime consumers of the retire-token.

    git grep exit codes: 0 = matches, 1 = no matches, >1 = error. Uses -i
    (lesson 021d: a grep without -i let a capitalized token escape). Excludes the
    owner file + deliberate history. Verdict is by OUTPUT (empty=OK), not exit code.
    """
    if not args.retire_token:
        return
    pathspecs = ["--", *HISTORY_EXCLUDES]
    pathspecs.extend(f":(exclude){owner}" for owner in args.retire_owner or [])
    grep = _run(["git", "grep", "-inE", args.retire_token, *pathspecs], dev)
    hits = [ln for ln in grep["stdout"].splitlines() if ln.strip()]
    if hits:
        verdict = "consumers_found"
    elif grep["returncode"] == 1:
        verdict = "0_consumers_ok"
    else:
        verdict = "grep_error"
    findings["checks"]["consumers"] = {
        "returncode": grep["returncode"],
        "hit_count": len(hits),
        "hits": hits[:20],
        "verdict": verdict,
        "note": "interpret by OUTPUT (empty=OK), not exit code (differs across shells)",
    }
    if hits:
        findings["automatic_criticals"].append("runtime_consumers_found")
    elif grep["returncode"] not in (0, 1):
        findings["automatic_criticals"].append("consumer_grep_error")


def collect(args: argparse.Namespace) -> dict:
    dev = Path(args.dev_root).resolve()
    principal = Path(args.principal_root).resolve() if args.principal_root else None
    workspace = Path(args.workspace_root).resolve() if args.workspace_root else None

    findings: dict = {
        "schema": SCHEMA_VERSION,
        "ticket": args.ticket,
        "retire_token": args.retire_token,
        "checks": {},
        "automatic_criticals": [],
        "note": "Collector output is [RELATO]; the agent produces the verdict.",
    }

    if not (dev / ".git").exists():
        findings["checks"]["dev_root"] = {"ok": False, "detail": "not a git repo"}
        findings["automatic_criticals"].append("dev_root_not_a_repo")
        return findings

    _check_shas(findings, args, dev, principal, workspace)
    _check_validate(findings, dev)
    _check_session_state(findings, args, dev, workspace)
    _check_topology(findings, args, dev, principal, workspace)
    _check_consumers(findings, args, dev)
    return findings


def _report(findings: dict) -> None:
    print("=" * 64)
    print(f"  PREFLIGHT code-only pipeline  ticket={findings['ticket']}")
    print("=" * 64)
    dev = findings["checks"].get("dev", {})
    print(f"_dev HEAD    : {dev.get('head')}  clean={dev.get('tree_clean')}", end="")
    if dev.get("sha_matches") is not None:
        print(f"  sha_matches={dev.get('sha_matches')}")
    else:
        print()
    for repo in ("principal", "workspace"):
        c = findings["checks"].get(repo)
        if c:
            print(f"{repo:12s}: {c.get('head')}")
    v = findings["checks"].get("validate", {})
    n_accepted = len(v.get("accepted_advisories", []))
    n_actionable = len(v.get("actionable_warnings", []))
    print(
        f"validate     : errors={v.get('total_errors')} "
        f"actionable={n_actionable} accepted_advisories={n_accepted}"
    )
    for w in v.get("actionable_warnings", []):
        print(f"    [actionable] {w}")
    ss = findings["checks"].get("session_state", {})
    if ss:
        print(
            f"session_state: {ss.get('session_state')} "
            f"(root_source={ss.get('root_source')}, sessions={ss.get('session_count')})"
        )
        if ss.get("latest_archived_summary_path"):
            print(
                f"    latest_archived_summary: {ss.get('latest_archived_summary_path')}"
            )
    t = findings["checks"].get("topology", {})
    print(f"topology     : ok={t.get('ok')}")
    cons = findings["checks"].get("consumers")
    if cons:
        print(f"consumers    : {cons.get('verdict')} (hits={cons.get('hit_count')})")
        for h in cons.get("hits", []):
            print(f"    {h}")
    crits = findings["automatic_criticals"]
    print("-" * 64)
    if crits:
        print(f"AUTOMATIC CRITICALS: {crits}  -> STOP, reconcile before proceeding")
    else:
        print("no automatic criticals -> preflight clean (agent still judges)")
    print("=" * 64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight collector for the code-only motor pipeline "
        "(witness, not executor)."
    )
    parser.add_argument(
        "--dev-root", required=True, help="Path to the motor _dev worktree."
    )
    parser.add_argument(
        "--principal-root", help="Path to the principal (detached) checkout."
    )
    parser.add_argument(
        "--workspace-root", help="Path to the workspace (backlog) repo."
    )
    parser.add_argument(
        "--ticket", required=True, help="Ticket ID (e.g. WOT-2026-020n)."
    )
    parser.add_argument(
        "--retire-token",
        help="Regex of the symbol/token being retired; grepped case-insensitively "
        "for runtime consumers.",
    )
    parser.add_argument(
        "--retire-owner",
        action="append",
        help="Path(s) that OWN the token (excluded from the consumer grep). Repeatable.",
    )
    parser.add_argument(
        "--expect-dev-sha", help="Expected _dev HEAD SHA (drift check)."
    )
    parser.add_argument("--expect-principal-sha", help="Expected principal HEAD SHA.")
    parser.add_argument("--expect-workspace-sha", help="Expected workspace HEAD SHA.")
    parser.add_argument(
        "--json", action="store_true", help="Emit findings.json to stdout."
    )
    args = parser.parse_args(argv)

    try:
        findings = collect(args)
    except Exception as exc:
        print(f"[ERROR] preflight collection failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    else:
        _report(findings)

    return 1 if findings["automatic_criticals"] else 0


if __name__ == "__main__":
    sys.exit(main())
