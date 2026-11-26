#!/usr/bin/env python3
"""Migrate legacy archive-index rows on disposable copies only.

Before: a source JSONL index contains ``RETIRADO_LOCAL`` rows from an older
        archive writer.
During: copy the source rows to a separate target and add complete,
        idempotent ``ARCHIVADO`` and ``RETIRADO`` counterparts. Applied writes
        use the shared lock and a sibling temp file followed by flush, fsync,
        and ``os.replace``.
After: the source remains byte-for-byte unchanged and the target is a
        reconciliable index without modifying P7 implementation modules.
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


def _load_rows(path: Path) -> list[dict[str, Any]]:
    """Before: ``path`` names a JSONL index copy.
    During: parse every non-empty line and reject malformed/non-object rows.
    After: return rows in original order without rewriting their representation.
    """
    _reject_d_drive(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read index {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"index row at {path}:{number} is not an object")
        rows.append(row)
    return rows


def _artifact_path(row: dict[str, Any], key: str, base: Path) -> Path:
    """Before: ``row`` contains an archive artifact reference.
    During: resolve it below the disposable copy and reject D: paths.
    After: return a path safe to inspect without modifying the archive.
    """
    value = row.get(key)
    if not value:
        raise ValueError(f"migrated row has no {key}")
    path = Path(str(value))
    if not path.is_absolute():
        path = base / path
    _reject_d_drive(path)
    return path


def _manifest_entries(row: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    """Before: ``row`` points at a manifest in a disposable archive copy.
    During: decode and validate every manifest entry.
    After: return entries in deterministic relative-path order.
    """
    path = _artifact_path(row, "manifest", base)
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


def _enrich_row(row: dict[str, Any], base: Path) -> dict[str, Any]:
    """Before: ``row`` identifies existing archive evidence.
    During: verify the zip/hash and derive list and clone evidence.
    After: return a complete deterministic row with no source fields lost.
    """
    result = dict(row)
    zip_path = _artifact_path(row, "zip", base)
    manifest_path = _artifact_path(row, "manifest", base)
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
    entries = _manifest_entries(row, base)
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


def _generated_rows(
    row: dict[str, Any], base: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Before: ``row`` is a legacy retired-local record.
    During: copy every field and replace only the lifecycle status.
    After: return the ARCHIVADO then RETIRADO transition records.
    """
    archived = _enrich_row(row, base)
    archived["status"] = ARCHIVED_STATUS
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
) -> tuple[list[dict[str, Any]], int, int]:
    """Before: source and target rows came from isolated index copies.
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
        for generated in _generated_rows(source_row, base):
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


def main(argv: list[str] | None = None) -> int:
    """Before: CLI arguments identify disposable source and target copies.
    During: run a dry-run unless ``--apply`` is explicitly supplied.
    After: print a reproducible summary and return a process status.
    """
    parser = argparse.ArgumentParser(
        description="Migrate RETIRADO_LOCAL rows between disposable JSONL copies"
    )
    parser.add_argument(
        "--source-index", "--source", dest="source", type=Path, required=True
    )
    parser.add_argument(
        "--target-index", "--target", dest="target", type=Path, required=True
    )
    parser.add_argument("--apply", action="store_true", help="write the target copy")
    parser.add_argument("--dry-run", action="store_true", help="force preview mode")
    args = parser.parse_args(argv)
    try:
        result = migrate_index(
            args.source, args.target, apply=args.apply and not args.dry_run
        )
    except (OSError, ValueError, p7_common.ArchiveError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    mode = "APPLIED" if args.apply and not args.dry_run else "DRY-RUN"
    print(
        f"[{mode}] source={args.source} target={args.target} "
        f"migrated={result.migrated} added_rows={result.added_rows} "
        f"written={result.written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
