#!/usr/bin/env python3
"""Git-recoverable artifact classification and pruning (WOT-2026-049b, 152i).

Classifies files under a surface directory as SAFE (the CURRENT bytes of the
file exist in git, committed at THAT path) or RISKY (anything else) and prunes
the recoverable ones conservatively.

Usage:
    python scripts/prune_git_recoverable.py --project-root <repo> \\
        [--dry-run | --apply] \\
        [--surface RUTA_RELATIVA] \\
        [--confirm-risky RUTA1 [RUTA2 ...]]

Modes (4):
    (no mode) / --dry-run
        Lists SAFE, RISKY, EXCLUDED and SKIPPED files with counts, paths and
        byte sizes. NEVER deletes anything. Exits 0. This is the default.

    --apply (without --confirm-risky)
        Deletes ONLY the SAFE files. RISKY files are reported and never
        touched in this invocation. Exits 0.

    --apply --confirm-risky RUTA1 RUTA2 ...
        Deletes the SAFE files AND the RISKY files whose paths are listed
        verbatim in --confirm-risky AND match exactly against the RISKY set
        computed in THIS RUN. If any --confirm-risky path is NOT in the RISKY
        set of this run (typo, already SAFE, nonexistent, outside surface,
        protected), the script DELETES NOTHING at all: fail-closed, exit 2.
        ``--confirm-risky`` with no paths, or without ``--apply``, is an
        error (exit 2): a confirmation flag is never silently ignored.

    --help
        Documents the contract above and exits 0.

Invariant: WITHOUT ``--confirm-risky`` a file is only deleted when the git
hash of its current bytes (after git's own clean filters, so EOL conversion
follows the repo config) is the blob committed at the same path in some
commit reachable from a branch, tag or remote-tracking ref. Rewritten,
never-committed, added-but-not-committed or renamed content is RISKY.
Anything uncertain is RISKY or SKIPPED, never deleted.

The ONE exception is a RISKY file named verbatim in ``--confirm-risky``: it is
deleted although its bytes are NOT in git (a human decision, by design). For
those only the type (regular file), the absence of links on the path and the
protected list are re-verified immediately before the unlink, not the blob.

git failures are never read as "not in git". If, DURING CLASSIFICATION, git
cannot run, ``git log`` or ``git hash-object`` fails on a file that still
exists, or their output cannot be parsed strictly (an unexpected header, token
or status is an error, not "no history"), the run aborts with exit 1 before
deleting anything (a file that vanished between listing and hashing is simply
dropped). That guarantee covers ONLY classification: deletion is sequential,
so a git failure while re-verifying a file DURING APPLICATION refuses only that
file ("Refused: ..." on stderr, exit 1) and files already unlinked before it
stay deleted (partial deletion is possible, each one verified on its own).
Paths git reports with non-UTF-8 bytes are decoded losslessly
(surrogateescape), so they never equal a real on-disk name and stay out of
SAFE.

Protected (never SAFE, never RISKY, never deletable, not even with
--confirm-risky): the canonical triage pair and its siblings (see
``_PROTECTED_PREFIXES``) and anything named ``.git``. Symlinks, junctions and
non-regular files are SKIPPED. Exit codes: 0 ok, 1 environment/surface/git
failure or refused candidates, 2 argument/confirmation misuse.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Names (case-insensitive prefixes of ANY path component) that are NEVER
# touched. Measured 2026-11-02 against the workspace reports/ directory, the
# .gitignore allowlist of that directory and the consumers in scripts/ and
# prompts/ (globs ``backlog_triage_*``, ``batch_run_*.json``,
# ``start_context_isolation*.json``, ``audit_autonomous_batch_*``,
# ``audit_gemela_*``, ``MUTATION_WOT-*.md`` and the ``integration_receipts``
# directory). ``_dag``/``_build_dag``/``_dead_dags`` are doubtful DAG material
# and are protected by the rule "doubtful name => do not delete".
_PROTECTED_PREFIXES: tuple[str, ...] = (
    "backlog_triage",
    "batch_run",
    "start_context_isolation",
    "audit_autonomous_batch",
    "audit_gemela",
    "integration_receipts",
    "mutation_wot-",
    "_dag",
    "_build_dag",
    "_dead_dags",
)
_PROTECTED_EXACT: tuple[str, ...] = (".git",)

_HASH_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ZERO_HASH_RE = re.compile(r"^0+$")
_RAW_HEADER_RE = re.compile(
    r"^:[0-7]{6} [0-7]{6} [0-9a-f]{40}(?:[0-9a-f]{24})? "
    r"(?P<new>[0-9a-f]{40}(?:[0-9a-f]{24})?) (?P<status>[ADMT])$"
)


class GitError(RuntimeError):
    """git could not be run or answered with a failure status."""


@dataclass(frozen=True)
class Classification:
    """Result of a classify run."""

    safe: list[str]  # relative POSIX paths whose current blob is in git
    risky: list[str]  # relative POSIX paths whose current blob is not in git
    safe_sizes: dict[str, int]  # bytes per safe file (by relative path)
    risky_sizes: dict[str, int]  # bytes per risky file
    excluded: list[str] = field(default_factory=list)  # protected, untouchable
    skipped: dict[str, str] = field(default_factory=dict)  # path -> reason
    safe_blobs: dict[str, str] = field(default_factory=dict)  # path -> blob
    surface: str = ""  # normalized surface that was classified


@dataclass(frozen=True)
class DeleteResult:
    """Outcome of ``_delete_files``: what went, what was refused and why."""

    deleted: list[str]
    refused: dict[str, str]


# --- Protection and path checks ----------------------------------------------


def is_protected(rel_path: str) -> bool:
    """True iff any component of ``rel_path`` is protected (never touched).

    Before: ``rel_path`` is a relative path with ``/`` separators.
    During: compares every component, case-insensitively, against the
        protected prefixes and exact names. No I/O.
    After: returns a bool; never raises.
    """
    for part in rel_path.replace("\\", "/").split("/"):
        low = part.casefold()
        if low in _PROTECTED_EXACT or low.startswith(_PROTECTED_PREFIXES):
            return True
    return False


def _is_junction(path: Path | str) -> bool:
    """True for a Windows junction; False where the platform has none."""
    fn = getattr(os.path, "isjunction", None)
    return bool(fn(path)) if fn is not None else False


def _is_link_like(project_root: Path, rel_path: str) -> bool:
    """True if ``rel_path`` or any parent under ``project_root`` is a symlink,
    a junction, or resolves somewhere other than where its name says.

    Fail-closed: an OS error while checking counts as link-like.
    """
    parts = rel_path.split("/")
    current = project_root
    try:
        for part in parts:
            current = current / part
            if current.is_symlink() or _is_junction(current):
                return True
        expected = Path(os.path.realpath(project_root)).joinpath(*parts)
        actual = os.path.realpath(project_root / rel_path)
    except OSError:
        return True
    return os.path.normcase(actual) != os.path.normcase(str(expected))


def _is_contained(candidate: Path, root: Path) -> bool:
    """True iff ``candidate`` is inside ``root`` (resolved paths)."""
    try:
        candidate_r = candidate.resolve()
        root_r = root.resolve()
    except OSError:
        return False
    return candidate_r == root_r or root_r in candidate_r.parents


def _validate_surface(project_root: Path, surface: str) -> str:
    """Return the normalized POSIX surface or raise.

    Before: ``project_root`` should be a directory; ``surface`` is user input.
    During: rejects absolute paths, drives, ``..``, the repo root itself
        (``.``/empty), any ``.git`` component and surfaces that are or cross a
        symlink/junction.
    After: returns ``a/b`` style relative path of an existing directory.
        Raises ``FileNotFoundError`` (missing root/surface) or ``ValueError``.
    """
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project root not found: {project_root}")
    raw = surface.replace("\\", "/")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    as_path = Path(surface)
    if (
        not parts
        or raw.startswith("/")
        or as_path.is_absolute()
        or as_path.drive
        or any(p == ".." for p in parts)
    ):
        raise ValueError(
            f"surface must be a relative path strictly inside the repo: {surface!r}"
        )
    if any(p.casefold() in _PROTECTED_EXACT for p in parts):
        raise ValueError(f"surface may not contain .git: {surface!r}")
    normalized = "/".join(parts)
    surface_dir = project_root / normalized
    if not surface_dir.is_dir():
        raise FileNotFoundError(f"Surface directory not found: {surface_dir}")
    if _is_link_like(project_root, normalized):
        raise ValueError(f"surface is or crosses a symlink/junction: {surface!r}")
    return normalized


# --- git access --------------------------------------------------------------


def _run_git(project_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run git on ``project_root`` with literal pathspecs; GitError on failure
    to execute. The caller checks ``returncode``."""
    cmd = ["git", "--literal-pathspecs", "-C", str(project_root), *args]
    try:
        return subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc


def _git_history(project_root: Path, surface: str) -> dict[str, set[str]]:
    """Map every path under ``surface`` to the blobs it ever held.

    Before: ``project_root`` is inside a git work tree.
    During: ONE ``git log --branches --tags --remotes --raw -z`` call (stash,
        notes and other refs are NOT trusted as recovery points); renames are
        off so a rename is a delete plus an add; ``--relative`` keeps paths
        relative to ``project_root``; ``core.quotePath=false`` + ``-z`` keep
        non-ASCII names intact; the output is decoded with ``surrogateescape``
        (lossless and injective) so undecodable path bytes never alias a
        real file name.
    After: ``{path: {blob, ...}}`` (deletions carry no blob). Raises
        ``GitError`` on a non-zero git status or on output that
        ``_parse_log_raw`` cannot parse strictly, so nothing is ever
        classified from a broken or misunderstood git.
    """
    proc = _run_git(
        project_root,
        [
            "-c",
            "core.quotePath=false",
            "log",
            "--branches",
            "--tags",
            "--remotes",
            "--no-renames",
            "--raw",
            "--no-abbrev",
            "-z",
            "--relative",
            "--pretty=format:",
            "--",
            surface,
        ],
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git log failed (rc={proc.returncode}): {detail}")
    # surrogateescape is lossless and injective: a git path with non-UTF-8
    # bytes becomes a string (lone surrogates) that no real on-disk name can
    # equal, so it can never alias another file. "replace" mapped many
    # byte strings onto U+FFFD and could make an unrelated file look committed.
    return _parse_log_raw(proc.stdout.decode("utf-8", errors="surrogateescape"))


def _parse_log_raw(output: str) -> dict[str, set[str]]:
    """Parse ``git log --raw -z --no-renames --pretty=format:`` STRICTLY.

    Before: ``output`` is the decoded stdout of that exact command.
    During: tokens are NUL-separated: ``:<mode> <mode> <old> <new> <status>``
        followed by exactly ONE path token (``--no-renames`` guarantees a
        single path, so ``R``/``C`` never appear). The path is consumed by
        position, so a file name that starts with ``:`` is just a path. Empty
        tokens (commit separators) are skipped. Anything else, a header that
        does not match, a status other than ``A M D T``, a deletion whose new
        hash is not all zeros, a non-deletion without a real new blob, an empty
        path or a stray token, is NOT read as "no history".
    After: ``{path: {blob, ...}}`` (a deletion adds the path with no blob).
        Raises ``GitError`` on any unexpected shape: nothing is ever classified
        from output that could not be understood.
    """
    history: dict[str, set[str]] = {}
    tokens = output.split("\0")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == "":
            continue
        match = _RAW_HEADER_RE.fullmatch(token)
        if match is None:
            raise GitError(f"unexpected token in git log --raw output: {token[:80]!r}")
        if index >= len(tokens) or tokens[index] == "":
            raise GitError(f"git log --raw header without a path: {token[:80]!r}")
        path = tokens[index]
        index += 1
        new_blob, status = match.group("new"), match.group("status")
        is_zero = bool(_ZERO_HASH_RE.match(new_blob))
        if status == "D":
            if not is_zero:
                raise GitError(f"git log --raw deletion with a blob: {token[:80]!r}")
            history.setdefault(path, set())
        else:
            if is_zero:
                raise GitError(f"git log --raw {status} without a blob: {token[:80]!r}")
            history.setdefault(path, set()).add(new_blob)
    return history


def _current_blob(project_root: Path, rel_path: str) -> str | None:
    """Git hash of the CURRENT bytes of ``rel_path`` (after clean filters).

    Before: ``project_root`` is a git work tree.
    During: one ``git hash-object`` call.
    After: returns the hash; returns ``None`` ONLY when the file no longer
        exists (it vanished between listing and hashing: not a git failure).
        Raises ``GitError`` when git cannot run, exits non-zero on a file that
        is still there (e.g. a failing clean filter) or prints something that
        is not a hash: "git failed" must never read as "content not in git".
    """
    proc = _run_git(project_root, ["hash-object", "--", rel_path])
    if proc.returncode != 0:
        if not os.path.lexists(project_root / rel_path):
            return None
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(
            f"git hash-object failed for {rel_path} (rc={proc.returncode}): {detail}"
        )
    blob = proc.stdout.decode("ascii", errors="replace").strip()
    if not _HASH_RE.match(blob):
        raise GitError(f"git hash-object gave no hash for {rel_path}: {blob!r}")
    return blob


# --- Core logic --------------------------------------------------------------


def _walk(
    project_root: Path,
    rel_dir: str,
    files: list[str],
    skipped: dict[str, str],
) -> None:
    """Collect regular files below ``rel_dir``; record the rest as skipped."""
    try:
        with os.scandir(project_root / rel_dir) as iterator:
            entries = sorted(iterator, key=lambda e: e.name)
    except OSError as exc:
        skipped[rel_dir] = f"unreadable directory ({type(exc).__name__})"
        return
    for entry in entries:
        rel = f"{rel_dir}/{entry.name}"
        try:
            if entry.is_symlink():
                skipped[rel] = "symlink"
            elif entry.is_dir(follow_symlinks=False):
                if _is_link_like(project_root, rel):
                    skipped[rel] = "junction or redirected directory"
                else:
                    _walk(project_root, rel, files, skipped)
            elif entry.is_file(follow_symlinks=False):
                files.append(rel)
            else:
                skipped[rel] = "not a regular file"
        except OSError as exc:
            skipped[rel] = f"unreadable ({type(exc).__name__})"


def _enumerate_files(
    project_root: Path, surface: str
) -> tuple[list[str], dict[str, str]]:
    """Return (regular files, skipped path->reason) under the surface."""
    files: list[str] = []
    skipped: dict[str, str] = {}
    _walk(project_root, surface, files, skipped)
    return files, skipped


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def classify(project_root: Path, surface: str) -> Classification:
    """Classify every regular file under ``surface``.

    Before: ``project_root`` is a git work tree containing ``surface``.
    During: one ``git log`` for the history of the surface, one directory walk
        (links skipped), one ``git hash-object`` per candidate whose path has
        history. SAFE = hash of the current bytes is one of the blobs that
        path held in a commit reachable from branches/tags/remotes. Protected
        paths go to ``excluded`` before anything else is looked at.
    After: returns a ``Classification``; deletes nothing. Raises
        ``FileNotFoundError``/``ValueError`` (bad root or surface) or
        ``GitError`` (git unusable, or ``hash-object`` failing on a file that
        still exists: nothing is classified from a broken git).
    """
    surface = _validate_surface(project_root, surface)
    history = _git_history(project_root, surface)
    file_list, skipped = _enumerate_files(project_root, surface)

    safe: list[str] = []
    risky: list[str] = []
    excluded: list[str] = []
    safe_sizes: dict[str, int] = {}
    risky_sizes: dict[str, int] = {}
    safe_blobs: dict[str, str] = {}

    for rel_path in file_list:
        if is_protected(rel_path):
            excluded.append(rel_path)
            continue
        size = _file_size(project_root / rel_path)
        blobs = history.get(rel_path, set())
        current = None
        if blobs:
            current = _current_blob(project_root, rel_path)
            if current is None:
                continue  # vanished between listing and hashing: nothing to do
        if current is not None and current in blobs:
            safe.append(rel_path)
            safe_sizes[rel_path] = size
            safe_blobs[rel_path] = current
        else:
            risky.append(rel_path)
            risky_sizes[rel_path] = size

    return Classification(
        safe=safe,
        risky=risky,
        safe_sizes=safe_sizes,
        risky_sizes=risky_sizes,
        excluded=excluded,
        skipped=skipped,
        safe_blobs=safe_blobs,
        surface=surface,
    )


def _refusal_reason(
    project_root: Path,
    rel_path: str,
    expected_blobs: dict[str, str] | None,
) -> str | None:
    """Why ``rel_path`` must NOT be unlinked right now, or ``None`` if it may.

    Re-checked immediately before each unlink: protected name, symlink or
    junction (the path or any parent), not a regular file, and, when
    ``expected_blobs`` is given, bytes that differ from the classified blob.
    """
    if is_protected(rel_path):
        return "protected path"
    if _is_link_like(project_root, rel_path):
        return "symlink or junction"
    try:
        is_regular = stat.S_ISREG(os.lstat(project_root / rel_path).st_mode)
    except OSError as exc:
        return f"cannot stat ({type(exc).__name__})"
    if not is_regular:
        return "not a regular file"
    if expected_blobs is not None:
        expected = expected_blobs.get(rel_path)
        try:
            current = _current_blob(project_root, rel_path)
        except GitError:
            return "cannot verify content (git failed)"
        if expected is None or current != expected:
            return "content changed since classification"
    return None


def _delete_files(
    rel_paths: list[str],
    project_root: Path,
    surface: str,
    expected_blobs: dict[str, str] | None = None,
) -> DeleteResult:
    """Delete the files at ``rel_paths`` (inside ``surface``), re-verifying
    each one immediately before its ``unlink``.

    Before: ``rel_paths`` come from ``classify`` (and, for RISKY, from a
        validated ``--confirm-risky``). ``expected_blobs`` maps a path to the
        blob it had when it was classified SAFE; pass it for SAFE deletions.
    During: per file: lexical/resolved containment inside the surface
        (``RuntimeError`` when it escapes), then absent => skipped silently,
        protected/link-like/non-regular => refused, blob changed since
        classification => refused, then ``unlink`` (OS error => refused).
    After: returns ``DeleteResult``; nothing outside ``surface`` is touched.
    """
    deleted: list[str] = []
    refused: dict[str, str] = {}
    surface_dir = project_root / surface
    for rel_path in rel_paths:
        file_path = project_root / rel_path
        if not _is_contained(file_path, surface_dir):
            raise RuntimeError(
                f"refusing to delete {file_path}: "
                f"not contained in surface {surface_dir}"
            )
        if not os.path.lexists(file_path):
            continue
        reason = _refusal_reason(project_root, rel_path, expected_blobs)
        if reason is None:
            try:
                file_path.unlink()
            except OSError as exc:
                reason = f"unlink failed ({type(exc).__name__})"
        if reason is None:
            deleted.append(rel_path)
        else:
            refused[rel_path] = reason
    return DeleteResult(deleted=deleted, refused=refused)


def _print_report(
    classification: Classification,
    mode: str,
) -> None:
    """Print a human-readable report of the classification."""
    safe_total = sum(classification.safe_sizes.values())
    risky_total = sum(classification.risky_sizes.values())

    print(f"[{mode}] surface classification")
    print(
        f"  SAFE (current bytes are committed at this path): "
        f"{len(classification.safe)} file(s), {safe_total} bytes"
    )
    for p in classification.safe:
        print(f"    - {p} ({classification.safe_sizes[p]} bytes)")

    print(
        f"  RISKY (bytes not in git at this path): "
        f"{len(classification.risky)} file(s), {risky_total} bytes"
    )
    for p in classification.risky:
        print(f"    - {p} ({classification.risky_sizes[p]} bytes)")

    print(
        f"  EXCLUDED (protected, never touched): {len(classification.excluded)} file(s)"
    )
    for p in classification.excluded:
        print(f"    - {p}")

    print(f"  SKIPPED (links/special/unreadable): {len(classification.skipped)}")
    for p, reason in classification.skipped.items():
        print(f"    - {p} ({reason})")

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


# --- CLI ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Classify files under a surface as SAFE (their current bytes are "
            "committed in git at that path) or RISKY and optionally prune the "
            "recoverable ones. "
            "\n\n"
            "Modes (4):\n"
            "  (no mode) / --dry-run  List SAFE/RISKY/EXCLUDED/SKIPPED, never\n"
            "                     deletes. Exit 0. This is the default.\n"
            "  --apply            Delete ONLY SAFE files; RISKY reported, untouched.\n"
            "                     Exit 0.\n"
            "  --apply --confirm-risky PATH ...  Also delete named RISKY files.\n"
            "    Each PATH must match EXACTLY a RISKY entry from THIS run.\n"
            "    If ANY path does not match, NOTHING is deleted (fail-closed),\n"
            "    exit 2 with stderr on the mismatch. Protected paths (the\n"
            "    canonical triage pair and siblings, .git) can never be named.\n"
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
            "(default: 'orchestrator_pipeline/reports'). The canonical triage "
            "pair inside it is always excluded."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without deleting anything (default when no mode).",
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
            "relative path. Requires --apply and at least one path. Every path "
            "must match a RISKY entry from THIS run. If any path does not match, "
            "the invocation aborts without deleting anything (fail-closed), exit 2."
        ),
    )
    return parser


def _validate_confirm_risky(
    confirmed_paths: list[str],
    risky_set: set[str],
    protected_set: frozenset[str] = frozenset(),
) -> tuple[int, list[str]]:
    """Validate --confirm-risky paths against the RISKY set.

    Returns (exit_code, validated_paths).  On mismatch returns (2, [])
    without touching the disk.  On success returns (0, confirmed_paths).
    """
    mismatches = [cp for cp in confirmed_paths if cp not in risky_set]

    if mismatches:
        for m in mismatches:
            why = " (protected path)" if m in protected_set else ""
            print(
                f"Error: --confirm-risky path not in RISKY set (mismatch){why}: {m}",
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
    """Entry point. Returns process exit code.

    Before: ``argv`` follows the CLI contract in the module docstring.
    During: validates flag combinations BEFORE touching git or the disk,
        classifies, prints the report, and (only with ``--apply``) deletes the
        SAFE files and the confirmed RISKY ones with per-file re-verification.
    After: 0 ok; 1 surface/git failure or some candidate refused at delete
        time; 2 flag misuse or ``--confirm-risky`` mismatch (nothing deleted).
    """
    args = _build_parser().parse_args(argv)

    flag_error = _confirm_flag_error(args)
    if flag_error is not None:
        print(f"Error: {flag_error}. NOTHING was deleted.", file=sys.stderr)
        return 2

    try:
        classification = classify(args.project_root, args.surface)
    except (FileNotFoundError, ValueError, GitError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not args.apply:
        _print_report(classification, "DRY-RUN")
        print("[DRY-RUN] no files deleted (default mode; use --apply to delete)")
        return 0

    # --apply: VALIDATE before touching disk.
    _print_report(classification, "APPLY")
    return _apply(classification, args.project_root, args.confirm_risky)


def _confirm_flag_error(args: argparse.Namespace) -> str | None:
    """Describe a misuse of ``--confirm-risky`` (no ``--apply``, no paths)."""
    if args.confirm_risky is None:
        return None
    if not args.apply:
        return "--confirm-risky requires --apply"
    if not args.confirm_risky:
        return "--confirm-risky needs at least one path"
    return None


def _apply(
    classification: Classification,
    project_root: Path,
    confirm_risky: list[str] | None,
) -> int:
    """Delete the SAFE files and the validated ``--confirm-risky`` ones.

    Before: ``classification`` is fresh from ``classify`` and flags are valid.
    During: validates ``--confirm-risky`` against the RISKY set (exit 2, nothing
        deleted, on mismatch), then deletes with per-file re-verification.
    After: 0 when everything requested was deleted, 1 when some candidate was
        refused or a path escaped the surface, 2 on confirmation mismatch.
    """
    mode = "APPLY"
    surface = classification.surface
    confirmed_paths: list[str] = []
    if confirm_risky:
        confirmed_paths = [
            _normalize_confirm_path(cp, project_root) for cp in confirm_risky
        ]
        exit_code, confirmed_paths = _validate_confirm_risky(
            confirmed_paths,
            set(classification.risky),
            frozenset(classification.excluded),
        )
        if exit_code == 2:
            return 2

    try:
        safe_result = _delete_files(
            classification.safe, project_root, surface, classification.safe_blobs
        )
        print(f"[{mode}] deleted {len(safe_result.deleted)} SAFE file(s)")

        if classification.risky:
            print("  RISKY files: not deleted (requires explicit --confirm-risky)")
            for p in classification.risky:
                print(f"    - {p} (requires --confirm-risky {p} to delete)")

        risky_result = DeleteResult(deleted=[], refused={})
        if confirmed_paths:
            risky_result = _delete_files(confirmed_paths, project_root, surface)
            print(
                f"[{mode}] deleted {len(risky_result.deleted)} confirmed RISKY file(s)"
            )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    refused = {**safe_result.refused, **risky_result.refused}
    for path, reason in refused.items():
        print(f"Refused: {path} ({reason})", file=sys.stderr)
    total_deleted = len(safe_result.deleted) + len(risky_result.deleted)
    print(f"[{mode}] total deleted: {total_deleted} file(s)")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(run())
