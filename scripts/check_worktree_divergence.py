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
Two surfaces, both git-tracked (NOT runtime/gitignored state), compared
DIFFERENTLY because they have different structure:

- `.agent/runtime/memory/archive/observations.*.jsonl` (portable memory):
  compared PER RECORD by `(topic, source_ticket)` -- the exact DoD wording
  and the same identity `bus.portable_memory_archive.record_key` already
  uses, so the reconciler and this detector never disagree on "the same
  lesson". A whole-file hash would only say "this file differs" on a
  500-record archive where ONE record changed, hiding which one; per-record
  comparison reports the actual divergent key (Codex Review 2 finding on
  commit ad2b461, 2026-10-09).
- `prompts/**/*.md` (canonical governance prompts): these have no record
  structure, so whole-FILE content hash is the right granularity -- the
  2026-07-28 incident this ticket cites (identical line count, different
  content on one normative line) is exactly what file-level sha256 catches.

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
    0 = no divergence found (every record/file present in one worktree is
        either absent in both, or identical in both).
    1 = divergence found (a record's content differs for the same
        (topic, source_ticket) key, a prompt file's content differs, or a
        record/file exists in one worktree's scope but not the other's).
    2 = usage/config error (a given worktree path does not exist, or a
        JSONL archive line could not be parsed).

This is a COLLECTOR (witness), consistent with the project's CEM contract:
it reports signals, the agent reading its output decides what to do about
each one (reconcile by hand, accept as deliberate per-line work, escalate).
It never writes to either worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from bus.portable_memory_archive import record_key  # noqa: E402


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


def _load_archive_records(path: Path) -> dict[tuple[str, str | None], dict[str, Any]]:
    """Parse a JSONL archive file into {record_key(): record}.

    Before: path is an existing archive file (one JSON object per line).
    During: parses each non-blank line; a line that fails to parse raises
            ValueError naming the file and line number (fail-closed: a
            corrupt archive must not be silently compared as if it were
            empty or skip the bad line unnoticed).
    After: returns a dict keyed by the SAME `record_key()` the reconciler
           uses, so this detector's notion of "the same lesson" can never
           diverge from `reconcile_portable_memory.py`'s.
    """
    records: dict[tuple[str, str | None], dict[str, Any]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: linea JSONL invalida: {exc}") from exc
        records[record_key(record)] = record
    return records


def _compare_archives(worktree_a: Path, worktree_b: Path) -> dict:
    """Per-RECORD comparison of every archive file present in either worktree.

    Before: worktree_a/worktree_b are existing directories.
    During: unions the archive filenames present in either worktree (a
            record divergence is reported per `(file, record_key)`, not
            merged across files -- the same key in two DIFFERENT monthly
            files is not the same comparison). For each shared filename,
            loads both sides' records and classifies each key: present in
            both with identical content (match, no signal), present in
            both with different content (divergent_records), present only
            in A (only_in_a_records) or only in B (only_in_b_records). A
            filename present in only one worktree contributes all its keys
            to the corresponding only_in_* list (the whole file is "only in
            A/B" at the record level, consistent with reporting signal per
            key rather than per file for this surface).
    After: returns {"divergent_records", "only_in_a_records",
           "only_in_b_records", "scanned_records"} -- each record list
           entry is "<relative_file_path>::<topic>::<source_ticket>" for a
           self-contained, greppable signal.
    """
    divergent: list[str] = []
    only_in_a: list[str] = []
    only_in_b: list[str] = []
    scanned = 0

    files_a = _relative_files(worktree_a, ARCHIVE_GLOB)
    files_b = _relative_files(worktree_b, ARCHIVE_GLOB)
    for rel in sorted(set(files_a) | set(files_b)):
        records_a = _load_archive_records(files_a[rel]) if rel in files_a else {}
        records_b = _load_archive_records(files_b[rel]) if rel in files_b else {}
        all_keys = sorted(
            set(records_a) | set(records_b), key=lambda k: (k[0], k[1] or "")
        )
        scanned += len(all_keys)
        for key in all_keys:
            topic, source_ticket = key
            signal = f"{rel}::{topic}::{source_ticket}"
            in_a = key in records_a
            in_b = key in records_b
            if in_a and not in_b:
                only_in_a.append(signal)
            elif in_b and not in_a:
                only_in_b.append(signal)
            elif records_a[key] != records_b[key]:
                divergent.append(signal)

    return {
        "divergent_records": sorted(divergent),
        "only_in_a_records": sorted(only_in_a),
        "only_in_b_records": sorted(only_in_b),
        "scanned_records": scanned,
    }


def _compare_prompts(worktree_a: Path, worktree_b: Path) -> dict:
    """Whole-FILE sha256 comparison for prompts (no record structure to key on).

    Before: worktree_a/worktree_b are existing directories.
    During: unions relative prompt paths present in either worktree;
            classifies each as only-in-one-side, or compares sha256 of the
            exact bytes on both sides. Hash, never `wc -l`/mtime: the
            2026-07-28 incident had IDENTICAL line counts with different
            content on one normative line.
    After: returns {"divergent_files", "only_in_a", "only_in_b",
           "scanned_files"}, relative posix paths.
    """
    divergent: list[str] = []
    only_in_a: list[str] = []
    only_in_b: list[str] = []

    files_a = _relative_files(worktree_a, PROMPTS_GLOB)
    files_b = _relative_files(worktree_b, PROMPTS_GLOB)
    all_rel = sorted(set(files_a) | set(files_b))

    for rel in all_rel:
        in_a = rel in files_a
        in_b = rel in files_b
        if in_a and not in_b:
            only_in_a.append(rel)
        elif in_b and not in_a:
            only_in_b.append(rel)
        elif _sha256_of(files_a[rel]) != _sha256_of(files_b[rel]):
            divergent.append(rel)

    return {
        "divergent_files": sorted(divergent),
        "only_in_a": sorted(only_in_a),
        "only_in_b": sorted(only_in_b),
        "scanned_files": len(all_rel),
    }


def compare_worktrees(worktree_a: Path, worktree_b: Path) -> dict:
    """Compare the archive (per-record) and prompts (per-file) surfaces of
    two worktrees. See `_compare_archives`/`_compare_prompts` for the
    per-surface contract; this merges both into one result dict with a
    combined `scanned` count for backward-compatible callers."""
    archives = _compare_archives(worktree_a, worktree_b)
    prompts = _compare_prompts(worktree_a, worktree_b)
    return {
        **archives,
        **prompts,
        "scanned": archives["scanned_records"] + prompts["scanned_files"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare memory archives (per record) and canonical prompts "
            "(per file) between two motor worktrees by content."
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


def _has_divergence(result: dict) -> bool:
    return bool(
        result["divergent_records"]
        or result["only_in_a_records"]
        or result["only_in_b_records"]
        or result["divergent_files"]
        or result["only_in_a"]
        or result["only_in_b"]
    )


def _print_section(label: str, entries: list[str]) -> None:
    if entries:
        print(f"[check-worktree-divergence] {label}:")
        for entry in entries:
            print(f"  - {entry}")


def _print_human_report(result: dict, worktree_a: Path, worktree_b: Path) -> None:
    print(
        f"[check-worktree-divergence] escaneados {result['scanned_records']} "
        f"records + {result['scanned_files']} prompts"
    )
    _print_section(
        "RECORDS DIVERGENTES (mismo topic+source_ticket)", result["divergent_records"]
    )
    _print_section(f"records solo en {worktree_a}", result["only_in_a_records"])
    _print_section(f"records solo en {worktree_b}", result["only_in_b_records"])
    _print_section("PROMPTS CON CONTENIDO DIVERGENTE", result["divergent_files"])
    _print_section(f"prompts solo en {worktree_a}", result["only_in_a"])
    _print_section(f"prompts solo en {worktree_b}", result["only_in_b"])
    if not _has_divergence(result):
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

    try:
        result = compare_worktrees(worktree_a, worktree_b)
    except ValueError as exc:
        print(f"[check-worktree-divergence] ERROR: {exc}")
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human_report(result, worktree_a, worktree_b)

    return 1 if _has_divergence(result) else 0


if __name__ == "__main__":
    sys.exit(main())
