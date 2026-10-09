#!/usr/bin/env python3
"""
Worktree content divergence detector (WOT-2026-038d).

PROBLEM
-------
Two worktrees of the same motor repo can silently diverge: each accumulates
commits the other never saw (uncommitted work, unpublished commits, a stale
checkout). Measured incident (2026-07-19): the memory archives of two
worktrees drifted to 106 vs 103 records with zero overlap-detection
mechanism; reconciled by hand (commit d6834c7), but nothing prevented the
next session from re-diverging the same way. A second, worse instance
(2026-07-28): `prompts/orchestrator_session_close_full_audit.md` had
IDENTICAL line count (288) in both worktrees but DIFFERENT content (one
normative line, 262) -- `wc -l` and modification time are both BLIND to
this: comparing by content HASH is the only check that catches it.

SCOPE
-----
Two surfaces, both git-tracked (NOT runtime/gitignored state):
- `.agent/runtime/memory/archive/observations.*.jsonl` (portable memory).
- `prompts/**/*.md` (canonical governance prompts).

Comparison is over the WORKING TREE content of each worktree path, never
`git diff`/`git log`: two worktrees can diverge via uncommitted work or
unpublished local commits (measured live on 2026-10-09: a merge commit
existed in one worktree's `main` but never reached `origin/main`), so a
git-history-based comparison would miss exactly the drift this script
exists to catch.

USAGE
-----
    python scripts/check_worktree_divergence.py \\
        --worktree-a <path> --worktree-b <path> [--json]

Exit codes:
    0 = no divergence found (every file present in one worktree is either
        absent in both, or byte-identical in both).
    1 = divergence found (file content differs, or a file exists in one
        worktree's scope but not the other's).
    2 = usage/config error (a given worktree path does not exist, or is not
        readable).

This is a COLLECTOR (witness), consistent with the project's CEM contract:
it reports signals (`divergent_files`, `only_in_a`, `only_in_b`), the agent
reading its output decides what to do about each one (reconcile by hand,
accept as deliberate per-line work, escalate). It never writes to either
worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ARCHIVE_GLOB = ".agent/runtime/memory/archive/observations.*.jsonl"
PROMPTS_GLOB = "prompts/**/*.md"


def _sha256_of(path: Path) -> str:
    """sha256 hex digest of path's exact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_files(worktree: Path, glob_pattern: str) -> dict[str, Path]:
    """Map of {relative_posix_path: absolute_path} for files matching glob_pattern
    under worktree, rooted at worktree itself (glob_pattern may contain `/`)."""
    return {
        p.relative_to(worktree).as_posix(): p
        for p in worktree.glob(glob_pattern)
        if p.is_file()
    }


def compare_worktrees(worktree_a: Path, worktree_b: Path) -> dict:
    """Compare the archive and prompts surfaces of two worktrees by content hash.

    Before: worktree_a and worktree_b are existing directories (the two
            worktree roots to compare); each may or may not have the scoped
            files present.
    During: for each of ARCHIVE_GLOB and PROMPTS_GLOB, builds the relative
            path -> absolute path map on both sides, computes the union of
            relative paths, and classifies each one: present in both with
            the SAME sha256 (match), present in both with a DIFFERENT
            sha256 (divergent_files), present only in A (only_in_a), or
            present only in B (only_in_b). Hash comparison, never `wc -l`
            or mtime: WOT-2026-038d's own 2026-07-28 amendment found a
            prompt with identical line count but different content.
    After: returns a dict with `divergent_files`, `only_in_a`, `only_in_b`
           (each a list of relative posix paths, sorted) and `scanned`
           (total relative paths considered across both surfaces). An
           empty result on all three lists means the worktrees match on
           every file the scope covers.
    """
    divergent_files: list[str] = []
    only_in_a: list[str] = []
    only_in_b: list[str] = []
    scanned = 0

    for glob_pattern in (ARCHIVE_GLOB, PROMPTS_GLOB):
        files_a = _relative_files(worktree_a, glob_pattern)
        files_b = _relative_files(worktree_b, glob_pattern)
        all_rel = sorted(set(files_a) | set(files_b))
        scanned += len(all_rel)

        for rel in all_rel:
            in_a = rel in files_a
            in_b = rel in files_b
            if in_a and not in_b:
                only_in_a.append(rel)
            elif in_b and not in_a:
                only_in_b.append(rel)
            else:
                if _sha256_of(files_a[rel]) != _sha256_of(files_b[rel]):
                    divergent_files.append(rel)

    return {
        "divergent_files": sorted(divergent_files),
        "only_in_a": sorted(only_in_a),
        "only_in_b": sorted(only_in_b),
        "scanned": scanned,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare memory archives and canonical prompts between two "
            "motor worktrees by content hash."
        )
    )
    parser.add_argument(
        "--worktree-a", required=True, type=Path, help="First worktree root."
    )
    parser.add_argument(
        "--worktree-b", required=True, type=Path, help="Second worktree root."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    return parser


def _print_human_report(result: dict, worktree_a: Path, worktree_b: Path) -> None:
    print(f"[check-worktree-divergence] escaneados {result['scanned']} ficheros")
    if result["divergent_files"]:
        print("[check-worktree-divergence] CONTENIDO DIVERGENTE:")
        for rel in result["divergent_files"]:
            print(f"  - {rel}")
    if result["only_in_a"]:
        print(f"[check-worktree-divergence] solo en {worktree_a}:")
        for rel in result["only_in_a"]:
            print(f"  - {rel}")
    if result["only_in_b"]:
        print(f"[check-worktree-divergence] solo en {worktree_b}:")
        for rel in result["only_in_b"]:
            print(f"  - {rel}")
    if not (result["divergent_files"] or result["only_in_a"] or result["only_in_b"]):
        print("[check-worktree-divergence] OK: sin divergencia detectada")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    worktree_a: Path = args.worktree_a.resolve()
    worktree_b: Path = args.worktree_b.resolve()

    for label, wt in (("--worktree-a", worktree_a), ("--worktree-b", worktree_b)):
        if not wt.is_dir():
            print(
                f"[check-worktree-divergence] ERROR: {label} no es un directorio: {wt}"
            )
            return 2

    result = compare_worktrees(worktree_a, worktree_b)
    has_divergence = bool(
        result["divergent_files"] or result["only_in_a"] or result["only_in_b"]
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human_report(result, worktree_a, worktree_b)

    return 1 if has_divergence else 0


if __name__ == "__main__":
    sys.exit(main())
