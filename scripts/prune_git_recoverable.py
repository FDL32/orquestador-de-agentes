#!/usr/bin/env python3
"""Git-recoverable artifact classification and pruning (WOT-2026-049b).

Classifies files under a surface directory as SAFE (ever tracked by git) or
RISKY (never seen by git log --all) and prunes the recoverable ones
conservatively.

Usage:
    python scripts/prune_git_recoverable.py --project-root <repo> \\
        (--dry-run | --apply) \\
        [--surface RUTA_RELATIVA] \\
        [--confirm-risky RUTA1 [RUTA2 ...]]

Modes (4):
    --dry-run
        Lists SAFE and RISKY files with counts, paths, and byte sizes.
        NEVER deletes anything. Exits 0.

    --apply (without --confirm-risky)
        Deletes ONLY the SAFE files. RISKY files are reported and
        never touched in this invocation. Exits 0.

    --apply --confirm-risky RUTA1 RUTA2 ...
        Deletes the SAFE files AND the RISKY files whose paths are listed
        verbatim in --confirm-risky AND match exactly against the RISKY
        set computed in THIS RUN. If any --confirm-risky path is NOT in the
        RISKY set of this run (typo, already SAFE, nonexistent, outside
        surface), the script DELETES NOTHING at all (neither SAFE nor
        RISKY): fail-closed. Exits 2 with clear stderr on the mismatch.

    --help
        Documents the contract above and exits 0.

Invariant: files under the surface are only deleted when git log --all
shows they were at some point tracked. A file that never appeared in
git history is never deleted without explicit --confirm-risky
acknowledgement.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Suppress: subprocess calls to local git binary, not user input.


@dataclass(frozen=True)
class Classification:
    """Result of a classify run."""

    safe: list[str]  # relative POSIX paths, ever tracked by git
    risky: list[str]  # relative POSIX paths, never tracked by git
    safe_sizes: dict[str, int]  # bytes per safe file (by relative path)
    risky_sizes: dict[str, int]  # bytes per risky file


# --- Core logic -------------------------------------------------------------


def _git_log_names(project_root: Path, surface: str) -> set[str]:
    """Return the set of file paths that have ever appeared under ``surface``
    in ANY commit of ANY branch.

    Single git invocation (not per-file):
        git -C <project_root> log --all --name-only --pretty=format: -- <surface>

    Returns a set of relative paths (one per non-empty line of stdout).
    """
    cmd: list[str] = [
        "git",
        "-C",
        str(project_root),
        "log",
        "--all",
        "--name-only",
        "--pretty=format:",
        "--",
        surface,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    tracked: set[str] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            tracked.add(stripped)
    return tracked


def _enumerate_files(project_root: Path, surface: str) -> list[str]:
    """Return a sorted list of relative POSIX paths for every file (not
    directory) under ``project_root / surface``, recursed."""
    surface_dir = project_root / surface
    files: list[str] = []
    for entry in sorted(surface_dir.rglob("*")):
        if entry.is_file() and not entry.is_symlink():
            try:
                rel = entry.relative_to(project_root).as_posix()
            except ValueError:
                continue
            files.append(rel)
    return files


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def classify(project_root: Path, surface: str) -> Classification:
    """Classify every file under ``surface`` as SAFE or RISKY.

    SAFE  = path appears at least once in ``git log --all --name-only`` for
            that surface.
    RISKY = path never appears in that git log output.

    Raises ``FileNotFoundError`` if the surface directory does not exist.
    """
    surface_dir = project_root / surface
    if not surface_dir.is_dir():
        raise FileNotFoundError(f"Surface directory not found: {surface_dir}")

    tracked = _git_log_names(project_root, surface)
    file_list = _enumerate_files(project_root, surface)

    safe: list[str] = []
    risky: list[str] = []
    safe_sizes: dict[str, int] = {}
    risky_sizes: dict[str, int] = {}

    for rel_path in file_list:
        file_path = project_root / rel_path
        size = _file_size(file_path)
        if rel_path in tracked:
            safe.append(rel_path)
            safe_sizes[rel_path] = size
        else:
            risky.append(rel_path)
            risky_sizes[rel_path] = size

    return Classification(
        safe=safe,
        risky=risky,
        safe_sizes=safe_sizes,
        risky_sizes=risky_sizes,
    )


def _is_contained(candidate: Path, root: Path) -> bool:
    """True iff ``candidate`` is inside ``root`` (resolved paths)."""
    try:
        candidate_r = candidate.resolve()
        root_r = root.resolve()
    except OSError:
        return False
    return candidate_r == root_r or root_r in candidate_r.parents


def _delete_files(rel_paths: list[str], project_root: Path, surface: str) -> list[str]:
    """Delete the files at the given relative paths (within surface).

    Each candidate is verified to be contained inside project_root/surface
    before unlinking. Returns list of deleted paths (as strings).

    Raises ``RuntimeError`` if a candidate escapes the surface.
    """
    deleted: list[str] = []
    surface_dir = project_root / surface
    for rel_path in rel_paths:
        file_path = project_root / rel_path
        if not _is_contained(file_path, surface_dir):
            raise RuntimeError(
                f"refusing to delete {file_path}: "
                f"not contained in surface {surface_dir}"
            )
        if file_path.exists():
            file_path.unlink()
            deleted.append(rel_path)
    return deleted


def _print_report(
    classification: Classification,
    mode: str,
) -> None:
    """Print a human-readable report of the classification."""
    safe_total = sum(classification.safe_sizes.values())
    risky_total = sum(classification.risky_sizes.values())

    print(f"[{mode}] surface classification")
    print(
        f"  SAFE (tracked by git): {len(classification.safe)} "
        f"file(s), {safe_total} bytes"
    )
    for p in classification.safe:
        print(f"    - {p} ({classification.safe_sizes[p]} bytes)")

    print(
        f"  RISKY (never tracked): {len(classification.risky)} "
        f"file(s), {risky_total} bytes"
    )
    for p in classification.risky:
        print(f"    - {p} ({classification.risky_sizes[p]} bytes)")

    print(
        f"  total: "
        f"{len(classification.safe) + len(classification.risky)} file(s), "
        f"{safe_total + risky_total} bytes"
    )


def _normalize_confirm_path(cp: str, project_root: Path) -> str:
    """Normalize a --confirm-risky path to a relative POSIX path."""
    cp_path = Path(cp)
    if cp_path.is_absolute():
        try:
            return cp_path.relative_to(project_root).as_posix()
        except ValueError:
            return cp_path.as_posix()
    return cp_path.as_posix()


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Classify files under a surface as SAFE (tracked by git log --all) "
            "or RISKY (never tracked) and optionally prune the recoverable ones. "
            "\n\n"
            "Modes (4):\n"
            "  --dry-run          List SAFE and RISKY, never deletes. Exit 0.\n"
            "  --apply            Delete ONLY SAFE files; RISKY reported, untouched.\n"
            "                     Exit 0.\n"
            "  --apply --confirm-risky PATH ...  Also delete named RISKY files.\n"
            "    Each PATH must match EXACTLY a RISKY entry from THIS run.\n"
            "    If ANY path does not match, NOTHING is deleted (fail-closed),\n"
            "    exit 2 with stderr on the mismatch.\n"
            "  --help             Document this contract and exit 0."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Repository root (must contain the surface directory).",
    )
    parser.add_argument(
        "--surface",
        default="orchestrator_pipeline/reports",
        help=(
            "Relative path to the surface directory under project-root "
            "(default: 'orchestrator_pipeline/reports')."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="List SAFE and RISKY files without deleting anything.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Delete SAFE files (and optionally named RISKY files with --confirm-risky).",
    )
    parser.add_argument(
        "--confirm-risky",
        nargs="*",
        default=None,
        help=(
            "Explicitly confirm deletion of specific RISKY files by their exact "
            "relative path. Every path must match a RISKY entry from THIS run. "
            "If any path does not match, the invocation aborts without deleting "
            "anything (fail-closed), exit 2."
        ),
    )
    return parser


def _validate_confirm_risky(
    confirmed_paths: list[str],
    risky_set: set[str],
) -> tuple[int, list[str]]:
    """Validate --confirm-risky paths against the RISKY set.

    Returns (exit_code, validated_paths).  On mismatch returns (2, [])
    without touching the disk.  On success returns (0, confirmed_paths).
    """
    mismatches = [cp for cp in confirmed_paths if cp not in risky_set]

    if mismatches:
        for m in mismatches:
            print(
                f"Error: --confirm-risky path not in RISKY set (mismatch): {m}",
                file=sys.stderr,
            )
        print(
            f"Error: {len(mismatches)} path(s) did not match RISKY set: "
            f"{', '.join(mismatches)}. NOTHING was deleted. "
            "Repeat the run to get a fresh classification.",
            file=sys.stderr,
        )
        return (2, [])

    return (0, confirmed_paths)


def run(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    args = _build_parser().parse_args(argv)
    project_root: Path = args.project_root
    surface: str = args.surface

    try:
        classification = classify(project_root, surface)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_report(classification, "DRY-RUN")
        print("[DRY-RUN] no files deleted")
        return 0

    # --apply: VALIDATE before touching disk.
    mode = "APPLY"
    _print_report(classification, mode)

    # Validate --confirm-risky BEFORE deleting anything.
    confirm_risky = args.confirm_risky
    confirmed_paths: list[str] = []
    if confirm_risky:
        risky_set = set(classification.risky)
        confirmed_paths = [
            _normalize_confirm_path(cp, project_root) for cp in confirm_risky
        ]
        exit_code, validated_paths = _validate_confirm_risky(confirmed_paths, risky_set)
        if exit_code == 2:
            return 2
        confirmed_paths = validated_paths

    # Phase 1: delete SAFE files.
    deleted_safe = _delete_files(classification.safe, project_root, surface)
    print(f"[{mode}] deleted {len(deleted_safe)} SAFE file(s)")

    if classification.risky:
        print("  RISKY files: not deleted (requires explicit --confirm-risky)")
        for p in classification.risky:
            print(f"    - {p} (requires --confirm-risky {p} to delete)")

    # Phase 2: delete confirmed RISKY files.
    deleted_risky_count = 0
    if confirmed_paths:
        deleted_risky = _delete_files(confirmed_paths, project_root, surface)
        deleted_risky_count = len(deleted_risky)
        print(f"[{mode}] deleted {deleted_risky_count} confirmed RISKY file(s)")

    total_deleted = len(deleted_safe) + deleted_risky_count
    print(f"[{mode}] total deleted: {total_deleted} file(s)")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
