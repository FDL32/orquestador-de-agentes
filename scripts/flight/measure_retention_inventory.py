"""Create labelled, read-only inventory photos for retention decisions.

Before: snapshot mode receives one or more absolute ``--root`` mappings, a
mandatory ``--out`` path outside every measured root, and a ``--flight-id``.
Compare mode receives two existing JSON photos and an exclusive output path.
During: walk only temporary or caller-selected trees, skip symbolic links and
Windows reparse points, collect age/family/git statistics, and write one JSON
artifact with exclusive creation. A user-selected root is intentionally
resolved to its destination; link entries inside the tree are still omitted.
No measured file is changed.
After: return 0 for a complete photo/compare, 1 when a root or comparison is
partial, and 2 for usage, validation, JSON, or output errors.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


SCHEMA_VERSION = 1
CHECK_EVERY = 64
REPARSE_POINT = 0x400
HISTOGRAM = ("0-1", "1-3", "3-7", "7-14", "14-30", "30-90", ">90")
_LETTERS = re.compile(r"^[A-Za-z]+")
_GIT = "git"


class UsageError(ValueError):
    """Raised for invalid command values before an artifact is written."""


def family_key(name: str) -> str:
    """Return a stable non-empty family key.

    Before: ``name`` is a filesystem basename, possibly hidden, numeric, or
    containing spaces and separators.
    During: strip the final suffix, classify hidden/nonnalphabetic names, take
    the leading letter token, and normalize it with ``casefold``.
    After: return a non-empty comparable key; no filesystem access occurs.
    """
    stem = Path(name).stem
    if name.startswith("."):
        return "(oculto)"
    match = _LETTERS.match(stem)
    if match is None:
        return "(sin-letras)"
    return match.group(0).casefold()


def _histogram(ages: list[float]) -> dict[str, int]:
    """Count exact ages in fixed left-inclusive buckets.

    Before: ``ages`` contains non-negative age values in days.
    During: assign each value to the contract's seven fixed buckets.
    After: return every bucket, including zero-count buckets, without I/O.
    """
    result = dict.fromkeys(HISTOGRAM, 0)
    for age in ages:
        if age < 1:
            key = "0-1"
        elif age < 3:
            key = "1-3"
        elif age < 7:
            key = "3-7"
        elif age < 14:
            key = "7-14"
        elif age < 30:
            key = "14-30"
        elif age <= 90:
            key = "30-90"
        else:
            key = ">90"
        result[key] += 1
    return result


def _is_reparse(path: Path) -> bool:
    """Detect symlinks and Windows reparse points without following them.

    Before: ``path`` names an entry in the tree and may be a junction.
    During: lstat the entry and inspect both the portable symlink bit and the
    Windows reparse-point attribute; errors are propagated to the caller.
    After: return true exactly when the entry must not be descended or counted.
    """
    stat_result = os.lstat(path)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & REPARSE_POINT)


def _git_root(root: Path) -> Path | None:
    """Find the repository owning a measured root.

    Before: ``root`` is an existing path candidate.
    During: ask Git using the root as cwd and suppress expected command errors.
    After: return the absolute repository root or None when no repository is
    available; no exception escapes for an ordinary non-repository tree.
    """
    if not _git_available():
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [_GIT, "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def _git_available() -> bool:
    """Check that the literal Git executable can be invoked.

    Before: the process may or may not expose Git on PATH.
    During: execute ``git --version`` without using filesystem paths supplied
    by the caller.
    After: return true only when Git exits successfully; expected OS failures
    become false and do not escape the inventory operation.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [_GIT, "--version"], capture_output=True, check=False, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _git_states(root: Path, files: list[Path]) -> dict[Path, str]:
    """Classify files as versioned, ignored, untracked, or outside Git.

    Before: ``files`` are paths found below ``root`` and may be empty.
    During: perform bulk Git index and ignore queries from the owning repo,
    preserving relative paths and never treating another repo's index as ours.
    After: return one state per input path; Git failures degrade to ``sin_repo``.
    """
    repo = _git_root(root)
    if repo is None:
        return {path: "sin_repo" for path in files}
    try:
        tracked_raw = subprocess.run(  # noqa: S603
            [_GIT, "ls-files", "-z", "--"],
            cwd=repo,
            capture_output=True,
            check=True,
            timeout=20,
        ).stdout
        relative = {path: path.resolve().relative_to(repo).as_posix() for path in files}
        tracked = {
            item.decode("utf-8", "surrogateescape")
            for item in tracked_raw.split(b"\0")
            if item
        }
        payload = "\0".join(relative.values()) + ("\0" if relative else "")
        ignored_raw = subprocess.run(  # noqa: S603
            [_GIT, "check-ignore", "-z", "--stdin"],
            cwd=repo,
            input=payload.encode("utf-8", "surrogateescape"),
            capture_output=True,
            check=False,
            timeout=20,
        ).stdout
        ignored = {
            item.decode("utf-8", "surrogateescape")
            for item in ignored_raw.split(b"\0")
            if item
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {path: "sin_repo" for path in files}
    return {
        path: (
            "versionado"
            if relative[path] in tracked
            else "ignorado"
            if relative[path] in ignored
            else "sin_seguimiento"
        )
        for path in files
    }


def _scan_root(root: Path, budget: float, now: float) -> dict[str, Any]:  # noqa: C901
    """Scan one root with bounded work and explicit traversal errors.

    Before: ``root`` is a resolved candidate; ``budget`` is non-negative and
    ``now`` is one captured epoch shared by this scan.
    During: use scandir/lstat, recheck a popped directory for reparse races,
    check the monotonic budget every 64 files, directories, and entries, skip
    symlinks and reparse points, and record stat/scandir failures.
    After: return counts, exact age statistics, families, git states, reasons,
    and completeness flags; no write or delete operation is performed.
    """
    result: dict[str, Any] = {
        "path": str(root),
        "files": 0,
        "bytes": 0,
        "oldest_age_days": None,
        "median_age_days": None,
        "histogram": dict.fromkeys(HISTOGRAM, 0),
        "families": {},
        "files_detail": [],
        "stat_errors": 0,
        "traversal_errors": [],
        "omitted_links": 0,
        "truncated": False,
        "partial": False,
        "absent": False,
        "reasons": [],
    }
    try:
        root.stat()
    except FileNotFoundError:
        result["absent"] = True
        result["partial"] = True
        result["reasons"].append("raiz ausente")
        return result
    except OSError as exc:
        result["partial"] = True
        result["reasons"].append(f"raiz ilegible: {type(exc).__name__}")
        return result
    start = time.monotonic()
    stack = [root]
    found: list[Path] = []
    mtimes: list[float] = []
    family_data: dict[str, list[float | int]] = defaultdict(lambda: [0, 0, []])
    processed = 0
    directories_processed = 0
    entries_processed = 0
    while stack:
        current = stack.pop()
        if current != root:
            try:
                if _is_reparse(current):
                    result["omitted_links"] += 1
                    continue
            except OSError as exc:
                result["traversal_errors"].append(f"{current}: {type(exc).__name__}")
                result["partial"] = True
                continue
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            result["traversal_errors"].append(f"{current}: {type(exc).__name__}")
            result["partial"] = True
            continue
        directories_processed += 1
        if (
            directories_processed % CHECK_EVERY == 0
            and time.monotonic() - start >= budget
        ):
            result["truncated"] = True
            result["partial"] = True
            result["reasons"].append("presupuesto agotado")
            break
        for entry in entries:
            path = Path(entry.path)
            entries_processed += 1
            if (
                entries_processed % CHECK_EVERY == 0
                and time.monotonic() - start >= budget
            ):
                result["truncated"] = True
                result["partial"] = True
                result["reasons"].append("presupuesto agotado")
                stack.clear()
                break
            try:
                if _is_reparse(path):
                    result["omitted_links"] += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat_result = os.stat(path, follow_symlinks=False)
            except OSError:
                result["stat_errors"] += 1
                result["partial"] = True
                continue
            processed += 1
            if processed % CHECK_EVERY == 0 and time.monotonic() - start >= budget:
                result["truncated"] = True
                result["partial"] = True
                result["reasons"].append("presupuesto agotado")
                stack.clear()
                break
            age = max(0.0, (now - stat_result.st_mtime) / 86400)
            found.append(path)
            mtimes.append(age)
            result["files"] += 1
            result["bytes"] += stat_result.st_size
            key = family_key(path.name)
            family_data[key][0] += 1
            family_data[key][1] += stat_result.st_size
            family_data[key][2].append(age)
        if result["truncated"]:
            break
    states = _git_states(root, found)
    result["files_detail"] = [
        {"name": path.name, "path": str(path.relative_to(root)), "git": states[path]}
        for path in found
    ]
    if mtimes:
        result["oldest_age_days"] = round(max(mtimes), 6)
        result["median_age_days"] = round(float(median(mtimes)), 6)
        result["histogram"] = _histogram(mtimes)
    result["families"] = {
        key: {
            "files": int(values[0]),
            "bytes": int(values[1]),
            "oldest_age_days": round(max(values[2]), 6),
            "median_age_days": round(float(median(values[2])), 6),
        }
        for key, values in sorted(family_data.items())
    }
    if result["stat_errors"]:
        result["reasons"].append("errores de stat")
    if result["traversal_errors"]:
        result["reasons"].append("errores de recorrido")
    return result


def _parse_roots(values: list[str]) -> list[tuple[str, Path]]:
    """Validate repeatable labelled absolute root arguments.

    Before: values are raw ``LABEL=PATH`` arguments from argparse.
    During: split once, reject duplicates/relative paths, and intentionally
    resolve each user-selected root to its destination; only entries inside
    the resulting tree are subject to link omission.
    After: return ordered unique labels and resolved absolute paths or raise
    UsageError.
    """
    roots: list[tuple[str, Path]] = []
    labels: set[str] = set()
    for raw in values:
        label, separator, raw_path = raw.partition("=")
        path = Path(raw_path)
        if not separator or not label or not raw_path or label in labels:
            raise UsageError(f"raiz invalida o repetida: {raw}")
        if not path.is_absolute():
            raise UsageError(f"la raiz debe ser absoluta: {raw}")
        labels.add(label)
        roots.append((label, path.resolve()))
    if not roots:
        raise UsageError("se requiere al menos una raiz")
    return roots


def _inside(path: Path, root: Path) -> bool:
    """Return whether a resolved output path is inside a measured root.

    Before: both paths are absolute candidates.
    During: compare normalized case-insensitive common paths.
    After: return true for the root itself or any descendant, without I/O.
    """
    try:
        return os.path.normcase(
            os.path.commonpath([str(path), str(root)])
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _validate_out(raw: str, roots: list[tuple[str, Path]]) -> Path:
    """Validate an exclusive output path before any scan or write.

    Before: ``raw`` is mandatory and roots have been parsed.
    During: resolve the path and reject descendants of measured roots.
    After: return the resolved output path or raise UsageError; no file opens.
    """
    output = Path(raw).resolve()
    if any(_inside(output, root) for _, root in roots):
        raise UsageError("--out debe estar fuera de todas las raices")
    return output


def _commit(root: Path) -> tuple[str | None, str | None]:
    """Read a repository HEAD without making it a photo prerequisite.

    Before: ``root`` may be a repository or an ordinary directory.
    During: ask Git for HEAD and convert failures into a reason.
    After: return ``(sha, reason)`` where exactly one is non-null.
    """
    repo = _git_root(root)
    if repo is None:
        return None, "no es un repositorio Git"
    try:
        result = subprocess.run(  # noqa: S603
            [_GIT, "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    if result.returncode != 0 or not result.stdout.strip():
        return None, "rev-parse fallo"
    return result.stdout.strip(), None


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Create exactly one UTF-8 JSON artifact without overwriting.

    Before: payload is serializable and path has passed semantic validation.
    During: verify that the parent already exists, then open the final path
    with O_EXCL; the parent is never created by this function.
    After: the artifact is fully written or an OSError propagates; an existing
    artifact is never overwritten.
    """
    if not path.parent.is_dir():
        raise OSError(f"directorio de salida inexistente: {path.parent}")
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
    except Exception:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise


def _snapshot(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Build and write one inventory photo.

    Before: snapshot arguments are validated and output is outside all roots.
    During: capture one UTC/epoch clock, scan each root, attach both requested
    commit identities, and publish counts/reasons inside the JSON photo.
    After: return photo and rc 0 or 1; output errors are raised for rc 2.
    """
    roots = _parse_roots(args.root)
    output = _validate_out(args.out, roots)
    if not args.flight_id:
        raise UsageError("--flight-id es obligatorio")
    if args.budget_seconds < 0 or not math.isfinite(args.budget_seconds):
        raise UsageError("--budget-seconds debe ser finito y no negativo")
    now = time.time()
    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(
        timespec="seconds"
    )
    if stamp.endswith("+00:00"):
        stamp = stamp[:-6] + "Z"
    records = {
        label: _scan_root(path, args.budget_seconds, now) for label, path in roots
    }
    commits: dict[str, Any] = {}
    motor_sha, motor_reason = _commit(Path(__file__).resolve().parents[2])
    commits["motor"] = motor_sha if motor_sha else {"sha": None, "reason": motor_reason}
    if args.workspace_root:
        workspace_sha, workspace_reason = _commit(Path(args.workspace_root).resolve())
        commits["workspace"] = (
            workspace_sha
            if workspace_sha
            else {"sha": None, "reason": workspace_reason}
        )
    measured = sum(not record["absent"] for record in records.values())
    partial = any(record["partial"] for record in records.values())
    photo: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": stamp,
        "flight_id": args.flight_id,
        "commits": commits,
        "denominator": {"requested": len(roots), "measured": measured},
        "partial": partial,
        "roots": records,
        "reasons": [
            f"{label}: {reason}"
            for label, record in records.items()
            for reason in record["reasons"]
        ],
    }
    if not partial:
        photo["total"] = {
            "files": sum(record["files"] for record in records.values()),
            "bytes": sum(record["bytes"] for record in records.values()),
        }
    _write_exclusive(output, photo)
    return photo, int(partial)


def _load_photo(path: Path) -> dict[str, Any]:
    """Load and validate one finite schema-versioned photo.

    Before: path names a candidate JSON file.
    During: parse JSON, reject wrong top-level shape/schema and non-finite
    numeric values, including deeply nested decoder recursion failures.
    After: return a dict photo or raise UsageError without writing anything.
    """

    def reject_constant(value: str) -> None:
        """Reject JSON NaN and infinity constants.

        Before: the JSON decoder supplies a non-standard numeric token.
        During: raise a value error before the photo can be accepted.
        After: no non-finite constant is returned to the caller.
        """
        raise ValueError(value)

    try:
        with path.open(encoding="utf-8") as handle:
            photo = json.load(
                handle,
                parse_constant=reject_constant,
            )
    except (OSError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise UsageError(f"foto ilegible: {path.name}: {type(exc).__name__}") from exc
    _validate_photo_structure(photo, path)

    def finite(value: Any) -> None:
        """Reject non-finite numbers recursively in a decoded photo.

        Before: ``value`` is any JSON-compatible scalar, list, or mapping.
        During: inspect every nested value and reject a non-finite float.
        After: return normally only when this subtree contains finite numbers.
        """
        if isinstance(value, float) and not math.isfinite(value):
            raise UsageError(f"numero no finito en {path.name}")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)

    finite(photo)
    return photo


def _validate_photo_structure(photo: Any, path: Path) -> None:  # noqa: C901
    """Validate the complete shape required by snapshot photos.

    Before: ``photo`` is decoded JSON from a candidate input path.
    During: verify top-level identity, denominator, roots, root counters,
    families, lists, and scalar types before comparison code reads them.
    After: return normally only for a snapshot-shaped object; raise
    ``UsageError`` with the path and field for every structural mismatch.
    """
    if not isinstance(photo, dict):
        raise UsageError(f"foto no es un objeto: {path.name}")
    if photo.get("mode") == "compare":
        raise UsageError(f"artefacto compare usado como foto: {path.name}")
    if photo.get("schema_version") != SCHEMA_VERSION:
        raise UsageError(f"schema_version invalida: {path.name}")
    required = (
        "captured_at",
        "flight_id",
        "commits",
        "denominator",
        "partial",
        "roots",
        "reasons",
    )
    missing = [field for field in required if field not in photo]
    if missing:
        raise UsageError(f"campos ausentes en {path.name}: {','.join(missing)}")
    if not isinstance(photo["captured_at"], str) or not photo["captured_at"]:
        raise UsageError(f"captured_at invalido en {path.name}")
    if not isinstance(photo["flight_id"], str) or not photo["flight_id"]:
        raise UsageError(f"flight_id invalido en {path.name}")
    if not isinstance(photo["commits"], dict):
        raise UsageError(f"commits invalido en {path.name}")
    denominator = photo["denominator"]
    if not isinstance(denominator, dict):
        raise UsageError(f"denominator invalido en {path.name}")
    for field in ("requested", "measured"):
        value = denominator.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise UsageError(f"denominator.{field} invalido en {path.name}")
    if not isinstance(photo["partial"], bool):
        raise UsageError(f"partial invalido en {path.name}")
    if not isinstance(photo["roots"], dict):
        raise UsageError(f"roots invalido en {path.name}")
    if not isinstance(photo["reasons"], list):
        raise UsageError(f"reasons invalido en {path.name}")
    root_fields = (
        "files",
        "bytes",
        "oldest_age_days",
        "median_age_days",
        "histogram",
        "families",
        "files_detail",
        "stat_errors",
        "traversal_errors",
        "omitted_links",
        "truncated",
        "partial",
        "absent",
        "reasons",
    )
    family_fields = ("files", "bytes", "oldest_age_days", "median_age_days")
    for label, record in photo["roots"].items():
        if not isinstance(label, str) or not isinstance(record, dict):
            raise UsageError(f"raiz invalida en {path.name}")
        missing = [field for field in root_fields if field not in record]
        if missing:
            raise UsageError(
                f"campos de raiz ausentes en {path.name}: {','.join(missing)}"
            )
        for field in ("files", "bytes", "stat_errors", "omitted_links"):
            value = record[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise UsageError(f"{label}.{field} invalido en {path.name}")
        for field in ("partial", "truncated", "absent"):
            if not isinstance(record[field], bool):
                raise UsageError(f"{label}.{field} invalido en {path.name}")
        if not isinstance(record["histogram"], dict) or not isinstance(
            record["families"], dict
        ):
            raise UsageError(f"{label}.histogram/families invalido en {path.name}")
        if (
            not isinstance(record["files_detail"], list)
            or not isinstance(record["traversal_errors"], list)
            or not isinstance(record["reasons"], list)
        ):
            raise UsageError(f"listas de raiz invalidas en {path.name}")
        for field in ("oldest_age_days", "median_age_days"):
            value = record[field]
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise UsageError(f"{label}.{field} invalido en {path.name}")
        for family, details in record["families"].items():
            if not isinstance(family, str) or not isinstance(details, dict):
                raise UsageError(f"familia invalida en {path.name}")
            if any(field not in details for field in family_fields):
                raise UsageError(f"campos de familia ausentes en {path.name}")
            for field in ("files", "bytes"):
                value = details[field]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise UsageError(f"familia.{field} invalida en {path.name}")


def _compare(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Calculate signed root and family deltas between two photos.

    Before: two compatible JSON paths and an exclusive output path exist.
    During: load both photos, compare every union root/family, and propagate
    partial status from either side; differing flight IDs become a warning.
    After: write one compare artifact and return rc 0 or 1, or raise UsageError.
    """
    output = Path(args.out).resolve()
    first = _load_photo(Path(args.compare[0]))
    second = _load_photo(Path(args.compare[1]))
    if first.get("flight_id") != second.get("flight_id"):
        warning = "flight_id distinto entre fotos"
    else:
        warning = None
    deltas: dict[str, Any] = {}
    partial = bool(first.get("partial") or second.get("partial"))
    labels = set(first.get("roots", {})) | set(second.get("roots", {}))
    for label in sorted(labels):
        left = first.get("roots", {}).get(label, {})
        right = second.get("roots", {}).get(label, {})
        root_partial = bool(
            left.get("partial")
            or right.get("partial")
            or left.get("truncated")
            or right.get("truncated")
        )
        partial = partial or root_partial
        families: dict[str, Any] = {}
        family_names = set(left.get("families", {})) | set(right.get("families", {}))
        for name in sorted(family_names):
            before = left.get("families", {}).get(name, {})
            after = right.get("families", {}).get(name, {})
            families[name] = {
                "files_delta": after.get("files", 0) - before.get("files", 0),
                "bytes_delta": after.get("bytes", 0) - before.get("bytes", 0),
            }
        deltas[label] = {
            "files_delta": right.get("files", 0) - left.get("files", 0),
            "bytes_delta": right.get("bytes", 0) - left.get("bytes", 0),
            "partial": root_partial,
            "families": families,
        }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "compare",
        "flight_id": second.get("flight_id"),
        "partial": partial,
        "roots": deltas,
        "reasons": [warning] if warning else [],
    }
    _write_exclusive(output, result)
    return result, int(partial)


def _parser() -> argparse.ArgumentParser:
    """Build the explicit snapshot/compare command parser.

    Before: no filesystem state is required.
    During: declare mandatory output and mutually exclusive operation inputs.
    After: return a parser; argparse handles basic usage errors before I/O.
    """
    parser = argparse.ArgumentParser(description="Read-only retention inventory")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--flight-id")
    parser.add_argument("--workspace-root")
    parser.add_argument("--budget-seconds", type=float, default=60.0)
    parser.add_argument("--compare", nargs=2, metavar="PHOTO")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run snapshot or compare mode and emit one named stdout summary.

    Before: argv is absent or explicit command-line text; no output is opened.
    During: parse, validate, execute one mode, and convert expected usage/I/O
    failures to rc 2 without tracebacks.
    After: print the output basename and return 0, 1, or 2.
    """
    try:
        args = _parser().parse_args(argv)
        if args.compare:
            if args.root or args.flight_id or args.workspace_root:
                raise UsageError(
                    "--compare no admite --root, --flight-id ni --workspace-root"
                )
            _, rc = _compare(args)
        else:
            if not args.root:
                raise UsageError("se requiere --root fuera de --compare")
            _, rc = _snapshot(args)
        print(
            f"RETENTION_INVENTORY {('partial' if rc else 'complete')} {Path(args.out).name}"
        )
        return rc
    except (AttributeError, OSError, TypeError, UsageError, ValueError) as exc:
        print(f"RETENTION_INVENTORY error {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
