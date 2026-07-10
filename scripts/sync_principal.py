#!/usr/bin/env python3
"""Sync the motor's PRIMARY (detached) checkout to origin/main -- safely.

The motor is used as two worktrees of one repo: the `_dev` worktree owns branch
`main` (where WOT tickets are worked), and the PRIMARY checkout is kept in a
DETACHED HEAD as a consume-only view. Over time the primary drifts behind `main`
(so its working tree misses prompts/scripts added later) and OTHER sessions
(CTL/EXF prefixes) may leave their own commits on that detached HEAD.

This tool fast-forwards the primary checkout to `origin/main` so its working tree
is current, WITHOUT ever losing another session's work:

  - If the primary HEAD is an ancestor of origin/main -> a clean advance.
  - If the primary HEAD has DIVERGENT commits not reachable from origin/main AND
    not present on any remote -> it FIRST creates a rescue branch
    `rescue/<sha7>-<stamp>` pointing at that HEAD, THEN advances. Nothing is ever
    orphaned. (This is the exact WOT-2026-019f / CTL-012i loss scenario.)
  - If the primary is on a NAMED branch (not detached) -> it is NOT the expected
    consume-only mode; the tool refuses to touch it and reports.

It also reports the QUEUE of rescue/* branches not yet merged into main, so their
owners remember to reintegrate them (the tool never merges rescue branches into
main -- that is a deliberate, reviewed act by whoever finished that work).

Before:
    - --motor-root: any worktree of the motor repo (the shared .git is resolved).
    - --primary-root: the primary checkout path (optional; auto-detected as the
      worktree that is NOT the _dev worktree).
    - --now: timestamp 'YYYYMMDD_HHMM' for the rescue branch name (the caller
      supplies it so runs are reproducible; defaults to UTC now in __main__).
    - --apply: actually move the primary. Default is a DRY-RUN (report only).

After:
    - Exit codes:
        0 = OK (already current, advanced, or dry-run reported cleanly).
        1 = refused (primary on a named branch, or a git operation failed).
        2 = usage/topology error (bad roots, git unavailable).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> dict:
    """Run a git command, capturing stdout/stderr/exit. Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }


def _git(args: list[str], cwd: Path, timeout: int = 60) -> dict:
    return _run(["git", "-C", str(cwd), *args], timeout=timeout)


def _is_worktree_toplevel(path: Path) -> bool:
    """True iff `path` is ITSELF the toplevel of a git worktree (anti-ascent).

    `git rev-parse --git-dir` succeeds from any descendant by ascending to a parent
    repo -- which, when this runs inside a sandbox nested in the motor repo, would
    accept a non-repo dir (the WOT-2026-021k sandbox-ascent trap). We instead
    require `--show-toplevel` to resolve to `path` exactly, so a bare directory
    that merely sits inside a repo is rejected.
    """
    res = _git(["rev-parse", "--show-toplevel"], path)
    if res["exit_code"] != 0:
        return False
    try:
        return Path(res["stdout"].strip()).resolve() == path.resolve()
    except (OSError, ValueError):
        return False


def _worktree_toplevels(motor_root: Path) -> list[Path]:
    """Absolute toplevel paths of every worktree of the repo at motor_root."""
    res = _git(["worktree", "list", "--porcelain"], motor_root)
    if res["exit_code"] != 0:
        return []
    return [
        Path(line[len("worktree ") :].strip()).resolve()
        for line in res["stdout"].splitlines()
        if line.startswith("worktree ")
    ]


def _detect_primary(motor_root: Path, dev_suffix: str = "_dev") -> Path | None:
    """The primary checkout = the worktree whose basename does NOT end in _dev.

    If there are exactly two worktrees (primary + _dev), return the non-_dev one.
    If ambiguous (0 or >1 non-dev), return None so the caller must pass it.
    """
    tops = _worktree_toplevels(motor_root)
    non_dev = [p for p in tops if not p.name.endswith(dev_suffix)]
    return non_dev[0] if len(non_dev) == 1 else None


def _current_branch(repo: Path) -> str | None:
    """Short branch name checked out at repo, or None if detached HEAD."""
    res = _git(["symbolic-ref", "--quiet", "--short", "HEAD"], repo)
    if res["exit_code"] == 0:
        return res["stdout"].strip() or None
    return None


def _head_sha(repo: Path) -> str | None:
    res = _git(["rev-parse", "HEAD"], repo)
    return res["stdout"].strip() if res["exit_code"] == 0 else None


def _is_ancestor(repo: Path, maybe_ancestor: str, descendant: str) -> bool:
    """True iff maybe_ancestor is an ancestor of descendant (clean fast-forward)."""
    res = _git(["merge-base", "--is-ancestor", maybe_ancestor, descendant], repo)
    return res["exit_code"] == 0


def _divergent_commits(repo: Path, primary_sha: str, target: str) -> list[str]:
    """Commits reachable from primary_sha but NOT from target (would be dropped)."""
    res = _git(["rev-list", f"{target}..{primary_sha}"], repo)
    if res["exit_code"] != 0:
        return []
    return [ln.strip() for ln in res["stdout"].splitlines() if ln.strip()]


def _on_any_remote(repo: Path, sha: str) -> bool:
    """True iff sha is contained in at least one remote-tracking branch.

    A divergent commit already on a remote is safe to leave behind (recoverable);
    one that is NOT on any remote must be rescued to a local branch first.
    """
    res = _git(["branch", "-r", "--contains", sha], repo)
    return res["exit_code"] == 0 and bool(res["stdout"].strip())


def _rescue_queue(repo: Path, target: str) -> list[dict]:
    """rescue/* branches whose tip is NOT yet merged into target (still pending)."""
    res = _git(
        [
            "for-each-ref",
            "--format=%(refname:short) %(objectname:short)",
            "refs/heads/rescue/",
        ],
        repo,
    )
    if res["exit_code"] != 0:
        return []
    pending = []
    for line in res["stdout"].splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name, sha = parts
        if not _is_ancestor(repo, name, target):  # not fully merged into target
            pending.append({"branch": name, "sha": sha})
    return pending


def plan_sync(repo: Path, primary: Path, target: str, stamp: str) -> dict:
    """Decide the action without mutating anything. Returns a plan dict.

    action in {already_current, advance, rescue_then_advance, refuse_named_branch,
               error}. This is the pure decision core -- fully testable.
    """
    branch = _current_branch(primary)
    if branch is not None:
        return {
            "action": "refuse_named_branch",
            "branch": branch,
            "reason": f"primary is on named branch '{branch}', not detached (consume-only)",
        }
    primary_sha = _head_sha(primary)
    target_sha = _git(["rev-parse", target], repo)["stdout"].strip()
    if not primary_sha or not target_sha:
        return {"action": "error", "reason": "cannot resolve primary HEAD or target"}
    if primary_sha == target_sha:
        return {
            "action": "already_current",
            "primary_sha": primary_sha,
            "target_sha": target_sha,
        }
    if _is_ancestor(repo, primary_sha, target_sha):
        return {
            "action": "advance",
            "primary_sha": primary_sha,
            "target_sha": target_sha,
        }
    # Divergent: primary has commits not on target.
    divergent = _divergent_commits(repo, primary_sha, target_sha)
    unpushed = [c for c in divergent if not _on_any_remote(repo, c)]
    plan = {
        "primary_sha": primary_sha,
        "target_sha": target_sha,
        "divergent_commits": divergent,
        "unpushed_commits": unpushed,
    }
    if unpushed:
        plan["action"] = "rescue_then_advance"
        plan["rescue_branch"] = f"rescue/{primary_sha[:7]}-{stamp}"
    else:
        # All divergent commits are on a remote -> safe to advance without rescue.
        plan["action"] = "advance"
    return plan


def apply_plan(repo: Path, primary: Path, plan: dict) -> list[str]:
    """Execute a plan produced by plan_sync. Returns a list of action log lines.

    Raises RuntimeError if a git step fails (so the caller reports exit 1).
    """
    log: list[str] = []
    action = plan["action"]
    if action in ("already_current", "refuse_named_branch", "error"):
        return log
    if action == "rescue_then_advance":
        rb = plan["rescue_branch"]
        res = _git(["branch", rb, plan["primary_sha"]], repo)
        if res["exit_code"] != 0:
            raise RuntimeError(f"failed to create rescue branch {rb}: {res['stderr']}")
        log.append(
            f"rescued {len(plan['unpushed_commits'])} unpushed commit(s) -> branch {rb}"
        )
        # Auto-push the rescue branch to origin so it does not depend on the local
        # reflog (the ctl-012i-wip single-point-of-failure this fixes). FAIL-OPEN:
        # a failed push (offline / no remote) is a WARN, never aborts the advance --
        # the local rescue branch already exists, which is the minimum guarantee.
        push = _git(["push", "origin", rb], repo)
        if push["exit_code"] == 0:
            log.append(f"rescue branch pushed to origin/{rb}")
        else:
            log.append(
                f"WARN: could not push rescue branch to origin ({(push['stderr'] or '').strip()[:80]}); "
                "it survives LOCALLY -- push it manually so it does not depend on the reflog"
            )
    # Advance the primary to the target commit (detached, its consume-only mode).
    res = _git(["checkout", "--detach", plan["target_sha"]], primary)
    if res["exit_code"] != 0:
        raise RuntimeError(
            f"failed to advance primary to {plan['target_sha'][:7]}: {res['stderr']}"
        )
    log.append(f"primary advanced to {plan['target_sha'][:7]} (detached)")
    return log


def build_report(
    plan: dict, applied_log: list[str], pending_rescues: list[dict], apply: bool
) -> str:
    """Human-facing report (also the closeout notification text)."""
    lines = ["[sync-principal] motor primary checkout sync"]
    action = plan["action"]
    p7 = (plan.get("primary_sha") or "?")[:7]
    t7 = (plan.get("target_sha") or "?")[:7]
    if action == "already_current":
        lines.append(f"  status: ALREADY CURRENT ({p7} == origin/main)")
    elif action == "refuse_named_branch":
        lines.append(f"  status: REFUSED -- {plan['reason']}")
    elif action == "error":
        lines.append(f"  status: ERROR -- {plan['reason']}")
    elif action == "advance":
        verb = "would advance" if not apply else "advanced"
        lines.append(f"  status: {verb} {p7} -> {t7} (clean fast-forward)")
    elif action == "rescue_then_advance":
        n = len(plan["unpushed_commits"])
        verb = "would rescue+advance" if not apply else "rescued+advanced"
        lines.append(f"  status: {verb} -- {n} unpushed commit(s) DIVERGENT")
        lines.append(f"          rescue branch: {plan['rescue_branch']} (-> {p7})")
        lines.append(f"          then primary {p7} -> {t7}")
        lines.append("  ACTION FOR THE OTHER SESSION: your work was preserved on the")
        lines.append("          rescue branch above. Reintegrate it into main when its")
        lines.append(
            "          ticket is done (rebase onto origin/main, run gates, merge)."
        )
    lines.extend(f"  done: {ln}" for ln in applied_log)
    if pending_rescues:
        lines.append(
            f"  PENDING RESCUE QUEUE ({len(pending_rescues)} not yet merged into main):"
        )
        lines.extend(
            f"    - {r['branch']} ({r['sha']}) -- reintegrate or delete when done"
            for r in pending_rescues
        )
    if not apply and action in ("advance", "rescue_then_advance"):
        lines.append("  (dry-run: re-run with --apply to perform the above)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely sync the motor's primary detached checkout to origin/main."
    )
    parser.add_argument(
        "--motor-root", required=True, help="any worktree of the motor repo"
    )
    parser.add_argument(
        "--primary-root",
        default=None,
        help="primary checkout (auto-detected if omitted)",
    )
    parser.add_argument(
        "--target", default="origin/main", help="ref to sync the primary to"
    )
    parser.add_argument(
        "--now", default=None, help="timestamp YYYYMMDD_HHMM for rescue branch names"
    )
    parser.add_argument(
        "--fetch", action="store_true", help="git fetch origin before planning"
    )
    parser.add_argument(
        "--apply", action="store_true", help="perform the sync (default: dry-run)"
    )
    args = parser.parse_args(argv)

    motor_root = Path(args.motor_root).resolve()
    if not _is_worktree_toplevel(motor_root):
        print(
            f"[sync-principal] ERROR: not a git worktree toplevel: {motor_root}",
            file=sys.stderr,
        )
        return 2

    if args.fetch:
        _git(["fetch", "origin", "--quiet"], motor_root, timeout=120)

    primary = (
        Path(args.primary_root).resolve()
        if args.primary_root
        else _detect_primary(motor_root)
    )
    if primary is None:
        print(
            "[sync-principal] ERROR: could not auto-detect the primary checkout; "
            "pass --primary-root.",
            file=sys.stderr,
        )
        return 2

    stamp = args.now or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    plan = plan_sync(motor_root, primary, args.target, stamp)

    applied_log: list[str] = []
    rc = 0
    if plan["action"] in ("refuse_named_branch", "error"):
        rc = 1
    elif args.apply and plan["action"] in ("advance", "rescue_then_advance"):
        try:
            applied_log = apply_plan(motor_root, primary, plan)
        except RuntimeError as exc:
            print(f"[sync-principal] ERROR: {exc}", file=sys.stderr)
            return 1

    pending = _rescue_queue(motor_root, args.target)
    print(build_report(plan, applied_log, pending, args.apply))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
