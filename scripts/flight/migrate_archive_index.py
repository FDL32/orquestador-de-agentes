#!/usr/bin/env python3
"""Migrate legacy archive-index rows, on disposable copies or a real root.

Before: a source JSONL index contains ``RETIRADO_LOCAL`` rows from an older
        archive writer; a row whose ``origin`` still exists on disk was never
        actually retired.
During: the default mode copies the source rows to a separate target and
        adds complete, idempotent ``ARCHIVADO`` and, only for an absent
        origin, ``RETIRADO`` counterparts. ``--real-root`` instead migrates a
        mounted real root's own index in place, under its shared P7 lock,
        with explicit user approval, a pre-write backup outside the root,
        and an abort if the index changed since it was first read. Every
        apply write uses a sibling temp file followed by flush, fsync, and
        ``os.replace``.
After: the disposable mode's source remains byte-for-byte unchanged; the
        real-root mode preserves every pre-existing byte of the index and
        only appends new rows. Neither mode touches P7 implementation
        modules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp
from typing import Any

from scripts.flight import p7_common


LEGACY_STATUS = "RETIRADO_LOCAL"
ARCHIVED_STATUS = "ARCHIVADO"
RETIRED_STATUS = "RETIRADO"


@dataclass(frozen=True)
class MigrationResult:
    """Before: one source and target index have been inspected.
    During: report the deterministic migration decision.
    After: callers can distinguish candidates from a physical write.
    """

    migrated: int
    added_rows: int
    would_write: bool
    written: bool


def _reject_d_drive(path: Path) -> None:
    """Before: ``path`` is an operator-supplied filesystem path.
    During: reject the forbidden external archive drive before opening it.
    After: only paths outside ``D:`` are accepted.
    """
    normalized = str(path).replace("\\", "/")
    if path.drive.upper() == "D:" or normalized.upper().startswith("D:/"):
        raise ValueError("D: archive paths are forbidden; use a disposable copy")


def _parse_index_text(text: str, context: str) -> list[dict[str, Any]]:
    """Before: ``text`` is the full content of a JSONL index.
    During: parse every non-empty line and reject malformed/non-object rows.
    After: return rows in original order without rewriting their representation.
    """
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {context}:{number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"index row at {context}:{number} is not an object")
        rows.append(row)
    return rows


def _load_rows(path: Path) -> list[dict[str, Any]]:
    """Before: ``path`` names a JSONL index copy, never the real D: root.
    During: reject the external drive, then parse every non-empty line.
    After: return rows in original order without rewriting their representation.
    """
    _reject_d_drive(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read index {path}: {exc}") from exc
    return _parse_index_text(text, str(path))


def _artifact_path(
    row: dict[str, Any], key: str, base: Path, *, allow_d_drive: bool = False
) -> Path:
    """Before: ``row`` contains an archive artifact reference.
    During: resolve it below ``base`` and, unless the caller is the
        real-root mode (``allow_d_drive``), reject D: paths.
    After: return a path safe to inspect without modifying the archive.
    """
    value = row.get(key)
    if not value:
        raise ValueError(f"migrated row has no {key}")
    path = Path(str(value))
    if not path.is_absolute():
        path = base / path
    if not allow_d_drive:
        _reject_d_drive(path)
    return path


def _manifest_entries(
    row: dict[str, Any], base: Path, *, allow_d_drive: bool = False
) -> list[dict[str, Any]]:
    """Before: ``row`` points at a manifest in a disposable archive copy or,
        with ``allow_d_drive``, at a real mounted root.
    During: decode and validate every manifest entry.
    After: return entries in deterministic relative-path order.
    """
    path = _artifact_path(row, "manifest", base, allow_d_drive=allow_d_drive)
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest {path}: {exc}") from exc
    entries = decoded if isinstance(decoded, list) else decoded.get("entries", [])
    if not isinstance(entries, list) or any(
        not isinstance(item, dict) for item in entries
    ):
        raise ValueError(f"manifest entries are invalid: {path}")
    if any(not {"rel", "sha256"} <= set(item) for item in entries):
        raise ValueError(f"manifest entries lack rel/sha256: {path}")
    return sorted(entries, key=lambda item: str(item["rel"]))


def _enrich_row(
    row: dict[str, Any], base: Path, *, allow_d_drive: bool = False
) -> dict[str, Any]:
    """Before: ``row`` identifies existing archive evidence.
    During: verify the zip/hash and derive list and clone evidence.
    After: return a complete deterministic row with no source fields lost.
    """
    result = dict(row)
    zip_path = _artifact_path(row, "zip", base, allow_d_drive=allow_d_drive)
    manifest_path = _artifact_path(row, "manifest", base, allow_d_drive=allow_d_drive)
    if not zip_path.is_file() or not manifest_path.is_file():
        raise ValueError(f"archive artifacts missing for {row.get('family')}")
    expected_hash = row.get("zip_sha256")
    if (
        expected_hash
        and p7_common.sha256_file(zip_path).lower() != str(expected_hash).lower()
    ):
        raise ValueError(f"zip hash mismatch for {zip_path}")
    expected_manifest_hash = row.get("manifest_sha256")
    if (
        expected_manifest_hash
        and p7_common.sha256_file(manifest_path).lower()
        != str(expected_manifest_hash).lower()
    ):
        raise ValueError(f"manifest hash mismatch for {manifest_path}")
    entries = _manifest_entries(row, base, allow_d_drive=allow_d_drive)
    canonical = [
        {"rel": str(item["rel"]).replace("\\", "/"), "sha256": str(item["sha256"])}
        for item in entries
    ]
    result["list_sha256"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    clone_names = sorted({item["rel"].split("/", 1)[0] for item in canonical})
    if clone_names and (
        "clone" in str(row.get("family", "")).lower() or len(clone_names) > 1
    ):
        result["clone_names"] = clone_names
    return result


def _origin_is_present(row: dict[str, Any], base: Path) -> bool:
    """Before: ``row`` may carry an ``origin`` evidence path.
    During: resolve an absolute origin as-is; resolve a relative origin
        against the index directory ``base``.
    After: return True only if that path exists on disk right now.
    """
    value = row.get("origin")
    if not value:
        return False
    path = Path(str(value))
    if not path.is_absolute():
        path = base / path
    return path.exists()


def _generated_rows(
    row: dict[str, Any], base: Path, *, allow_d_drive: bool = False
) -> tuple[dict[str, Any]] | tuple[dict[str, Any], dict[str, Any]]:
    """Before: ``row`` is a legacy retired-local or archived record.
    During: copy every field and replace only the lifecycle status; skip the
        RETIRADO transition when the row's origin still exists on disk, since
        a live origin means nothing was actually retired.
    After: return only the ARCHIVADO row for a live origin, or the ARCHIVADO
        then RETIRADO pair for an absent one (today's behavior).
    """
    archived = _enrich_row(row, base, allow_d_drive=allow_d_drive)
    archived["status"] = ARCHIVED_STATUS
    if _origin_is_present(row, base):
        return (archived,)
    retired = dict(archived)
    retired["status"] = RETIRED_STATUS
    retired["migration"] = "WOT-2026-175d"
    retired["removed"] = [{"path": str(row.get("origin", "")), "status": "RETIRADA"}]
    return archived, retired


def _row_key(row: dict[str, Any]) -> str:
    """Before: ``row`` is a JSON-compatible index record.
    During: serialize all fields in a stable form for exact deduplication.
    After: return a process-independent identity for idempotent output.
    """
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _migration_rows(
    source_rows: Iterable[dict[str, Any]],
    target_rows: Iterable[dict[str, Any]],
    base: Path,
    *,
    allow_d_drive: bool = False,
) -> tuple[list[dict[str, Any]], int, int]:
    """Before: source and target rows came from isolated index copies, or,
        with ``allow_d_drive``, from a real root mounted on D:.
    During: preserve target history and append missing generated transitions.
    After: return output rows, legacy-row count, and newly added-row count.
    """
    result = [dict(row) for row in target_rows]
    existing = {_row_key(row) for row in result}
    migrated = 0
    added = 0
    for source_row in source_rows:
        if source_row.get("status") not in {LEGACY_STATUS, ARCHIVED_STATUS}:
            continue
        archived_exists = any(
            row.get("status") == ARCHIVED_STATUS
            and row.get("family") == source_row.get("family")
            and row.get("zip") == source_row.get("zip")
            for row in result
        )
        if source_row.get("status") == ARCHIVED_STATUS and any(
            row.get("status") == RETIRED_STATUS
            and row.get("migration") == "WOT-2026-175d"
            and row.get("family") == source_row.get("family")
            and row.get("zip") == source_row.get("zip")
            for row in result
        ):
            continue
        migrated += 1
        for generated in _generated_rows(source_row, base, allow_d_drive=allow_d_drive):
            if generated.get("status") == ARCHIVED_STATUS and archived_exists:
                continue
            key = _row_key(generated)
            if key in existing:
                continue
            result.append(generated)
            existing.add(key)
            added += 1
    return result, migrated, added


def _atomic_write(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Before: ``rows`` are the complete target index contents.
    During: write a sibling temp file, flush/fsync it, and replace atomically.
    After: ``path`` contains complete JSONL or its prior bytes remain intact.
    """
    _reject_d_drive(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise ValueError(f"cannot atomically write index {path}: {exc}") from exc


def migrate_index(
    source: Path,
    target: Path,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Before: ``source`` and ``target`` are disposable, distinct index copies.
    During: calculate the migration and optionally publish it under a lock.
    After: source is untouched; apply mode writes target atomically and only
           when new lifecycle rows are needed.
    """
    source = Path(source)
    target = Path(target)
    _reject_d_drive(source)
    _reject_d_drive(target)
    if source.resolve() == target.resolve():
        raise ValueError("source and target must be separate copies")
    source_rows = _load_rows(source)
    target_rows = _load_rows(target) if target.exists() else list(source_rows)
    output_rows, migrated, added = _migration_rows(
        source_rows, target_rows, source.parent
    )
    would_write = added > 0 or not target.exists()
    written = False
    if apply and would_write:
        lock = target.with_name(f".{target.name}.migrate.lock")
        p7_common.acquire_lock(lock, pid=os.getpid(), cwd=os.getcwd())
        try:
            # Re-read after taking the lock so concurrent runs cannot clobber
            # rows added by another migration process.
            current = _load_rows(target) if target.exists() else list(source_rows)
            output_rows, migrated, added = _migration_rows(
                source_rows, current, source.parent
            )
            if added > 0 or not target.exists():
                _atomic_write(target, output_rows)
                written = True
        finally:
            p7_common.release_lock(lock)
    return MigrationResult(migrated, added, would_write, written)


def _reject_backup_inside_root(root: Path, backup_dir: Path) -> None:
    """Before: ``root`` is the real archive root and ``backup_dir`` its
        proposed pre-write copy location.
    During: resolve and normcase both paths (Windows is case-insensitive).
    After: raise ValueError if ``backup_dir`` is the root or lives under it.
    """
    root_key = Path(os.path.normcase(str(root.resolve())))
    backup_key = Path(os.path.normcase(str(backup_dir.resolve())))
    if backup_key == root_key or root_key in backup_key.parents:
        raise ValueError("backup-dir must be outside the real root")


def _read_real_root_bytes(index: Path) -> bytes:
    """Before: ``index`` names the live JSONL index of a mounted real root.
    During: read it exactly as it stands, D: included.
    After: return its raw bytes or raise ValueError on I/O failure.
    """
    try:
        return index.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read index {index}: {exc}") from exc


def _backup_real_root_index(index: Path, data: bytes, backup_dir: Path) -> str:
    """Before: ``data`` are the exact bytes read from ``index`` under the lock.
    During: copy them, verbatim, into ``backup_dir`` alongside their sha256.
    After: a durable pre-write copy exists outside the root before any write.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    backup_path = backup_dir / f"{index.name}.{digest}.bak"
    backup_path.write_bytes(data)
    (backup_dir / f"{index.name}.{digest}.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    return digest


def _append_real_root_atomic(
    index: Path, original: bytes, new_rows: Iterable[dict[str, Any]]
) -> None:
    """Before: ``original`` are the exact bytes read under the lock.
    During: write a sibling temp file with those bytes unchanged plus the new
        rows appended, then flush/fsync/replace.
    After: every pre-existing byte of ``index`` is preserved; only new lines
           are added, or the prior bytes remain intact on failure.
    """
    index.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = mkstemp(prefix=f".{index.name}.", suffix=".tmp", dir=index.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
            if original and not original.endswith(b"\n"):
                handle.write(b"\n")
            for row in new_rows:
                line = json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, index)
    except OSError as exc:
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise ValueError(f"cannot atomically write index {index}: {exc}") from exc


def migrate_real_root(
    index: Path,
    *,
    apply: bool = False,
    approval_message_id: str | None = None,
    backup_dir: Path | None = None,
) -> MigrationResult:
    """Before: ``index`` is the live JSONL index of a mounted real archive
        root (D: included); this is the only path allowed to touch it.
    During: preview the self-migration without side effects; with ``apply``,
        require explicit approval and a backup directory outside the root,
        take the shared P7 lock (``index.parent/.p7.lock``), re-read the
        index under the lock, abort without writing if its bytes changed
        since the initial read, back it up, and append only the new rows
        while preserving every original byte.
    After: dry-run never touches disk; apply either writes atomically under
           lock with a prior backup, or raises/aborts leaving the real index
           and the lock untouched.
    """
    index = Path(index)
    initial_bytes = _read_real_root_bytes(index)
    initial_rows = _parse_index_text(initial_bytes.decode("utf-8"), str(index))
    _, migrated, added = _migration_rows(
        initial_rows, initial_rows, index.parent, allow_d_drive=True
    )
    would_write = added > 0
    if not apply:
        return MigrationResult(migrated, added, would_write, False)
    if not approval_message_id:
        raise ValueError("real-root apply requires --approval-message-id from the user")
    if backup_dir is None:
        raise ValueError("real-root apply requires --backup-dir")
    backup_dir = Path(backup_dir)
    _reject_backup_inside_root(index.parent, backup_dir)
    lock = index.parent / ".p7.lock"
    p7_common.acquire_lock(lock, pid=os.getpid(), cwd=os.getcwd())
    written = False
    try:
        locked_bytes = _read_real_root_bytes(index)
        if (
            hashlib.sha256(locked_bytes).hexdigest()
            != hashlib.sha256(initial_bytes).hexdigest()
        ):
            raise ValueError(
                "archive index changed between read and write; aborting without writing"
            )
        locked_rows = _parse_index_text(locked_bytes.decode("utf-8"), str(index))
        output_rows, migrated, added = _migration_rows(
            locked_rows, locked_rows, index.parent, allow_d_drive=True
        )
        would_write = added > 0
        if would_write:
            new_rows = output_rows[len(locked_rows) :]
            _backup_real_root_index(index, locked_bytes, backup_dir)
            _append_real_root_atomic(index, locked_bytes, new_rows)
            written = True
    finally:
        p7_common.release_lock(lock)
    return MigrationResult(migrated, added, would_write, written)


def main(argv: list[str] | None = None) -> int:
    """Before: CLI arguments identify either disposable source/target copies
        or, with ``--real-root``, the live index of a mounted real root.
    During: run a dry-run unless ``--apply`` is explicitly supplied.
    After: print a reproducible summary and return a process status.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Migrate RETIRADO_LOCAL rows between disposable JSONL copies, or, "
            "with --real-root, in place on a mounted real archive root"
        )
    )
    parser.add_argument("--source-index", "--source", dest="source", type=Path)
    parser.add_argument("--target-index", "--target", dest="target", type=Path)
    parser.add_argument(
        "--real-root",
        action="store_true",
        help="migrate in place on --source-index, a mounted real root (D: allowed)",
    )
    parser.add_argument(
        "--approval-message-id",
        dest="approval_message_id",
        help="required with --real-root --apply: the user's approval messageId",
    )
    parser.add_argument(
        "--backup-dir",
        dest="backup_dir",
        type=Path,
        help="required with --real-root --apply: pre-write copy, outside the root",
    )
    parser.add_argument("--apply", action="store_true", help="write the target copy")
    parser.add_argument("--dry-run", action="store_true", help="force preview mode")
    args = parser.parse_args(argv)
    if args.source is None:
        print("ERROR: --source-index is required", file=sys.stderr)
        return 2
    apply = args.apply and not args.dry_run
    try:
        if args.real_root:
            result = migrate_real_root(
                args.source,
                apply=apply,
                approval_message_id=args.approval_message_id,
                backup_dir=args.backup_dir,
            )
        else:
            if args.target is None:
                print("ERROR: --target-index is required", file=sys.stderr)
                return 2
            result = migrate_index(args.source, args.target, apply=apply)
    except (OSError, ValueError, p7_common.ArchiveError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    mode = "APPLIED" if apply else "DRY-RUN"
    target_label = args.source if args.real_root else args.target
    print(
        f"[{mode}] source={args.source} target={target_label} "
        f"migrated={result.migrated} added_rows={result.added_rows} "
        f"written={result.written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
