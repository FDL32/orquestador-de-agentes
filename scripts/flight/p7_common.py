"""Shared fail-closed primitives for the P7 flight archive tool.

Before: callers provide an explicitly selected tree, manifest, list, or lock path.
During: this module hashes and validates every boundary before changing state.
After: a mismatch raises :class:`ArchiveError`; candidate classification never retires.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any


class ArchiveError(RuntimeError):
    """A P7 precondition or integrity check failed."""


MIN_AGE_DAYS = 7
MIN_AGE_SECONDS = MIN_AGE_DAYS * 86400
TTL_DIAS_DEFAULT = 7


def sha256_file(path: Path) -> str:
    """Before: ``path`` is a readable regular file.
    During: hash bytes in bounded chunks.
    After: return the hexadecimal SHA-256 digest or propagate an I/O failure.
    """
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArchiveError(f"no se puede leer {path}: {exc}") from exc
    return digest.hexdigest()


def is_reparse_or_link(path: Path) -> bool:
    """Before: ``path`` may be a file or directory.
    During: inspect symlink and Windows reparse-point metadata without resolving it.
    After: return True for links, junctions, or inspection failures (fail-closed).
    """
    try:
        value = Path(path).lstat()
        return stat.S_ISLNK(value.st_mode) or bool(
            getattr(value, "st_file_attributes", 0) & 0x400
        )
    except OSError:
        return True


def walk_files_no_links(top: Path) -> list[Path]:
    """Before: ``top`` is a directory whose links must not be traversed.
    During: walk with link-following disabled and prune reparse directories.
    After: return sorted regular files, excluding every link or failed probe.
    """
    top = Path(top)
    if not top.is_dir() or is_reparse_or_link(top):
        return []
    result: list[Path] = []
    for root, dirs, files in os.walk(top, topdown=True, followlinks=False):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not is_reparse_or_link(root_path / d)]
        for name in files:
            candidate = root_path / name
            if not is_reparse_or_link(candidate) and candidate.is_file():
                result.append(candidate)
    return sorted(result)


def root_files(
    directory: Path, skip_names: Iterable[str] = ("README.md", "INDEX.md")
) -> list[Path]:
    """Before: ``directory`` is a non-link directory.
    During: select only direct regular files not named in ``skip_names``.
    After: return a deterministic list without traversing child links.
    """
    directory = Path(directory)
    if not directory.is_dir() or is_reparse_or_link(directory):
        return []
    skip = set(skip_names)
    return sorted(
        p
        for p in directory.iterdir()
        if p.name not in skip and not is_reparse_or_link(p) and p.is_file()
    )


def append_rows_atomic(
    path: Path,
    rows: Iterable[str],
    header: str | None = None,
    *,
    newline: str | None = "\n",
) -> None:
    """Before: ``path`` is a ledger and rows are complete text records.
    During: append through a sibling temporary file and atomic replacement.
    After: existing content and all rows are durable, or no replacement occurs.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else (header or "")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    payload = existing + "".join(rows)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(temp_name)
        raise ArchiveError(f"no se pudo actualizar {path}: {exc}") from exc


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if not git:
        raise ArchiveError("git no esta en PATH")
    try:
        return subprocess.run(  # noqa: S603
            [git, "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveError(f"git no se pudo ejecutar: {exc}") from exc


def git_tracked_files(project_root: Path) -> set[str]:
    """Before: ``project_root`` is the intended git repository.
    During: query tracked paths and reject any non-zero git result.
    After: return normalized repository-relative tracked names.
    """
    proc = _git(Path(project_root), "ls-files", "-z")
    if proc.returncode:
        raise ArchiveError(f"git ls-files fallo (rc={proc.returncode})")
    return {item.replace("\\", "/") for item in (proc.stdout or "").split("\0") if item}


def git_dirty_names(project_root: Path) -> set[str]:
    """Before: ``project_root`` is a git repository.
    During: inspect all tracked and untracked status entries with ``-uall``.
        ``-uall`` is mandatory because plain porcelain collapses an entire
        untracked directory into one line, leaving the work-in-progress guard
        blind to its individual files. Parse rename entries on both sides of
        ``old -> new`` so either path keeps its basename protected.
    After: return dirty basenames, aborting on git failure.
    """
    proc = _git(Path(project_root), "status", "--porcelain", "-uall")
    if proc.returncode:
        raise ArchiveError(f"git status fallo (rc={proc.returncode})")
    names: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        rest = line[3:] if len(line) > 3 else line
        for part in rest.split(" -> "):
            if part.strip():
                names.add(Path(part.strip().strip('"')).name)
    return names


def manifest_of_tree(base: Path) -> list[dict[str, Any]]:
    """Before: ``base`` is a mounted, non-link directory.
    During: record relative path, byte size, mtime, and SHA-256 for each file.
    After: return a sorted complete tree manifest; links are never included.
    """
    base = Path(base)
    if not base.is_dir() or is_reparse_or_link(base):
        raise ArchiveError(f"raiz no montada o no valida: {base}")
    rows = []
    for path in walk_files_no_links(base):
        try:
            info = path.stat()
        except OSError as exc:
            raise ArchiveError(f"no se pudo stat {path}: {exc}") from exc
        rows.append(
            {
                "rel": path.relative_to(base).as_posix(),
                "size": info.st_size,
                "mtime": info.st_mtime,
                "sha256": sha256_file(path),
            }
        )
    return sorted(rows, key=lambda row: row["rel"])


def verify_manifest_entries(base: Path, manifest: Iterable[dict[str, Any]]) -> None:
    """Before: ``manifest`` is the approved snapshot of ``base``.
    During: compare existence, size, mtime (1e-3), and digest in manifest order.
    After: return only when every entry matches; first mismatch aborts.
    """
    base = Path(base)
    for row in manifest:
        rel = str(row.get("rel", row.get("path", "")))
        path = base / rel
        try:
            if not path.is_file() or is_reparse_or_link(path):
                raise ArchiveError(f"manifiesto: falta o enlace: {rel}")
            info = path.stat()
        except OSError as exc:
            raise ArchiveError(
                f"manifiesto: no se pudo comprobar {rel}: {exc}"
            ) from exc
        if info.st_size != int(row["size"]):
            raise ArchiveError(f"manifiesto: tamano discrepante: {rel}")
        if abs(info.st_mtime - float(row["mtime"])) > 1e-3:
            raise ArchiveError(f"manifiesto: mtime discrepante: {rel}")
        if sha256_file(path) != row["sha256"]:
            raise ArchiveError(f"manifiesto: hash discrepante: {rel}")


def load_jsonl_index(path: Path) -> list[dict[str, Any]]:
    """Before: ``path`` is a JSONL index or absent.
    During: parse each non-empty line as an object.
    After: return rows, rejecting malformed records.
    """
    if not Path(path).exists():
        return []
    rows = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("row is not object")
                rows.append(item)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"indice JSONL invalido: {path}: {exc}") from exc
    return rows


def write_jsonl_index_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Before: ``rows`` contains JSON-serializable index records.
    During: serialize all rows and replace the index atomically.
    After: the complete JSONL index is present.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(temp_name)
        raise ArchiveError(f"no se pudo escribir indice {path}: {exc}") from exc


def reconcile_index(
    archive_root: Path, rows: Iterable[dict[str, Any]], family: str
) -> list[str]:
    """Before: ``rows`` is the shared index for all archive families.
    During: filter ARCHIVADO rows by ``family`` and compare canonicalized
        indexed names with the actual non-link files under that family. The
        shared index is reconciled *by family*, so another family's rows never
        contaminate this comparison; paths are resolved and normcased before
        component-wise containment checks.
    After: return findings in both directions, sorted and prefixed.
    """
    root = (Path(archive_root) / family).resolve()
    root_key = Path(os.path.normcase(str(root)))
    indexed: set[str] = set()
    for row in rows:
        if row.get("status") != "ARCHIVADO" or row.get("family") != family:
            continue
        for key in ("zip", "manifest"):
            value = row.get(key)
            if not value:
                raise ArchiveError(f"fila ARCHIVADO sin {key}")
            candidate = Path(str(value))
            if not candidate.is_absolute():
                candidate = Path(archive_root) / candidate
            candidate_key = Path(os.path.normcase(str(candidate.resolve())))
            try:
                indexed.add(candidate_key.relative_to(root_key).as_posix())
            except ValueError as exc:
                raise ArchiveError(f"ruta de indice fuera de familia: {value}") from exc
    actual = (
        {
            Path(os.path.normcase(str(p.resolve()))).relative_to(root_key).as_posix()
            for p in walk_files_no_links(root)
        }
        if root.is_dir()
        else set()
    )
    return [f"fila_sin_fichero: {name}" for name in sorted(indexed - actual)] + [
        f"fichero_sin_fila: {name}" for name in sorted(actual - indexed)
    ]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        tasklist = shutil.which("tasklist")
        if tasklist:
            try:
                probe = subprocess.run(  # noqa: S603
                    [tasklist, "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                return True
            return probe.returncode == 0 and str(pid) in (probe.stdout or "")
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        return exc.errno not in (errno.EINVAL, errno.ESRCH)
    except SystemError:
        return True
    return True


def acquire_lock(path: Path, *, pid: int, cwd: str) -> None:
    """Before: ``path`` names the P7 lock and ``cwd`` is the active session cwd.
    During: create lock atomically, rejecting live owners or invalid cwd metadata.
    After: a durable JSON lock exists, or ArchiveError is raised.
    """
    path = Path(path)
    if not Path(cwd).is_dir():
        raise ArchiveError(f"cwd de sesion no existe: {cwd}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"pid": pid, "cwd": str(Path(cwd).resolve()), "created": time.time()}
    )
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            old_pid = int(old.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as read_exc:
            raise ArchiveError(
                f"lock invalido y no se puede tomar: {path}"
            ) from read_exc
        if _pid_alive(old_pid):
            raise ArchiveError(f"lock retenido por PID {old_pid}: {path}") from exc
        try:
            path.unlink()
            return acquire_lock(path, pid=pid, cwd=cwd)
        except OSError as unlink_exc:
            raise ArchiveError(
                f"no se pudo reemplazar lock huerfano: {path}"
            ) from unlink_exc
    except OSError as exc:
        raise ArchiveError(f"no se pudo crear lock {path}: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        with suppress(OSError):
            path.unlink()
        raise ArchiveError(f"no se pudo escribir lock {path}: {exc}") from exc


def release_lock(path: Path) -> None:
    """Before: ``path`` is a P7 lock owned by this operation.
    During: remove the lock file.
    After: absence is guaranteed unless the filesystem rejects removal.
    """
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        raise ArchiveError(f"no se pudo liberar lock {path}: {exc}") from exc


def lock_is_held(path: Path) -> bool:
    """Before: ``path`` may or may not exist.
    During: inspect lock metadata and owner liveness.
    After: return True only for a syntactically valid live lock.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return _pid_alive(int(data["pid"]))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def load_approved_list(path: Path, expected_list_sha256: str) -> list[dict[str, Any]]:
    """Before: ``path`` is the user-approved JSON/JSONL list and hash is explicit.
    During: hash the exact bytes, then parse object rows or a JSON array.
    After: return entries only if the approved list hash matches.
    """
    actual = sha256_file(Path(path))
    if actual.lower() != expected_list_sha256.lower():
        raise ArchiveError(f"hash de lista no aprobado: {actual}")
    try:
        text = Path(path).read_text(encoding="utf-8")
        if text.lstrip().startswith("["):
            data = json.loads(text)
            entries = data if isinstance(data, list) else []
        else:
            entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"lista aprobada invalida: {path}") from exc
    if not all(isinstance(item, dict) for item in entries):
        raise ArchiveError("lista aprobada debe contener objetos")
    return entries


def verify_list_entries(entries: Iterable[dict[str, Any]], base: Path) -> None:
    """Before: entries contain each approved relative path and SHA-256.
    During: hash every entry from ``base`` and reject the first mismatch.
    After: every approved entry still denotes the approved bytes.
    """
    for entry in entries:
        rel = str(entry.get("rel", entry.get("path", entry.get("name", ""))))
        assert_no_link_ancestors(base, rel)
        path = Path(base) / rel
        if is_reparse_or_link(path) or not path.is_file():
            raise ArchiveError(f"entrada aprobada ausente o enlace: {rel}")
        if sha256_file(path) != str(entry.get("sha256", entry.get("hash", ""))):
            raise ArchiveError(f"hash de entrada no coincide: {rel}")


def assert_no_link_ancestors(base: Path, rel: str) -> None:
    """Before: ``rel`` is a relative approved path below ``base``.
    During: inspect each directory component without resolving links.
    After: return only when no ancestor is a symlink or reparse point.
    """
    relative = Path(rel)
    if (
        relative.is_absolute()
        or relative.drive
        or relative.anchor
        or ".." in relative.parts
    ):
        raise ArchiveError(f"ruta aprobada invalida: {rel}")
    current = Path(base)
    for part in relative.parts[:-1]:
        current /= part
        if is_reparse_or_link(current):
            raise ArchiveError(f"ruta aprobada atraviesa enlace o junction: {rel}")


def classify_candidates(
    entries: Iterable[dict[str, Any]],
    *,
    now: float,
    ttl_dias: int,
    min_age_segundos: int,
) -> list[dict[str, Any]]:
    """Before: entries describe possible historical files.
    During: select only entries older than both TTL and minimum age.
    After: return candidates only; this function never removes or mutates files.
    """
    threshold = max(int(ttl_dias) * 86400, int(min_age_segundos))
    return [
        entry for entry in entries if now - float(entry.get("mtime", now)) >= threshold
    ]
