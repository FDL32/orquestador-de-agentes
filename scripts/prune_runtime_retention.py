#!/usr/bin/env python3
"""Opt-in local retention for gitignored runtime artifacts (WOT-2026-013l).

Standalone, opt-in CLI that applies count-based retention over three LOCAL,
gitignored runtime surfaces of a destination workspace, WITHOUT touching
versioned history, producers, or the closeout lifecycle.

Target surfaces (and ONLY these):
  - .agent/runtime/reviews/                       (one directory per ticket)
  - .agent/runtime/review_packets/                (<ticket>_attempt-N.md files)
  - .agent/runtime/memory/observations.jsonl.bak.*  (timestamped backup files)
  - .agent/collaboration/archive/notifications_*.md  (archived notif snapshots,
    WOT-2026-013k; name-filtered: notifications.md and every other archive file
    are excluded)

Recency semantics (WOT-2026-013v): "newest" is the mtime of each candidate ENTRY
itself. For review_packets and observation baks the entry is a file, so its mtime
is the artifact's own mtime. For reviews/ the entry is the ticket DIRECTORY, so
recency is the DIRECTORY's mtime -- NOT the most recent file inside it ("last
logical attempt"). On most filesystems a directory's mtime changes when direct
entries are added/removed, not when nested files are edited, so the two can
diverge. This is intentional and documented; ranking reviews/ by the newest
nested file would be a separate, explicitly-approved change.

Hard safety invariant: a candidate is selected for pruning ONLY if it is
directly contained in one of the fixed roots above AND, for name-filtered
surfaces, matches the surface's pattern. Versioned/useful history surfaces
(events/archive, audits/system_health, collaboration/_archive) are NEVER
reachable. collaboration/archive/ is reachable ONLY for the
notifications_<timestamp>.md family (WOT-2026-013k); every other file there
(review_queue_*.md, manager_feedback, recovered_*, relaunch_capsules, ...) is
never a candidate.

Usage:
    python scripts/prune_runtime_retention.py --project-root <repo_destino> \
        (--dry-run | --apply) \
        [--keep-reviews N] [--keep-packets N] [--keep-observation-baks N]

Exactly one of --dry-run / --apply is required: the script never deletes unless
--apply is explicitly declared.

Before:
  - --project-root must point at a workspace with a .agent/ directory.
During:
  - Read-only scan of the three roots; selects the OLDEST entries beyond the
    keep-count of each surface (newest kept; deterministic by mtime then name).
  - --dry-run: prints what WOULD be removed; touches nothing on disk.
  - --apply: removes the selected candidates (rmtree for review dirs, unlink for
    packet/bak files).
After:
  - Returns 0 on success, 1 on usage/path errors. dry-run NEVER deletes.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


# --- Surface contract -------------------------------------------------------

# Backup filename prefix inside the memory dir.
_OBSERVATION_BAK_PREFIX = "observations.jsonl.bak."

# WOT-2026-013k: archived notification snapshots live in collaboration/archive/
# as `notifications_<timestamp>.md` (producer: agent_controller.archive_old_
# notifications). The family is matched by BOTH a prefix and a suffix so the live
# `notifications.md`, `review_queue_*.md`, `manager_feedback`, recovered_* and any
# other collaboration/archive/ artifact are NEVER candidates.
_NOTIFICATION_ARCHIVE_PREFIX = "notifications_"
_NOTIFICATION_ARCHIVE_SUFFIX = ".md"

# Default keep-counts: conservative. None of these may default to 0 (which would
# delete everything); the operator opts into aggressiveness explicitly.
DEFAULT_KEEP_REVIEWS = 20
DEFAULT_KEEP_PACKETS = 20
DEFAULT_KEEP_OBSERVATION_BAKS = 10
DEFAULT_KEEP_NOTIFICATION_ARCHIVES = 20


@dataclass(frozen=True)
class Surface:
    """A prunable runtime surface rooted at a fixed relative path."""

    key: str
    rel_root: str  # relative to <project_root>/.agent
    entry_is_dir: bool  # reviews -> dir per ticket; others -> files
    keep_arg: str  # CLI dest holding the keep-count


SURFACES: tuple[Surface, ...] = (
    Surface("reviews", "runtime/reviews", True, "keep_reviews"),
    Surface("review_packets", "runtime/review_packets", False, "keep_packets"),
    Surface(
        "observation_baks",
        "runtime/memory",
        False,
        "keep_observation_baks",
    ),
    # WOT-2026-013k: archived notification snapshots, name-filtered so only the
    # `notifications_<timestamp>.md` family is prunable (not other archive files).
    Surface(
        "notification_archives",
        "collaboration/archive",
        False,
        "keep_notification_archives",
    ),
)


# --- Path resolution --------------------------------------------------------


def _agent_dir(project_root: Path) -> Path:
    return project_root / ".agent"


def _surface_root(project_root: Path, surface: Surface) -> Path:
    return _agent_dir(project_root) / surface.rel_root


def _is_contained(child: Path, root: Path) -> bool:
    """True iff `child` is the root or strictly inside it (resolved)."""
    try:
        child_r = child.resolve()
        root_r = root.resolve()
    except OSError:
        return False
    return child_r == root_r or root_r in child_r.parents


# --- Candidate selection ----------------------------------------------------


def _entry_is_candidate(surface: Surface, entry: Path) -> bool:
    """Whether a direct child of a surface root qualifies as a prunable entry.

    Name-filtered surfaces accept ONLY their family, so unrelated siblings are
    never candidates:
      - observation_baks: files named ``observations.jsonl.bak.*`` (MEMORY.md,
        observations.jsonl, archive/ are excluded).
      - notification_archives: files named ``notifications_<ts>.md`` (the live
        notifications.md, review_queue_*.md, manager_feedback, recovered_*, and
        any other collaboration/archive/ file are excluded).
      - other surfaces: dir-vs-file by ``surface.entry_is_dir``.
    """
    if surface.key == "observation_baks":
        return entry.is_file() and entry.name.startswith(_OBSERVATION_BAK_PREFIX)
    if surface.key == "notification_archives":
        return (
            entry.is_file()
            and entry.name.startswith(_NOTIFICATION_ARCHIVE_PREFIX)
            and entry.name.endswith(_NOTIFICATION_ARCHIVE_SUFFIX)
        )
    return entry.is_dir() if surface.entry_is_dir else entry.is_file()


def _list_surface_entries(project_root: Path, surface: Surface) -> list[Path]:
    """Return the direct entries of a surface that are prunable candidates."""
    root = _surface_root(project_root, surface)
    if not root.is_dir():
        return []

    entries: list[Path] = []
    for entry in root.iterdir():
        # Defense in depth: the entry must be a direct child of the fixed root.
        if entry.parent.resolve() != root.resolve():
            continue
        if not _is_contained(entry, root) or entry.resolve() == root.resolve():
            continue
        if _entry_is_candidate(surface, entry):
            entries.append(entry)
    return entries


def _sort_newest_first(entries: list[Path]) -> list[Path]:
    """Deterministic order: newest mtime first, tie-break by name desc.

    Newest first means the keep-count slices off the head to KEEP and the tail
    is pruned.
    """

    def key(p: Path) -> tuple[float, str]:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (mtime, p.name)

    return sorted(entries, key=key, reverse=True)


def select_candidates(project_root: Path, surface: Surface, keep: int) -> list[Path]:
    """Select prunable candidates for one surface, keeping the `keep` newest.

    Raises ValueError if `keep` is negative. Returns the OLDEST entries beyond
    the keep-count. All returned paths are guaranteed to be contained in the
    surface root (never a versioned/history surface).
    """
    if keep < 0:
        raise ValueError(f"keep count for {surface.key} must be >= 0, got {keep}")
    ordered = _sort_newest_first(_list_surface_entries(project_root, surface))
    candidates = ordered[keep:]
    # Final hard guard: every candidate MUST be inside the surface root.
    root = _surface_root(project_root, surface)
    for cand in candidates:
        if not _is_contained(cand, root) or cand.resolve() == root.resolve():
            raise RuntimeError(f"refusing to prune {cand}: escapes surface root {root}")
    return candidates


def select_all(project_root: Path, keeps: dict[str, int]) -> dict[str, list[Path]]:
    """Select candidates for every surface. Returns {surface_key: [paths]}.

    A surface whose keep-arg is absent from `keeps` is treated as keep-all (no
    candidates): for a deletion tool, an omitted keep-count must NEVER fall
    through to pruning. The CLI always supplies every keep via defaults.
    """
    result: dict[str, list[Path]] = {}
    for surface in SURFACES:
        if surface.keep_arg not in keeps:
            result[surface.key] = []
            continue
        keep = keeps[surface.keep_arg]
        result[surface.key] = select_candidates(project_root, surface, keep)
    return result


# --- Removal ----------------------------------------------------------------


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def prune(selection: dict[str, list[Path]], *, apply: bool) -> dict[str, list[str]]:
    """Print/remove the selection. With apply=False, NOTHING is deleted.

    Returns {surface_key: [str(path), ...]} of the paths that were (or would be)
    removed, for auditability.
    """
    report: dict[str, list[str]] = {}
    for surface in SURFACES:
        paths = selection.get(surface.key, [])
        report[surface.key] = [str(p) for p in paths]
        for path in paths:
            if apply:
                _remove(path)
    return report


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in local retention for gitignored local artifacts "
            "(reviews, review_packets, observations.jsonl.bak.*, "
            "collaboration/archive/notifications_*.md)."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Destination workspace root (must contain .agent/).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed without deleting anything.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually remove the selected candidates.",
    )
    parser.add_argument(
        "--keep-reviews",
        type=int,
        default=DEFAULT_KEEP_REVIEWS,
        help=(
            "Keep the newest N review dirs, ranked by DIRECTORY mtime "
            "(not the newest file inside the dir; default "
            f"{DEFAULT_KEEP_REVIEWS})."
        ),
    )
    parser.add_argument(
        "--keep-packets",
        type=int,
        default=DEFAULT_KEEP_PACKETS,
        help=f"Keep the newest N review packets (default {DEFAULT_KEEP_PACKETS}).",
    )
    parser.add_argument(
        "--keep-observation-baks",
        type=int,
        default=DEFAULT_KEEP_OBSERVATION_BAKS,
        help=(
            "Keep the newest N observations.jsonl.bak.* files "
            f"(default {DEFAULT_KEEP_OBSERVATION_BAKS})."
        ),
    )
    parser.add_argument(
        "--keep-notification-archives",
        type=int,
        default=DEFAULT_KEEP_NOTIFICATION_ARCHIVES,
        help=(
            "Keep the newest N collaboration/archive/notifications_*.md snapshots "
            f"(default {DEFAULT_KEEP_NOTIFICATION_ARCHIVES}); never touches "
            "notifications.md or other archive files."
        ),
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    args = _build_parser().parse_args(argv)

    project_root: Path = args.project_root
    if not _agent_dir(project_root).is_dir():
        print(
            f"Error: {project_root} has no .agent/ directory",
            file=sys.stderr,
        )
        return 1

    keeps = {
        "keep_reviews": args.keep_reviews,
        "keep_packets": args.keep_packets,
        "keep_observation_baks": args.keep_observation_baks,
        "keep_notification_archives": args.keep_notification_archives,
    }
    try:
        selection = select_all(project_root, keeps)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    apply = bool(args.apply)
    mode = "APPLY" if apply else "DRY-RUN"
    report = prune(selection, apply=apply)

    total = sum(len(v) for v in report.values())
    print(f"[{mode}] retention over 4 gitignored local surfaces")
    print("  (reviews recency = DIRECTORY mtime, not the newest file inside the dir)")
    for surface in SURFACES:
        paths = report[surface.key]
        verb = "removed" if apply else "would remove"
        print(f"  {surface.key}: {verb} {len(paths)}")
        for p in paths:
            print(f"    - {p}")
    print(f"[{mode}] total {'removed' if apply else 'would remove'}: {total}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
