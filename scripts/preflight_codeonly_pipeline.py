#!/usr/bin/env python3
# ruff: noqa: S603
"""Preflight collector for the code-only motor pipeline (collector, NOT executor).

Witness for `prompts/orchestrator_pipeline_codeonly.md` (Paso 0). Runs read-only
deterministic checks and reports SIGNALS; the AGENT judges whether to proceed. It
NEVER mutates the tree, NEVER closes a ticket, NEVER decides on its own.

Checks:
    - SHAs of the 3 repos (_dev, principal, workspace) + _dev tree cleanliness.
    - `agent_controller.py --validate --json --force` -> 0 errors (bus_drift
      warnings are NORMAL in code-only and are not counted as errors).
    - Worktree topology guard (check_worktree_topology.py): _dev/main correct.
    - BARRIER "0 runtime consumers": case-insensitive `git grep -i` of --retire-token
      across the tree, EXCLUDING the file that owns the symbol (--retire-owner) and
      deliberate history (CHANGELOG/DEC/.agent/collaboration). Empty result = 0
      consumers = safe to retire. This is the check that makes a deprecated-code
      retirement safe; topology + SHAs alone are not enough.

Exit codes (collect_system_health.py convention):
    0 = collection OK, no automatic criticals (safe to proceed; agent still judges).
    1 = collection OK, automatic criticals present (dirty tree / validate errors /
        topology fail / consumers found). STOP and reconcile before proceeding.
    2 = execution/collection error (bad paths, git unavailable).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCHEMA_VERSION = "codeonly-preflight-collector/v0"

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
    if validate["returncode"] in (0, 1) and validate["stdout"].strip():
        try:
            total_errors = json.loads(validate["stdout"]).get("total_errors")
        except json.JSONDecodeError:
            total_errors = None
    findings["checks"]["validate"] = {
        "returncode": validate["returncode"],
        "total_errors": total_errors,
        "note": "bus_drift/invariants warnings are NORMAL in code-only mode",
    }
    if total_errors not in (0, None):
        findings["automatic_criticals"].append("validate_errors")
    elif total_errors is None and validate["returncode"] not in (0, 1):
        findings["automatic_criticals"].append("validate_unparseable")


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
    print(
        f"validate     : total_errors={v.get('total_errors')} (bus_drift warns normal)"
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
