"""P7 archive and retirement CLI.

Before: an external mounted archive root, an origin, and a hashed approved list.
During: dry-run by default; apply-archive creates verified zip evidence, while
apply-retire revalidates that evidence before unlinking only eligible files.
After: every operation is indexed outside the retired origin, or fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.flight import p7_common  # noqa: E402


def _mounted(root: Path) -> bool:
    try:
        return (
            root.is_dir()
            and not p7_common.is_reparse_or_link(root)
            and os.path.exists(root.anchor)
        )
    except OSError:
        return False


def _canonical_path(path: Path) -> Path:
    """Before: ``path`` identifies a configured filesystem tree.
    During: resolve it without requiring existence and normalize its case.
    After: return a stable component-comparable path for containment checks.
    """
    return Path(os.path.normcase(str(Path(path).resolve(strict=False))))


def _paths_overlap(left: Path, right: Path) -> bool:
    """Before: ``left`` and ``right`` are configured roots.
    During: compare canonical path components, never string prefixes.
    After: return True when either root contains the other, including equality.
    """
    left_key = _canonical_path(left)
    right_key = _canonical_path(right)
    try:
        left_key.relative_to(right_key)
        return True
    except ValueError:
        pass
    try:
        right_key.relative_to(left_key)
        return True
    except ValueError:
        return False


def _entry_name(entry: dict[str, object]) -> str:
    return str(entry.get("rel", entry.get("path", entry.get("name", ""))))


def _paths(entries: list[dict[str, object]], origin: Path) -> list[Path]:
    result = []
    for entry in entries:
        rel = _entry_name(entry)
        relative = Path(rel)
        if (
            not rel
            or relative.is_absolute()
            or relative.drive
            or relative.anchor
            or ".." in relative.parts
        ):
            raise p7_common.ArchiveError(f"ruta aprobada invalida: {rel}")
        p7_common.assert_no_link_ancestors(origin, rel)
        result.append(origin / rel)
    return result


def _index_paths(archive_root: Path, family: str) -> tuple[Path, Path, Path]:
    del family
    return (
        archive_root / "index.jsonl",
        archive_root / "INDEX.md",
        archive_root / ".p7.lock",
    )


def _append_record(index: Path, record: dict[str, object]) -> None:
    rows = p7_common.load_jsonl_index(index)
    rows.append(record)
    p7_common.write_jsonl_index_atomic(index, rows)


def _zip_paths(zip_path: Path, paths: list[Path], origin: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    actual_names = {
        os.path.normcase(path.relative_to(origin).as_posix()): path.relative_to(
            origin
        ).as_posix()
        for path in p7_common.walk_files_no_links(origin)
    }
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            requested = path.relative_to(origin).as_posix()
            archive.write(
                path, actual_names.get(os.path.normcase(requested), requested)
            )


def _markdown_index(path: Path, rows: list[dict[str, object]]) -> None:
    text = "# P7 index\n\n| Estado | Familia | Zip | Manifiesto | Lista |\n|---|---|---|---|---|\n"
    text += "".join(
        f"| {row.get('status', '')} | {row.get('family', '')} | {row.get('zip', '')} | {row.get('manifest', '')} | {row.get('list_sha256', '')} |\n"
        for row in rows
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check_index(archive_root: Path, family: str, index: Path) -> None:
    """Before: index and family artifacts are present or absent together.
    During: reconcile both directions against the actual family directory.
    After: return only for a complete index; findings abort the P7 transition.
    """
    findings = p7_common.reconcile_index(
        archive_root, p7_common.load_jsonl_index(index), family
    )
    if findings:
        raise p7_common.ArchiveError("indice P7 inconsistente: " + "; ".join(findings))


def _check_shared_index(archive_root: Path, family: str, index: Path) -> None:
    """Before: ``index`` is the shared ledger and ``family`` is selected.
    During: reconcile the selected family and every family already represented
        in the shared ledger, preserving family-local path comparisons while
        refusing to proceed over any pre-existing broken family.
    After: return only when the shared archive is consistent for all known
        families.
    """
    rows = p7_common.load_jsonl_index(index)
    families = {family}
    families.update(
        str(row["family"])
        for row in rows
        if row.get("status") == "ARCHIVADO" and row.get("family")
    )
    for candidate in sorted(families):
        _check_index(archive_root, candidate, index)


def _validate_manifest_shape(manifest: list[dict[str, object]]) -> None:
    """Before: ``manifest`` contains decoded manifest rows.
    During: require the exact schema on every row, not only the first row.
    After: return only for a uniformly shaped manifest.
    """
    expected = {"rel", "size", "mtime", "sha256"}
    if any(set(row) != expected for row in manifest):
        raise p7_common.ArchiveError("manifiesto con claves inesperadas")


def _apply_archive(  # noqa: C901
    args: argparse.Namespace,
    entries: list[dict[str, object]],
    origin: Path,
    index: Path,
    md: Path,
) -> int:
    paths = _paths(entries, origin)
    for path in paths:
        if not path.is_file() or p7_common.is_reparse_or_link(path):
            raise p7_common.ArchiveError(f"entrada no archivables: {path}")
    p7_common.verify_list_entries(entries, origin)
    family_dir = args.archive_root / args.family
    family_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = family_dir / f"{args.family}-{stamp}.zip"
    manifest_path = family_dir / f"{zip_path.stem}.manifest.json"
    if zip_path.exists() or manifest_path.exists():
        raise p7_common.ArchiveError("ya existe evidencia para la marca temporal")
    temp_zip_fd, temp_zip_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.", suffix=".tmp", dir=str(family_dir)
    )
    os.close(temp_zip_fd)
    os.unlink(temp_zip_name)
    temp_zip = Path(temp_zip_name)
    temp_manifest_fd, temp_manifest_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.", suffix=".tmp", dir=str(family_dir)
    )
    os.close(temp_manifest_fd)
    os.unlink(temp_manifest_name)
    temp_manifest = Path(temp_manifest_name)
    original_rows = p7_common.load_jsonl_index(index)
    index_existed = index.exists()
    try:
        _zip_paths(temp_zip, paths, origin)
        if temp_zip.stat().st_size <= 0:
            raise p7_common.ArchiveError("zip vacio")
        with zipfile.ZipFile(temp_zip) as archive:
            if archive.testzip() is not None:
                raise p7_common.ArchiveError("zip corrupto")
        manifest = p7_common.manifest_of_tree(origin)
        approved_names = {os.path.normcase(_entry_name(entry)) for entry in entries}
        manifest = [
            row
            for row in manifest
            if os.path.normcase(str(row["rel"])) in approved_names
        ]
        if len(manifest) != len(entries):
            raise p7_common.ArchiveError("manifiesto sin todas las entradas aprobadas")
        _validate_manifest_shape(manifest)
        with zipfile.ZipFile(temp_zip) as archive:
            for row in manifest:
                with archive.open(row["rel"]) as member:
                    digest = hashlib.sha256(member.read()).hexdigest()
                if digest != row["sha256"]:
                    raise p7_common.ArchiveError(
                        f"hash del zip discrepante: {row['rel']}"
                    )
        temp_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        record = {
            "status": "ARCHIVADO",
            "family": args.family,
            "origin": str(origin),
            "zip": str(zip_path),
            "manifest": str(manifest_path),
            "zip_sha256": p7_common.sha256_file(temp_zip),
            "list_sha256": args.list_sha256,
            "entries": entries,
        }
        rows = [*original_rows, record]
        p7_common.write_jsonl_index_atomic(index, rows)
        os.replace(temp_zip, zip_path)
        os.replace(temp_manifest, manifest_path)
        _check_index(args.archive_root, args.family, index)
        _markdown_index(md, rows)
        return 0
    except Exception:
        for candidate in (temp_zip, temp_manifest, zip_path, manifest_path):
            with suppress(FileNotFoundError):
                candidate.unlink()
        if index_existed:
            p7_common.write_jsonl_index_atomic(index, original_rows)
        else:
            with suppress(FileNotFoundError):
                index.unlink()
        raise


def _apply_retire(
    args: argparse.Namespace,
    entries: list[dict[str, object]],
    origin: Path,
    index: Path,
    md: Path,
) -> int:
    _check_index(args.archive_root, args.family, index)
    rows = p7_common.load_jsonl_index(index)
    archived = next(
        (
            row
            for row in reversed(rows)
            if row.get("status") == "ARCHIVADO"
            and row.get("list_sha256") == args.list_sha256
        ),
        None,
    )
    if archived is None:
        raise p7_common.ArchiveError("no existe fila ARCHIVADO para la lista aprobada")
    zip_path = Path(str(archived["zip"]))
    manifest_path = Path(str(archived["manifest"]))
    if not zip_path.is_file() or p7_common.sha256_file(zip_path) != archived.get(
        "zip_sha256"
    ):
        raise p7_common.ArchiveError("zip archivado ausente o hash discrepante")
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise p7_common.ArchiveError("zip archivado corrupto")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest_shape(manifest)
    with zipfile.ZipFile(zip_path) as archive:
        for row in manifest:
            with archive.open(row["rel"]) as member:
                digest = hashlib.sha256(member.read()).hexdigest()
            if digest != row["sha256"]:
                raise p7_common.ArchiveError(f"hash del zip discrepante: {row['rel']}")
    p7_common.verify_manifest_entries(origin, manifest)
    p7_common.verify_list_entries(entries, origin)
    tracked = p7_common.git_tracked_files(origin)
    tracked_keys = {os.path.normcase(name) for name in tracked}
    removed = []
    for path, _entry in zip(_paths(entries, origin), entries, strict=True):
        key = os.path.normcase(path.relative_to(origin).as_posix())
        if key in tracked_keys:
            removed.append({"path": str(path), "status": "SALTADA_VERSIONADA"})
            continue
        path.unlink()
        removed.append({"path": str(path), "status": "RETIRADA"})
    _append_record(
        index,
        {
            "status": "RETIRADO",
            "family": args.family,
            "list_sha256": args.list_sha256,
            "removed": removed,
        },
    )
    _markdown_index(md, p7_common.load_jsonl_index(index))
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Before: parse an explicit archive root and approved list.
    During: hold an external lock and execute the selected P7 transition.
    After: return 0, 1, 2, or 4 according to the fail-closed CLI contract.
    """
    parser = argparse.ArgumentParser(
        description="P7: archive/retire with approved hashes; recommended root D:/flight_archive"
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        required=True,
        help="mounted archive volume; recommended D:/flight_archive",
    )
    parser.add_argument("--family", required=True)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--list", dest="list_path", type=Path, required=True)
    parser.add_argument("--list-sha256", required=True)
    parser.add_argument("--ttl-dias", type=int, default=p7_common.TTL_DIAS_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-archive", action="store_true")
    parser.add_argument("--apply-retire", action="store_true")
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if (
        (args.apply_archive and args.apply_retire)
        or (args.apply_archive and args.dry_run)
        or (args.apply_retire and args.dry_run)
    ):
        return 2
    if _paths_overlap(args.archive_root, args.origin):
        print(
            "ERROR: archive-root y origin deben ser arboles disjuntos",
            file=sys.stderr,
        )
        return 2
    if p7_common.is_reparse_or_link(args.origin):
        print("ERROR: origin no puede ser un enlace o reparse point", file=sys.stderr)
        return 2
    if not _mounted(args.archive_root):
        return 4
    if not args.origin.is_dir():
        return 1
    try:
        entries = p7_common.load_approved_list(args.list_path, args.list_sha256)
        p7_common.verify_list_entries(entries, args.origin)
        index, md, lock = _index_paths(args.archive_root, args.family)
        p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(Path.cwd()))
        try:
            _check_shared_index(args.archive_root, args.family, index)
            if args.apply_archive:
                rc = _apply_archive(args, entries, args.origin, index, md)
            elif args.apply_retire:
                rc = _apply_retire(args, entries, args.origin, index, md)
            else:
                rc = 0
            _check_shared_index(args.archive_root, args.family, index)
            if args.json:
                print(
                    json.dumps(
                        {
                            "status": "DRY_RUN"
                            if not (args.apply_archive or args.apply_retire)
                            else "OK",
                            "candidates": p7_common.classify_candidates(
                                entries,
                                now=datetime.now(timezone.utc).timestamp(),
                                ttl_dias=args.ttl_dias,
                                min_age_segundos=p7_common.MIN_AGE_SECONDS,
                            ),
                        }
                    )
                )
            return rc
        finally:
            p7_common.release_lock(lock)
    except (p7_common.ArchiveError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
