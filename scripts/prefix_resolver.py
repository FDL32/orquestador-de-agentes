#!/usr/bin/env python3
"""
Prefix resolver: maps ticket prefixes to destination repos (WOT-2026-020s).

ARCHITECTURE: scans parent(motor_root) for motor_destination_link.json files,
each declaring a ticket_prefix + destination_root. Builds a reverse map
prefix -> destination_root. WOT is a special case resolving to motor_root
(the motor itself, which versions .agent/collaboration/ for dogfooding).

No versioned registry, no auto-registration in install. The mapping is derived
purely from the links that already exist on disk. A local overrides file
(prefix_resolver.local.json, gitignored) can add destinations outside the
search tree; a .example template is versioned.

CLI:
    python scripts/prefix_resolver.py --resolve <PREFIX> [--motor-root <PATH>]
    python scripts/prefix_resolver.py --verify [--motor-root <PATH>]
    python scripts/prefix_resolver.py --guard <TICKET_OR_PROJECT> [--motor-root <PATH>]

Exit codes:
    0 = success (resolved / verified / guard passed)
    1 = resolution failed (unknown prefix, mismatch) or verify found issues
    2 = error (malformed input, cannot discover motor_root)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"
LOCAL_OVERRIDES = Path(__file__).resolve().parent / "prefix_resolver.local.json"
WOT_PREFIX = "WOT"
# Canonical ticket ID: PREFIX-YYYY-NNNx (e.g. WOT-2026-020t, EXF-2026-010a)
TICKET_ID_RE = re.compile(r"^[A-Z]{2,5}-\d{4}-\d{3}[a-z]$")
# Malformed ticket ID: looks like one but doesn't match canonical pattern
MALFORMED_ID_RE = re.compile(r"^[A-Za-z]{2,5}-\d{1,4}-\d{1,4}[a-z]?$")
PREFIX_RE = re.compile(r"^[A-Z]{2,5}$")


def discover_motor_root(cwd: Path) -> Path | None:
    """Discover motor_root from cwd.

    Before: cwd may be the motor itself (has agent_controller.py) or a
            destination (has a link pointing to the motor).
    During: checks FIRST if cwd IS the motor (agent_controller.py present),
            then tries cwd's link (motor_root field), then AGENT_PROJECT_ROOT
            env. Motor-first avoids treating the motor as a destination when
            it has a stale/self-referential link.
    After: returns the motor_root Path, or None if undiscoverable.
    """
    if (cwd / ".agent" / "agent_controller.py").exists():
        return cwd
    link_path = cwd / LINK_REL
    if link_path.exists():
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("motor_root"):
                return Path(data["motor_root"])
        except (json.JSONDecodeError, OSError):
            pass
    env_root = os.environ.get("AGENT_PROJECT_ROOT")
    if env_root:
        p = Path(env_root)
        if (p / ".agent" / "agent_controller.py").exists():
            return p
        link_path = p / LINK_REL
        if link_path.exists():
            try:
                data = json.loads(link_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("motor_root"):
                    return Path(data["motor_root"])
            except (json.JSONDecodeError, OSError):
                pass
    return None


def scan_links(search_root: Path) -> dict[str, list[Path]]:
    """Scan search_root one level deep for motor_destination_link.json.

    Before: search_root is parent(motor_root).
    During: iterates search_root/*/.agent/config/motor_destination_link.json,
            reads ticket_prefix + destination_root from each. Skips links
            with null/missing prefix or destination.
    After: returns dict prefix -> list of destination_roots (list for
          duplicate detection; singleton when unique).
    """
    mapping: dict[str, list[Path]] = {}
    if not search_root.exists():
        return mapping
    for child in sorted(search_root.iterdir()):
        if child.name.startswith("."):
            continue
        link_path = child / LINK_REL
        if not link_path.exists():
            continue
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        prefix = data.get("ticket_prefix")
        dest = data.get("destination_root")
        if not prefix or not dest:
            continue
        mapping.setdefault(prefix, []).append(Path(dest))
    return mapping


def load_overrides() -> dict[str, Path]:
    """Load prefix_resolver.local.json overrides (gitignored, optional).

    Before: LOCAL_OVERRIDES may or may not exist.
    During: reads JSON with {"overrides": {"PREFIX": "/path"}}.
    After: returns dict prefix -> Path, or empty if missing/malformed.
    """
    if not LOCAL_OVERRIDES.exists():
        return {}
    try:
        data = json.loads(LOCAL_OVERRIDES.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: Path(v) for k, v in data.get("overrides", {}).items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def resolve_prefix(prefix: str | None, motor_root: Path) -> Path | None:
    """Resolve a ticket prefix to a destination_root.

    Before: prefix is a short uppercase string (e.g. EXF, WOT); motor_root
            is the motor repository root.
    During: WOT -> motor_root (special case). Otherwise checks local overrides
            first, then scans parent(motor_root) for links. Returns None if
            prefix is None, not found, or ambiguous (duplicate).
    After: returns the destination_root Path, or None.
    """
    if prefix is None:
        return None
    if prefix == WOT_PREFIX:
        return motor_root
    overrides = load_overrides()
    if prefix in overrides:
        return overrides[prefix]
    mapping = scan_links(motor_root.parent)
    dests = mapping.get(prefix)
    if not dests:
        return None
    if len(dests) > 1:
        return None
    return dests[0]


def resolve_by_project_name(name: str, motor_root: Path) -> Path | None:
    """Resolve by destination_id (project directory name).

    Before: name is a project name (not a ticket ID).
    During: scans links, matches destination_id field.
    After: returns the destination_root Path, or None.
    """
    search_root = motor_root.parent
    if not search_root.exists():
        return None
    for child in sorted(search_root.iterdir()):
        link_path = child / LINK_REL
        if not link_path.exists():
            continue
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("destination_id") == name or child.name == name:
            dest = data.get("destination_root")
            if dest:
                return Path(dest)
    return None


def extract_prefix(ticket_or_project: str) -> str | None:
    """Extract prefix from a ticket ID, or return None for a project name.

    Before: ticket_or_project may be a ticket ID (WOT-2026-020t) or a
            project name (Extractor_Facturas_PDF_Seguro).
    During: matches against TICKET_ID_RE. If it matches, returns the prefix
            (group 1). If it looks malformed (MALFORMED_ID_RE), raises
            ValueError. Otherwise returns None (project name).
    After: returns prefix string, None, or raises ValueError.
    """
    if TICKET_ID_RE.match(ticket_or_project):
        return ticket_or_project.split("-")[0]
    if MALFORMED_ID_RE.match(ticket_or_project):
        raise ValueError(f"Malformed ticket ID: {ticket_or_project}")
    return None


def _git_executable() -> str | None:
    """Resolve the absolute path to the git executable, or None if missing.

    Satisfies ruff S607 (partial executable path) without a noqa: the
    literal string "git" is never passed to subprocess directly, only the
    resolved absolute path from shutil.which.
    """
    return shutil.which("git")


def _git_common_dir(path: Path) -> Path | None:
    """Resolve the absolute git-common-dir for path, or None on failure.

    Before: path is a directory that may or may not be a git worktree.
    During: invokes `git -C <path> rev-parse --path-format=absolute
            --git-common-dir` with check=False (never check=True unguarded).
            The --path-format=absolute flag is mandatory: without it, git
            returns a relative path (e.g. ".git") for the primary checkout
            of a worktree set, and Path(...).resolve() on that relative
            output resolves against the calling PROCESS cwd, not against
            <path> -- producing a false mismatch (verified live, see
            work_plan.md "Verificacion en vivo"). Do NOT use
            --absolute-git-dir: that returns the LINKED worktree's own
            git-dir (.git/worktrees/<name>), which never matches between
            sibling worktrees of the same repo.
    After: returns the resolved absolute Path, or None if path is not a
          git repo (non-zero returncode) or git is not on PATH
          (FileNotFoundError). Callers must treat None as fail-closed.
    """
    git = _git_executable()
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


def guard(ticket_or_project: str, cwd: Path, motor_root: Path) -> int:
    """Guard: is cwd the right repo to work ticket_or_project from?

    Before: ticket_or_project is a ticket ID or project name; cwd is the
            current working directory; motor_root is the motor root.
    During: extracts the prefix (or uses the project name). WOT is decided
            FIRST and WITHOUT resolving the prefix to a destination: the
            question for WOT is "is cwd the same git repo as motor_root"
            (any worktree of it -- the _dev worktree and the primary
            detached checkout are the SAME motor), answered by comparing
            git-common-dir. That answer does not depend on where the WOT
            prefix RESOLVES to, so this branch must not require a
            resolution: demanding one would make a missing or duplicate WOT
            link (resolve_prefix -> None -> exit 2) block every WOT ticket
            from the correct worktree. It also does NOT enforce write
            discipline (which worktree/branch to use for WOT belongs to
            scripts/check_worktree_topology.py, exclusively). If
            git-common-dir cannot be determined for either side (not a git
            repo, or git missing from PATH), fails closed: mismatch
            (exit 1), never a crash, never exit 0. All other prefixes
            resolve to a destination_root and keep the literal-path
            comparison, unchanged.
    After: returns 0 if match, 1 if mismatch, 2 if resolution fails.
          Prints to stderr on failure (NO bus event: runs before
          --bootstrap-ticket).
    """
    try:
        prefix = extract_prefix(ticket_or_project)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if prefix == WOT_PREFIX:
        cwd_common = _git_common_dir(cwd)
        motor_common = _git_common_dir(motor_root)
        if cwd_common is None or motor_common is None:
            print(
                f"[ERROR] Cannot determine git-common-dir for cwd={cwd} or "
                f"motor_root={motor_root}: not a git repository, or git not "
                "found on PATH",
                file=sys.stderr,
            )
            return 1
        if cwd_common != motor_common:
            print(
                f"[ERROR] Repo mismatch: '{ticket_or_project}' is a motor "
                f"ticket, but cwd is {cwd}, which is not a worktree of the "
                f"motor at {motor_root} (different git repo)",
                file=sys.stderr,
            )
            return 1
        return 0
    if prefix is not None:
        resolved = resolve_prefix(prefix, motor_root)
    else:
        resolved = resolve_by_project_name(ticket_or_project, motor_root)
    if resolved is None:
        print(
            f"[ERROR] Cannot resolve '{ticket_or_project}' to a destination",
            file=sys.stderr,
        )
        return 2
    if cwd.resolve() != resolved.resolve():
        print(
            f"[ERROR] Prefix mismatch: '{ticket_or_project}' resolves to "
            f"{resolved}, but cwd is {cwd}",
            file=sys.stderr,
        )
        return 1
    return 0


def _get_motor_root(args: argparse.Namespace) -> Path | None:
    if args.motor_root:
        return Path(args.motor_root)
    return discover_motor_root(Path.cwd())


def cmd_resolve(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    prefix = args.resolve
    if prefix is None:
        print("[ERROR] prefix is None (use --resolve <PREFIX>)", file=sys.stderr)
        return 2
    if not PREFIX_RE.match(prefix):
        print(f"[ERROR] Malformed prefix: {prefix}", file=sys.stderr)
        return 2
    resolved = resolve_prefix(prefix, motor_root)
    if resolved is None:
        print(f"[ERROR] Unknown or ambiguous prefix: {prefix}", file=sys.stderr)
        return 1
    print(str(resolved))
    return 0


def _collect_verify_issues(motor_root: Path) -> list[str]:
    """Collect verify issues: duplicates, unreachable, override collisions."""
    search_root = motor_root.parent
    mapping = scan_links(search_root)
    issues: list[str] = []
    for prefix, dests in sorted(mapping.items()):
        if len(dests) > 1:
            issues.append(
                f"DUPLICATE prefix '{prefix}' -> {len(dests)} destinations: "
                f"{[str(d) for d in dests]}"
            )
        issues.extend(
            f"UNREACHABLE prefix '{prefix}' -> {dest} (path does not exist)"
            for dest in dests
            if not dest.exists()
        )
    overrides = load_overrides()
    for prefix, dest in sorted(overrides.items()):
        if prefix in mapping:
            issues.append(f"OVERRIDE collision: '{prefix}' in both overrides and scan")
        if not dest.exists():
            issues.append(
                f"OVERRIDE unreachable: '{prefix}' -> {dest} (path does not exist)"
            )
    return issues


def cmd_verify(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    issues = _collect_verify_issues(motor_root)
    if issues:
        for issue in issues:
            print(f"[VERIFY] {issue}", file=sys.stderr)
        print(f"[VERIFY] {len(issues)} issue(s) found", file=sys.stderr)
        return 1
    mapping = scan_links(motor_root.parent)
    print(f"[VERIFY] OK: {len(mapping)} prefixes mapped, 0 issues")
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    motor_root = _get_motor_root(args)
    if motor_root is None:
        print("[ERROR] Cannot discover motor_root (use --motor-root)", file=sys.stderr)
        return 2
    return guard(args.guard, Path.cwd(), motor_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prefix resolver: maps ticket prefixes to destination repos."
    )
    parser.add_argument(
        "--motor-root",
        help="Path to the motor repo (auto-discovered if omitted).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--resolve",
        metavar="PREFIX",
        help="Resolve a prefix to its destination_root path.",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Re-scan and detect duplicates, drift, unreachable paths.",
    )
    group.add_argument(
        "--guard",
        metavar="TICKET_OR_PROJECT",
        help="Guard: resolve and compare with cwd (exit 1 on mismatch).",
    )
    args = parser.parse_args(argv)
    if args.resolve is not None:
        return cmd_resolve(args)
    if args.verify:
        return cmd_verify(args)
    if args.guard is not None:
        return cmd_guard(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
