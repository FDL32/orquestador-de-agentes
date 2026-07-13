#!/usr/bin/env python3
"""
Worktree topology guard (WOT-2026-021g).

Blocks working a WOT ticket from the primary detached checkout of the motor
(the exact topology that caused the WOT-2026-019f work-loss incident on
2026-07-09: the Builder's mutation-verify collided with a concurrent commit
from CTL-2026-012j in the same shared checkout). This is the ONLY place
where the write discipline "WOT tickets are worked in the _dev worktree,
branch main; the primary checkout is detached/consume-only" lives.

scripts/prefix_resolver.py::guard() answers a DIFFERENT question ("is cwd
the same repo as motor_root") and, for WOT, deliberately does NOT enforce
which worktree/branch to use -- that discipline belongs here, exclusively.

For WOT there are TWO independent verifications, BOTH mandatory:
  Verification A (worktree of the motor): cwd must be a linked worktree of
    the same repo as motor_root, on branch 'main', and that worktree's
    toplevel must match an entry of `git worktree list` whose directory
    name ends in "_dev".
  Verification B (active workspace), evaluated ONLY if A passed: the active
    workspace (--project-root) must be the destination that the WOT prefix
    resolves to, via prefix_resolver.resolve_prefix -- the same mechanism
    every other prefix uses. (Until WOT-2026-023i this was derived by
    destination_id instead, because the workspace link carried
    ticket_prefix: null; the link now declares "WOT" and the bespoke lookup
    is gone.)

For any other prefix (destinations, e.g. CTL/EXF): the motor being detached
is expected (no _dev requirement); only the active workspace must match the
destination resolved by prefix_resolver.resolve_prefix().

CLI:
    python scripts/check_worktree_topology.py --ticket <TICKET_OR_PROJECT>
        [--motor-root <PATH>] [--project-root <PATH>] [--allow-diagnostic]

Env:
    WORKTREE_GUARD_BYPASS=1  same effect as --allow-diagnostic.

Exit codes:
    0 = topology correct for the resolved prefix.
    1 = topology incorrect (WOT in the primary detached checkout, _dev
        missing, or the active workspace does not match what is expected
        for the resolved prefix).
    2 = contract incoherence (delivery_authority in the active work_plan.md
        does not match the prefix) or the prefix/project could not be
        resolved at all.
    With --allow-diagnostic / WORKTREE_GUARD_BYPASS=1: ALWAYS exits 0,
    prints the real verdict (including what would have blocked) prefixed
    with "[DIAGNOSTIC MODE]". This does NOT skip the topology rule, it only
    lets the guard be inspected without blocking.

NOTE: this script never CREATES the _dev worktree. It only warns and points
to scripts/setup_dev_worktree.ps1 as a reference for the user to run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import prefix_resolver


DEV_SUFFIX = "_dev"


def _git_common_dir(path: Path) -> Path | None:
    """Resolve the absolute git-common-dir for path, or None on failure.

    Before: path is a directory that may or may not be a git worktree.
    During: invokes `git -C <path> rev-parse --path-format=absolute
            --git-common-dir` with check=False. The --path-format=absolute
            flag is mandatory (see scripts/prefix_resolver.py::_git_common_dir
            for the full rationale: without it, a relative raw output
            resolves against the calling process's cwd, not against <path>,
            and the match is never True for the real use case).
    After: returns the resolved absolute Path, or None if path is not a git
          repo or git is not on PATH. Callers must fail closed on None.
    """
    git = prefix_resolver._git_executable()
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [
                git,
                "-C",
                str(path),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    return Path(raw).resolve()


def _git_current_branch(path: Path) -> str | None:
    """Return the short branch name checked out at path, or None if detached
    or path is not a git repo / git missing from PATH."""
    git = prefix_resolver._git_executable()
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [git, "-C", str(path), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _git_worktree_list(motor_root: Path) -> list[Path]:
    """Return the list of worktree toplevel paths for the repo at motor_root.

    Before: motor_root is a directory that may or may not be a git repo.
    During: runs `git -C <motor_root> worktree list --porcelain` and parses
            lines starting with "worktree ".
    After: returns a list of absolute Paths (one per worktree entry), or an
          empty list if motor_root is not a git repo / git is unavailable.
    """
    git = prefix_resolver._git_executable()
    if git is None:
        return []
    try:
        result = subprocess.run(  # noqa: S603
            [git, "-C", str(motor_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [
        Path(line[len("worktree ") :].strip()).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def _find_dev_worktree(motor_root: Path) -> Path | None:
    """Find the worktree entry whose directory basename ends in '_dev'.

    Before: motor_root is a git repo (or a worktree of one).
    During: scans `git worktree list --porcelain` (run with -C motor_root)
            for an entry whose basename ends in DEV_SUFFIX. The suffix is
            compared against the real basename of the worktree entry, never
            a hardcoded repo name.
    After: returns the matching worktree Path, or None if no such entry
          exists (the _dev worktree has not been created yet).
    """
    for wt_path in _git_worktree_list(motor_root):
        if wt_path.name.endswith(DEV_SUFFIX):
            return wt_path
    return None


def _check_wot_topology(
    cwd: Path, motor_root: Path, project_root: Path
) -> tuple[int, str]:
    """Verification A (motor worktree) + Verification B (active workspace).

    Before: cwd is where the agent is running from; motor_root is the
            motor repo root; project_root is the active session workspace.
    During: Verification A -- cwd and motor_root must share the same
            git-common-dir (same repo). If either side cannot be resolved
            (not a git repo, git missing), fails closed: "cannot determine
            topology" (exit 2, distinguishable from a confirmed mismatch).
            If they ARE the same repo: cwd's branch must be 'main' AND
            cwd's toplevel must match a `git worktree list` entry whose
            basename ends in "_dev". If the branch isn't main or the
            toplevel doesn't match that _dev entry -> exit 1 with the exact
            instruction to use _dev. If no _dev entry exists at all -> exit
            1 with the "create _dev" message (never auto-created here).
            Verification B runs ONLY if A returned exit 0: resolves the
            expected workspace via prefix_resolver.resolve_prefix(WOT), the
            same mechanism every other prefix uses. If WOT does not resolve
            (no link declares ticket_prefix "WOT", or more than one does and
            it is ambiguous) -> exit 2, "cannot determine" (NOT exit 1,
            which means "the workspace is the wrong one"); if project_root
            does not match the resolved destination -> exit 1.
    After: returns (exit_code, message).
    """
    cwd_common = _git_common_dir(cwd)
    motor_common = _git_common_dir(motor_root)
    if cwd_common is None or motor_common is None:
        return (
            2,
            f"no se puede determinar topologia: cwd ({cwd}) no es worktree "
            f"del mismo repo que motor_root ({motor_root}) -- git-common-dir "
            "no resoluble para uno de los dos (no es repo git, o git no "
            "esta en PATH)",
        )
    if cwd_common != motor_common:
        return (
            2,
            f"no se puede determinar topologia: cwd ({cwd}) no es worktree "
            f"del mismo repo que motor_root ({motor_root})",
        )

    dev_entry = _find_dev_worktree(motor_root)
    if dev_entry is None:
        return (
            1,
            "Crea la worktree _dev: .\\scripts\\setup_dev_worktree.ps1",
        )

    branch = _git_current_branch(cwd)
    cwd_toplevel = _git_common_dir_toplevel(cwd)
    if branch != "main" or cwd_toplevel != dev_entry.resolve():
        return (
            1,
            "Ticket WOT escribe en el MOTOR: usa la worktree _dev (rama "
            "main), no el checkout principal (detached=consumo). Ver "
            "scripts/setup_dev_worktree.ps1.",
        )

    expected_workspace = prefix_resolver.resolve_prefix(
        prefix_resolver.WOT_PREFIX, motor_root
    )
    if expected_workspace is None:
        return (
            2,
            "no se pudo derivar el workspace esperado para WOT: ningun link "
            f"declara ticket_prefix == {prefix_resolver.WOT_PREFIX}, o mas de "
            "uno lo declara (ambiguo). Diagnostico: "
            "python scripts/prefix_resolver.py --verify",
        )
    if project_root.resolve() != expected_workspace.resolve():
        return (
            1,
            f"Ticket WOT necesita el workspace {expected_workspace}, "
            f"no {project_root}.",
        )
    return (
        0,
        "topologia correcta: worktree del motor (_dev/main) y workspace correctos",
    )


def _git_common_dir_toplevel(path: Path) -> Path | None:
    """Return the toplevel (worktree root) for path, or None on failure."""
    git = prefix_resolver._git_executable()
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [git, "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    return Path(raw).resolve()


def _check_destination_topology(
    prefix: str, cwd: Path, motor_root: Path
) -> tuple[int, str]:
    """Verification for non-WOT prefixes: cwd must equal the resolved
    destination_root for that prefix. The motor being detached is expected
    and NOT checked here (no _dev requirement for destinations).

    Before: prefix is a resolved ticket prefix (e.g. "CTL", "EXF").
    During: resolves prefix via prefix_resolver.resolve_prefix. If it
            cannot be resolved -> exit 2. If cwd != resolved -> exit 1.
    After: returns (exit_code, message).
    """
    resolved = prefix_resolver.resolve_prefix(prefix, motor_root)
    if resolved is None:
        return (2, f"prefijo desconocido: {prefix}")
    if cwd.resolve() != resolved.resolve():
        return (1, f"Ticket {prefix} necesita el workspace {resolved}, no {cwd}.")
    return (0, f"topologia correcta: workspace {resolved} coincide con {prefix}")


def _check_contract_coherence(
    motor_root: Path, prefix: str | None
) -> tuple[int, str] | None:
    """Cross delivery_authority (from the ACTIVE work_plan.md, if any)
    against the resolved prefix. WOT must carry repo_motor; any other
    prefix must carry repo_destino. Returns None if there's no work_plan.md
    to check (not blocking: this guard runs in preflight, possibly before a
    plan exists) OR if the work_plan is in a TERMINAL state (a closed ticket's
    contract must not block the launch of a new ticket of another prefix --
    WOT-2026-021s; the residual COMPLETED work_plan of a prior WOT would
    otherwise false-block any CTL start with "incoherencia de contrato").
    Returns (exit_code, message) on a genuine live mismatch.
    """
    work_plan_path = motor_root / ".agent" / "collaboration" / "work_plan.md"
    if not work_plan_path.exists():
        return None
    try:
        content = work_plan_path.read_text(encoding="utf-8")
    except OSError:
        return None

    agent_dir = motor_root / ".agent"
    sys.path.insert(0, str(agent_dir))
    import scope_gate
    import state_validation

    # A work_plan in a terminal state is a CLOSED ticket's contract -> it must
    # not block a new ticket. The 3 irreversible terminals mirror the canonical
    # source bus/state_machine.py IRREVERSIBLE_TERMINAL_STATES; they are
    # replicated inline (not imported) because bus/ hangs off motor_root, NOT
    # off .agent/ (the only dir this guard adds to sys.path) -- importing bus
    # here would raise ImportError. get_status returns "UNKNOWN" when there's no
    # Estado marker, which is NOT terminal, so a plan-less/Estado-less work_plan
    # still gets its contract crossed (the genuine-incoherence path is intact).
    # Normalize the raw status: uppercase + first whitespace token, so a
    # decorated marker ("completed", "COMPLETED (archivado)", "COMPLETED ✅")
    # still matches the bare terminal literal.
    terminal_states = frozenset({"COMPLETED", "SUPERSEDED", "BLOCKED_FINAL"})
    raw_status = state_validation.get_status(content, "**Estado:**")
    normalized_status = (
        raw_status.strip().upper().split()[0] if raw_status.strip() else ""
    )
    if normalized_status in terminal_states:
        return None

    delivery_authority = scope_gate.read_delivery_authority(content)
    expected = "repo_motor" if prefix == prefix_resolver.WOT_PREFIX else "repo_destino"
    if delivery_authority != expected:
        return (
            2,
            f"incoherencia de contrato: prefijo {prefix} vs delivery_authority "
            f"{delivery_authority}",
        )
    return None


def check_topology(
    ticket_or_project: str,
    cwd: Path,
    motor_root: Path,
    project_root: Path,
) -> tuple[int, str]:
    """Dispatch to the WOT or destination verification, after checking
    contract coherence when a work_plan.md is present.

    Before: ticket_or_project is a ticket ID or project name.
    During: extracts the prefix (raises for malformed IDs -> exit 2),
            checks delivery_authority coherence first (if a work_plan.md
            exists) -- an incoherence short-circuits before any topology
            check. Then dispatches: WOT -> _check_wot_topology (with
            project_root); anything else -> _check_destination_topology
            (with project_root as the "cwd" being compared against the
            resolved destination).
    After: returns (exit_code, message).
    """
    try:
        prefix = prefix_resolver.extract_prefix(ticket_or_project)
    except ValueError as exc:
        return (2, str(exc))

    coherence_issue = _check_contract_coherence(motor_root, prefix)
    if coherence_issue is not None:
        return coherence_issue

    if prefix == prefix_resolver.WOT_PREFIX:
        return _check_wot_topology(cwd, motor_root, project_root)
    if prefix is not None:
        return _check_destination_topology(prefix, project_root, motor_root)
    # Project name (no ticket prefix): resolve like prefix_resolver.guard does.
    resolved = prefix_resolver.resolve_by_project_name(ticket_or_project, motor_root)
    if resolved is None:
        return (2, f"prefijo desconocido: {ticket_or_project}")
    if project_root.resolve() != resolved.resolve():
        return (
            1,
            f"Ticket {ticket_or_project} necesita el workspace {resolved}, "
            f"no {project_root}.",
        )
    return (
        0,
        f"topologia correcta: workspace {resolved} coincide con {ticket_or_project}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Worktree topology guard: blocks WOT tickets worked from "
        "the primary detached checkout instead of the _dev worktree."
    )
    parser.add_argument("--ticket", required=True, help="Ticket ID or project name.")
    parser.add_argument(
        "--motor-root", help="Path to the motor repo (auto-discovered if omitted)."
    )
    parser.add_argument(
        "--project-root",
        help="Active session workspace (defaults to cwd if omitted).",
    )
    parser.add_argument(
        "--allow-diagnostic",
        action="store_true",
        help="Always exit 0; print the real verdict with [DIAGNOSTIC MODE]. "
        "Does not skip the rule, only unblocks debugging.",
    )
    args = parser.parse_args(argv)

    diagnostic = args.allow_diagnostic or os.environ.get("WORKTREE_GUARD_BYPASS") == "1"

    cwd = Path.cwd()
    motor_root = (
        Path(args.motor_root)
        if args.motor_root
        else prefix_resolver.discover_motor_root(cwd)
    )
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 0 if diagnostic else 2
    project_root = Path(args.project_root) if args.project_root else Path.cwd()

    exit_code, message = check_topology(args.ticket, cwd, motor_root, project_root)

    if diagnostic:
        print(
            f"[DIAGNOSTIC MODE] veredicto real: "
            f"{'bloqueado' if exit_code != 0 else 'OK'}, motivo: {message}",
            file=sys.stderr,
        )
        return 0

    stream = sys.stderr if exit_code != 0 else sys.stdout
    prefix_tag = "[ERROR]" if exit_code != 0 else "[OK]"
    print(f"{prefix_tag} {message}", file=stream)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
