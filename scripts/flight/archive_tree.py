"""Versioned, fail-closed archiver for clone trees.

Before: callers provide an origin tree and a disjoint archive root.
During: the tool hashes candidates, holds the shared P7 lock, writes verified
        zip and manifest evidence, and optionally retires only that evidence.
After: dry-run has no writes; apply leaves an auditable P7 JSONL ledger.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.flight import p7_common, verify_user_authorization as vua  # noqa: E402


RETIRE_STEP = 1
CHAIN_LEDGER_NAME = "chain_authority_ledger.jsonl"


class ArchiveTreeError(RuntimeError):
    """A fail-closed precondition or evidence check failed."""


def _default_git_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Before: git command needs execution without throwing subprocess errors.
    During: execute subprocess.run capturing stdout and stderr in text mode.
    After: return CompletedProcess for status inspection.
    """
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


_git_runner = _default_git_runner


def set_git_runner(
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None,
) -> None:
    """Before: default runner invokes real subprocess git.
    During: update the internal git invocation hook.
    After: tests can inspect or control git commands.
    """
    global _git_runner
    _git_runner = runner or _default_git_runner


def _get_git_common_dir(origin: Path) -> Path | None:
    """Before: worktree origin path is known but common repo dir may differ.
    During: invoke git rev-parse --git-common-dir to obtain common dir.
    After: return Path to common repository directory, or None if not git.
    """
    with suppress(Exception):
        res = _git_runner(
            [
                "git",
                "-C",
                str(origin),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ]
        )
        if res.returncode == 0 and res.stdout.strip():
            return Path(res.stdout.strip())
    return None


def _is_worktree_registered(origin: Path, common_dir: Path) -> bool:
    """Before: worktree registration in common repo is unknown.
    During: query git worktree list --porcelain and match origin path.
    After: return True if registered, False otherwise.
    """
    with suppress(Exception):
        res = _git_runner(
            ["git", "-C", str(common_dir), "worktree", "list", "--porcelain"]
        )
        if res.returncode == 0:
            target_norm = os.path.normcase(str(origin.resolve()))
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    wt_path = line[len("worktree ") :].strip()
                    if os.path.normcase(str(Path(wt_path).resolve())) == target_norm:
                        return True
    return False


def _verify_tree_conditions(args: argparse.Namespace, origin: Path) -> None:  # noqa: C901
    """Before: tree mode requires satisfying all five R1 conditions.
    During: verify ticket in backlog_done, ancestor integration, clean worktree, settled session, and no gc or prune.
    After: fail-closed with ArchiveTreeError on any violation without modifying origin.
    """
    if not origin.exists():
        return
    if not args.ticket:
        raise ArchiveTreeError("missing --ticket argument for tree mode")
    if not args.project_root:
        raise ArchiveTreeError("missing --project-root argument for tree mode")
    backlog_file = (
        args.project_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    )
    if not backlog_file.is_file():
        raise ArchiveTreeError(f"backlog_done.md is missing: {backlog_file}")
    backlog_text = backlog_file.read_text(encoding="utf-8", errors="replace")
    pattern = rf"^\| [^|]+ \| {re.escape(args.ticket)} \|"
    if not re.search(pattern, backlog_text, re.MULTILINE):
        raise ArchiveTreeError(
            f"ticket {args.ticket} not found closed in backlog_done.md"
        )

    if not args.integrated_into:
        raise ArchiveTreeError("missing --integrated-into argument for tree mode")
    common_dir = _get_git_common_dir(origin)
    if common_dir is None:
        raise ArchiveTreeError(f"cannot resolve git common dir for origin: {origin}")
    head_res = _git_runner(["git", "-C", str(origin), "rev-parse", "HEAD"])
    if head_res.returncode != 0 or not head_res.stdout.strip():
        raise ArchiveTreeError(f"cannot resolve HEAD for origin: {origin}")
    head = head_res.stdout.strip()
    mb_res = _git_runner(
        [
            "git",
            "-C",
            str(common_dir),
            "merge-base",
            "--is-ancestor",
            head,
            args.integrated_into,
        ]
    )
    if mb_res.returncode != 0:
        raise ArchiveTreeError(
            f"origin HEAD {head} is not an ancestor of {args.integrated_into}"
        )

    st_res = _git_runner(
        ["git", "-C", str(origin), "status", "--porcelain", "-uall", "--ignored"]
    )
    if st_res.returncode != 0 or st_res.stdout.strip():
        raise ArchiveTreeError(
            "worktree origin is not clean (modified, untracked, or ignored files present)"
        )

    if not args.registry:
        raise ArchiveTreeError("missing --registry argument for tree mode")
    if not args.owner_session:
        raise ArchiveTreeError("missing --owner-session argument for tree mode")
    if not args.registry.is_file():
        raise ArchiveTreeError(f"registry file is missing: {args.registry}")
    try:
        registry_data = json.loads(args.registry.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveTreeError(f"registry file is invalid: {exc}") from exc
    if not isinstance(registry_data, dict) or not isinstance(
        registry_data.get("sessions"), list
    ):
        raise ArchiveTreeError("registry must be an object with a sessions list")

    seen_codes: set[str] = set()
    owner_entry: dict[str, Any] | None = None
    for entry in registry_data["sessions"]:
        if not isinstance(entry, dict):
            raise ArchiveTreeError("invalid session entry in registry")
        code = str(entry.get("code", "")).strip()
        if code in seen_codes:
            raise ArchiveTreeError(f"duplicate session code in registry: {code}")
        seen_codes.add(code)
        if code == args.owner_session:
            owner_entry = entry

    if owner_entry is None:
        raise ArchiveTreeError(
            f"owner session {args.owner_session} not found in registry"
        )
    status_str = str(owner_entry.get("status", "")).strip().casefold()
    if not (status_str.startswith("asentada") or status_str.startswith("settled")):
        raise ArchiveTreeError(
            f"owner session {args.owner_session} is not settled (status: {status_str})"
        )

    prune_res = _git_runner(
        ["git", "-C", str(common_dir), "worktree", "prune", "--dry-run"]
    )
    prune_out = (prune_res.stdout + prune_res.stderr).strip()
    if prune_res.returncode != 0 or prune_out:
        raise ArchiveTreeError("pending worktree prune detected in git common dir")
    if (common_dir / "gc.pid").exists() or (common_dir / "gc.log").exists():
        raise ArchiveTreeError(
            "git gc is in progress or pending (gc.pid or gc.log present in git common dir)"
        )


def _sha256_bytes(data: bytes) -> str:
    """Before: ``data`` is immutable bytes.
    During: calculate SHA-256.
    After: return the hexadecimal digest.
    """
    return hashlib.sha256(data).hexdigest()


def _tree_rows(root: Path) -> list[dict[str, Any]]:
    """Before: ``root`` is a real directory.
    During: enumerate files and empty directories without following links.
    After: return deterministic rows including metadata and digests.
    """
    if not root.is_dir() or p7_common.is_reparse_or_link(root):
        raise ArchiveTreeError(f"invalid origin: {root}")
    rows: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if not p7_common.is_reparse_or_link(current_path / name)
        ]
        if not dirs and not files and current_path != root:
            rows.append({"rel": current_path.relative_to(root).as_posix(), "dir": True})
        for name in files:
            path = current_path / name
            if p7_common.is_reparse_or_link(path) or not path.is_file():
                raise ArchiveTreeError(f"link or non-file in origin: {path}")
            info = path.stat()
            rows.append(
                {
                    "rel": path.relative_to(root).as_posix(),
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                    "sha256": p7_common.sha256_file(path),
                }
            )
    return sorted(rows, key=lambda row: (row["rel"], row.get("dir", False)))


def tree_hash(root: Path, *, exclude: Iterable[str] = ()) -> str:
    """Before: ``root`` is a readable tree.
    During: hash relative names, directory markers, sizes, mtimes, and bytes.
    After: return a stable digest for the complete tree.
    """
    excluded = set(exclude)
    rows = [row for row in _tree_rows(root) if row["rel"] not in excluded]
    return _sha256_bytes(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    )


def _candidate_dirs(origin: Path) -> list[Path]:
    """Before: ``origin`` is a clone parent.
    During: select direct, non-link directories and ignore operational files.
    After: return deterministic non-empty candidates.
    """
    result = []
    for path in sorted(origin.iterdir()):
        if (
            path.name.startswith(".")
            or not path.is_dir()
            or p7_common.is_reparse_or_link(path)
        ):
            continue
        if _tree_rows(path):
            result.append(path)
    return result


def _approved_entries(  # noqa: C901
    path: Path | None,
    expected: str | None,
    origin: Path,
    *,
    tree: bool = False,
) -> list[dict[str, Any]]:
    """Before: an optional approval file is supplied.
    During: verify its exact byte hash and every selected tree hash.
    After: return normalized approved entries or raise without writing.
    """
    if expected is None:
        if tree:
            return [{"rel": ".", "sha256": tree_hash(origin)}]
        return [
            {"rel": p.name, "sha256": tree_hash(p)} for p in _candidate_dirs(origin)
        ]
    if path is None or not path.is_file():
        raise ArchiveTreeError("approved list is missing")
    actual = p7_common.sha256_file(path)
    if actual.lower() != expected.lower():
        raise ArchiveTreeError("approved list hash mismatch")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveTreeError("approved list is invalid") from exc
    if not isinstance(data, list) or not data:
        raise ArchiveTreeError("approved list must be a non-empty array")
    entries = []
    for raw in data:
        if not isinstance(raw, dict) or not raw.get("rel") or not raw.get("sha256"):
            raise ArchiveTreeError("every approved entry needs rel and sha256")
        rel = str(raw["rel"])
        target = origin if tree and rel in (".", origin.name) else origin / rel
        if Path(rel).is_absolute() or ".." in Path(rel).parts or not target.is_dir():
            raise ArchiveTreeError(f"invalid approved tree: {rel}")
        if p7_common.is_reparse_or_link(target) or tree_hash(target) != str(
            raw["sha256"]
        ):
            raise ArchiveTreeError(f"approved tree hash mismatch: {rel}")
        entries.append({"rel": rel.replace("\\", "/"), "sha256": str(raw["sha256"])})
    return entries


def _process_rows() -> list[tuple[int, str, str | None, int | None]]:
    """Before: the platform may expose process metadata.
    During: query command lines and best-effort Windows current directories.
    After: return pid, command line, and cwd; Windows query failures abort closed
    after one retry, while non-Windows keeps its documented empty result.
    """
    if os.name != "nt":
        return []
    script = "Get-CimInstance Win32_Process | ForEach-Object { $c=$_.CommandLine; Write-Output ($_.ProcessId.ToString()+'|'+$_.ParentProcessId.ToString()+'|'+$c) }"
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    for timeout in (10, 30):
        try:
            proc = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
            if proc.returncode == 0:
                break
        except (OSError, subprocess.SubprocessError):
            proc = None
        if timeout == 30:
            raise ArchiveTreeError("cannot list processes")
    else:
        raise ArchiveTreeError("cannot list processes")
    result = []
    for line in proc.stdout.splitlines():
        if line.count("|") < 2:
            continue
        pid_text, parent_text, command = line.split("|", 2)
        with suppress(ValueError):
            pid = int(pid_text)
            result.append((pid, command, _windows_cwd(pid), int(parent_text)))
    return result


def _windows_cwd(pid: int) -> str | None:
    """Before: ``pid`` identifies a Windows process.
    During: use standard-library ctypes to query the PEB current directory.
    After: return a directory string or None when access is denied/unreadable.
    """
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.ReadProcessMemory.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.ReadProcessMemory.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return None
    try:

        class Basic(ctypes.Structure):
            _fields_ = [
                ("exit_status", ctypes.c_long),
                ("padding", ctypes.c_ulong),
                ("peb", ctypes.c_void_p),
                ("affinity", ctypes.c_void_p),
                ("base_priority", ctypes.c_long),
                ("unique_pid", ctypes.c_void_p),
                ("inherited_pid", ctypes.c_void_p),
            ]

        info = Basic()
        nt = ctypes.WinDLL("ntdll")
        nt.NtQueryInformationProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        nt.NtQueryInformationProcess.restype = ctypes.c_long
        status = nt.NtQueryInformationProcess(
            handle, 0, ctypes.byref(info), ctypes.sizeof(info), None
        )
        if status != 0 or not info.peb:
            return None
        params = ctypes.c_void_p()
        peb_address = int(info.peb)
        if not kernel.ReadProcessMemory(
            handle,
            peb_address + 0x20,
            ctypes.byref(params),
            ctypes.sizeof(params),
            None,
        ):
            return None
        # RTL_USER_PROCESS_PARAMETERS.CurrentDirectory.DosPath is a UNICODE_STRING.
        raw = ctypes.create_string_buffer(16)
        if not kernel.ReadProcessMemory(handle, params.value + 0x38, raw, 16, None):
            return None
        length = int.from_bytes(raw.raw[0:2], "little")
        buffer_addr = int.from_bytes(raw.raw[8:16], "little")
        if not buffer_addr or length <= 0 or length > 32768:
            return None
        text_buffer = ctypes.create_string_buffer(length)
        if not kernel.ReadProcessMemory(handle, buffer_addr, text_buffer, length, None):
            return None
        return text_buffer.raw.decode("utf-16-le", errors="replace")
    except (OSError, ValueError, ctypes.ArgumentError):
        return None
    finally:
        kernel.CloseHandle(handle)


def active_processes(origin: Path) -> list[tuple[int, str]]:
    """Before: ``origin`` is the tree under protection.
    During: detect live command-line or cwd references, excluding this PID.
    After: return matching process descriptions for a fail-closed decision.
    """
    needle = os.path.normcase(str(origin.resolve()))
    found = []
    rows = _process_rows()
    own = os.getpid()
    excluded = {own}
    parent_by_pid = {row[0]: row[3] for row in rows if len(row) > 3}
    cursor = own
    while cursor in parent_by_pid and parent_by_pid[cursor] not in excluded:
        excluded.add(parent_by_pid[cursor])
        cursor = parent_by_pid[cursor]
    for row in rows:
        pid, command, cwd, _parent = (*row, None) if len(row) == 3 else row
        if pid in excluded:
            continue
        command_key = os.path.normcase(command or "")
        cwd_key = os.path.normcase(cwd or "")
        if (
            needle in command_key
            or cwd_key == needle
            or cwd_key.startswith(needle + os.sep)
        ):
            found.append((pid, command or cwd or ""))
    return found


def _verify_zip(zip_path: Path, manifest: list[dict[str, Any]]) -> None:
    """Before: zip and manifest are staged evidence.
    During: compare every member digest and exact member set.
    After: return only for a valid archive.
    """
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise ArchiveTreeError("zip checksum failed")
        expected = {str(row["rel"]) for row in manifest if not row.get("dir")}
        actual = set(archive.namelist())
        if actual != expected:
            raise ArchiveTreeError("zip member set differs from manifest")
        for row in manifest:
            if row.get("dir"):
                continue
            with archive.open(str(row["rel"])) as member:
                if _sha256_bytes(member.read()) != row["sha256"]:
                    raise ArchiveTreeError(f"zip hash differs: {row['rel']}")


def _manifest_for_entries(
    origin: Path, entries: list[dict[str, Any]], *, tree: bool = False
) -> list[dict[str, Any]]:
    """Before: entries are approved clone directories or tree.
    During: build one complete manifest with clone-relative names.
    After: return rows suitable for zip and independent restoration.
    """
    if tree:
        return _tree_rows(origin)
    result = []
    for entry in entries:
        clone = origin / str(entry["rel"])
        result.extend(
            {**row, "rel": f"{entry['rel']}/{row['rel']}"} for row in _tree_rows(clone)
        )
    return sorted(result, key=lambda row: (row["rel"], row.get("dir", False)))


def _atomic_json(path: Path, value: Any) -> None:
    """Before: ``value`` is JSON serializable.
    During: write, flush, fsync, and replace a sibling temporary file.
    After: ``path`` contains the complete JSON value or is unchanged.
    """
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _index_record(
    family: str,
    origin: Path,
    zip_path: Path,
    manifest_path: Path,
    entries: list[dict[str, Any]],
    list_sha: str,
) -> dict[str, Any]:
    """Before: verified archive artifacts exist.
    During: create the compact P7 ARCHIVADO row.
    After: return a row without per-file entries.
    """
    return {
        "status": "ARCHIVADO",
        "family": family,
        "origin": str(origin),
        "zip": str(zip_path),
        "manifest": str(manifest_path),
        "zip_sha256": p7_common.sha256_file(zip_path),
        "manifest_sha256": p7_common.sha256_file(manifest_path),
        "list_sha256": list_sha,
        "clones": [entry["rel"] for entry in entries],
    }


def _safe_remove(path: Path) -> None:
    """Before: ``path`` has passed manifest validation.
    During: unlink one regular non-link file.
    After: the file is absent or an exception stops retirement.
    """
    if p7_common.is_reparse_or_link(path) or not path.is_file():
        raise ArchiveTreeError(f"unsafe removal target: {path}")
    path.unlink()


def _preflight_retirement(origin: Path, manifest: list[dict[str, Any]]) -> None:
    """Before: ``origin`` is the archived batch under review.
    During: recheck links, metadata, bytes, extras, empty directories, and writability.
    After: return only when every planned deletion is safe and no process is live.
    """
    if active_processes(origin):
        raise ArchiveTreeError("live process references origin")
    expected = {row["rel"] for row in manifest}
    actual_rows = _tree_rows(origin)
    if {row["rel"] for row in actual_rows} != expected:
        raise ArchiveTreeError("origin has extra or missing files/directories")
    for row in manifest:
        if row.get("dir"):
            continue
        path = origin / row["rel"]
        mode = path.stat().st_mode
        if not os.access(path, os.W_OK) or not (mode & stat.S_IWRITE):
            raise ArchiveTreeError(f"origin file is read-only: {row['rel']}")
        info = path.stat()
        if (
            info.st_size != row["size"]
            or abs(info.st_mtime - row["mtime"]) > 1e-3
            or p7_common.sha256_file(path) != row["sha256"]
        ):
            raise ArchiveTreeError(f"origin changed: {row['rel']}")
    for path in origin.rglob("*"):
        if p7_common.is_reparse_or_link(path):
            raise ArchiveTreeError(f"link in origin: {path}")


def _retire(
    origin: Path,
    archive_root: Path,
    family: str,
    record: dict[str, Any],
    manifest: list[dict[str, Any]],
) -> None:
    """Before: the same archived batch is fully verified.
    During: write an incomplete recovery record, remove files, then complete it.
    After: only a vanished origin receives a complete RETIRADO row.
    """
    common_dir = _get_git_common_dir(origin)
    is_registered = False
    if common_dir is not None:
        is_registered = _is_worktree_registered(origin, common_dir)

    _preflight_retirement(origin, manifest)
    ledger = archive_root / "retirement_recovery.json"
    if ledger.exists():
        pending = json.loads(ledger.read_text(encoding="utf-8"))
        if (
            str(pending.get("origin")) != str(origin)
            or str(pending.get("family")) != family
        ):
            raise ArchiveTreeError("retirement recovery pending")
    _atomic_json(
        ledger,
        {
            "status": "IN_PROGRESS",
            "family": family,
            "origin": str(origin),
            "record": record,
            "manifest": manifest,
        },
    )
    for row in sorted(
        manifest, key=lambda item: len(item["rel"].split("/")), reverse=True
    ):
        if not row.get("dir"):
            _safe_remove(origin / row["rel"])
    for directory in sorted(
        (p for p in origin.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        directory.rmdir()
    if origin.exists() and any(origin.iterdir()):
        raise ArchiveTreeError("origin remains after retirement")
    origin.rmdir()
    rows = p7_common.load_jsonl_index(archive_root / "index.jsonl")
    rows.append(
        {
            "status": "RETIRADO",
            "family": family,
            "origin": str(origin),
            "archive": record["zip"],
            "manifest_sha256": record["manifest_sha256"],
        }
    )
    p7_common.write_jsonl_index_atomic(archive_root / "index.jsonl", rows)
    ledger.unlink(missing_ok=True)

    if is_registered and common_dir is not None:
        rem_res = _git_runner(
            ["git", "-C", str(common_dir), "worktree", "remove", str(origin)]
        )
        prune_res = _git_runner(["git", "-C", str(common_dir), "worktree", "prune"])
        if rem_res.returncode != 0 or prune_res.returncode != 0:
            raise ArchiveTreeError(
                f"git worktree deregistration failed: remove rc={rem_res.returncode}, prune rc={prune_res.returncode}"
            )


def _retire_existing(origin: Path, archive_root: Path, list_sha: str) -> None:
    """Before: an ARCHIVADO row identifies the requested batch.
    During: revalidate its zip and manifest, then perform fail-closed retirement.
    After: the same batch has a complete RETIRADO record or no deletion occurred.
    """
    index = archive_root / "index.jsonl"
    rows = p7_common.load_jsonl_index(index)
    record = next(
        (
            row
            for row in reversed(rows)
            if row.get("status") == "ARCHIVADO" and row.get("list_sha256") == list_sha
        ),
        None,
    )
    if record is None:
        raise ArchiveTreeError("no archived family matches list hash")
    manifest_path = Path(str(record["manifest"]))
    zip_path = Path(str(record["zip"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_zip(zip_path, manifest)
    if p7_common.sha256_file(manifest_path) != record.get("manifest_sha256"):
        raise ArchiveTreeError("manifest hash differs")
    _retire(origin, archive_root, str(record["family"]), record, manifest)


def _recover_retirement(archive_root: Path) -> None:  # noqa: C901
    """Before: a recovery ledger records an interrupted retirement.
    During: remove only remaining manifest members after hash checks and finish the ledger.
    After: RETIRADO is appended only when the origin is empty; otherwise the ledger remains.
    """
    ledger = archive_root / "retirement_recovery.json"
    data = json.loads(ledger.read_text(encoding="utf-8"))
    origin = Path(str(data["origin"]))
    manifest = list(data["manifest"])
    record = data["record"]
    if str(origin) != str(record["origin"]):
        raise ArchiveTreeError("recovery origin differs from record")
    if active_processes(origin):
        raise ArchiveTreeError("live process references origin")
    manifest_path = Path(str(record["manifest"]))
    zip_path = Path(str(record["zip"]))
    _verify_zip(zip_path, manifest)
    if p7_common.sha256_file(manifest_path) != record["manifest_sha256"]:
        raise ArchiveTreeError("manifest hash differs")
    partials = list(archive_root.glob(".*.tmp")) + list(zip_path.parent.glob(".*.tmp"))
    for partial in partials:
        partial.unlink(missing_ok=True)
    for row in manifest:
        if row.get("dir"):
            continue
        path = origin / row["rel"]
        if not path.exists():
            continue
        if (
            p7_common.is_reparse_or_link(path)
            or p7_common.sha256_file(path) != row["sha256"]
        ):
            raise ArchiveTreeError("recovery evidence differs")
        _safe_remove(path)
    if origin.exists():
        for directory in sorted(
            (p for p in origin.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            directory.rmdir()
        if any(origin.iterdir()):
            raise ArchiveTreeError("recovery left files in origin")
        origin.rmdir()
    rows = p7_common.load_jsonl_index(archive_root / "index.jsonl")
    if any(
        row.get("status") == "RETIRADO" and row.get("family") == record["family"]
        for row in rows
    ):
        ledger.unlink(missing_ok=True)
        return
    rows.append(
        {
            "status": "RETIRADO",
            "family": record["family"],
            "origin": str(origin),
            "archive": record["zip"],
            "manifest_sha256": record["manifest_sha256"],
        }
    )
    p7_common.write_jsonl_index_atomic(archive_root / "index.jsonl", rows)
    ledger.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:  # noqa: C901
    """Before: parsed CLI arguments identify disjoint roots.
    During: enforce limits, lock, process guard, archive verification, and optional retirement.
    After: return 0 for success, 1 for contract failure, or 4 for unavailable capacity/root.
    """
    requested_origin = args.origin
    origin = requested_origin
    stage = origin.parent / (".p7_" + "stage_" + args.prefix)
    if stage.exists():
        if not args.resume:
            raise ArchiveTreeError("staged batch requires --resume")
        origin = stage
    archive_root = args.archive_root
    if not archive_root.is_dir():
        return 4
    if not origin.is_dir() or p7_common.is_reparse_or_link(origin):
        return 4
    if (
        archive_root.resolve() == origin.resolve()
        or origin.resolve() in archive_root.resolve().parents
    ):
        return 2
    if (
        args.min_libre > 0
        and archive_root.is_dir()
        and shutil.disk_usage(archive_root).free < args.min_libre
    ):
        return 4
    if args.min_libre > 0 and not archive_root.is_dir() and not args.dry_run:
        return 4
    before_origin = tree_hash(origin)
    candidates = [origin] if getattr(args, "tree", False) else _candidate_dirs(origin)
    if not candidates:
        raise ArchiveTreeError("no candidates")
    entries = _approved_entries(
        args.list_path, args.list_sha256, origin, tree=getattr(args, "tree", False)
    )
    selected = {entry["rel"] for entry in entries}
    if args.max_bytes >= 0:
        total = sum(
            path.stat().st_size
            for entry in entries
            for path in (origin / entry["rel"]).rglob("*")
            if path.is_file()
        )
        if total > args.max_bytes:
            raise ArchiveTreeError("max_bytes exceeded")
    if active_processes(origin):
        raise ArchiveTreeError("live process references origin")
    before_archive = tree_hash(archive_root) if archive_root.is_dir() else "absent"
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "candidates": sorted(selected),
                    "origin_sha256": before_origin,
                    "archive_sha256": before_archive,
                },
                sort_keys=True,
            )
        )
        return 0
    if not archive_root.is_dir():
        return 4
    lock = archive_root / ".p7.lock"
    p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(Path.cwd()))
    original_origin = requested_origin
    moved_to_stage = False
    resumed_stage = stage.exists() and args.resume
    try:
        if args.apply_retire:
            _retire_existing(origin, archive_root, args.list_sha256)
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        family = f"{args.prefix}_{stamp}"
        family_dir = archive_root / family
        if family_dir.exists():
            raise ArchiveTreeError("archive family already exists")
        family_dir.mkdir()
        zip_path = family_dir / f"{family}.zip"
        manifest_path = family_dir / f"{family}.manifest.json"
        manifest = _manifest_for_entries(
            origin, entries, tree=getattr(args, "tree", False)
        )
        temp_zip = family_dir / f".{zip_path.name}.tmp"
        with zipfile.ZipFile(
            temp_zip, "x", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for row in manifest:
                if not row.get("dir"):
                    archive.write(origin / row["rel"], row["rel"])
        _verify_zip(temp_zip, manifest)
        os.replace(temp_zip, zip_path)
        _atomic_json(manifest_path, manifest)
        record = _index_record(
            family,
            origin,
            zip_path,
            manifest_path,
            entries,
            args.list_sha256 or "derived",
        )
        index = archive_root / "index.jsonl"
        rows = p7_common.load_jsonl_index(index)
        rows.append(record)
        p7_common.write_jsonl_index_atomic(index, rows)
        if args.apply_archive and resumed_stage and stage.exists():
            for entry in entries:
                staged = stage / entry["rel"]
                if staged.exists():
                    shutil.move(str(staged), str(original_origin / entry["rel"]))
            stage.rmdir()
        if stage == origin and stage.exists():
            stage.rmdir()
        return 0
    except Exception:
        if moved_to_stage and stage.exists():
            for entry in entries:
                staged = stage / entry["rel"]
                if staged.exists() and not (original_origin / entry["rel"]).exists():
                    shutil.move(str(staged), str(original_origin / entry["rel"]))
            with suppress(OSError):
                stage.rmdir()
        raise
    finally:
        p7_common.release_lock(lock)


def _store_path() -> Path:
    """Before: the host home directory is the user-data root.
    During: append the canonical T3 state-store path to ``Path.home()``.
    After: return the path without opening or creating the store.
    """
    return Path.home() / ".t3" / "userdata" / "statev2.sqlite"


def _authorization_spent(ledger: vua.ChainAuthorityLedger, message_id: str) -> bool:
    """Before: ``ledger`` identifies the retirement authority log.
    During: validate the fixed step through the ledger, then inspect every step.
    After: return whether this message has been consumed by any chain step.
    """
    if ledger.is_consumed(message_id, RETIRE_STEP):
        return True
    if not ledger.path.exists():
        return False
    try:
        with ledger.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.strip():
                    item = ledger._strict_json_loads(raw.strip())
                    if isinstance(item, dict) and item.get("messageId") == message_id:
                        return True
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise vua.InfraError("chain-ledger-corrupt-line", str(exc)) from exc
    return False


def _authorize_retire(args: argparse.Namespace) -> tuple[int, str | None] | None:  # noqa: C901
    """Before: retire arguments identify an archived family and user message.
    During: validate store provenance, exact phrase, origin identity, and ledger state.
    After: consume one authority step or return a fail-closed cause/rc.
    """
    if not args.archive_root.is_dir():
        return 4, None
    connection = vua.open_store_ro(_store_path())
    try:
        vua.check_schema(connection)
        cause = vua._thread_rejection(connection, args.thread_id)
        if cause:
            return 1, cause
        record, decision = vua._load_anchor(connection, args.message_id)
        if record is None:
            return 1, decision.reason
        if record.thread_id != args.thread_id:
            return 1, "thread-mismatch"
        rows = p7_common.load_jsonl_index(args.archive_root / "index.jsonl")
        row = next(
            (
                item
                for item in reversed(rows)
                if item.get("status") == "ARCHIVADO"
                and item.get("list_sha256") == args.list_sha256
            ),
            None,
        )
        if row is None:
            raise ArchiveTreeError("no archived family matches list hash")
        expected = (
            f"RETIRAR {row['family']} {str(row['list_sha256'])[:12].lower()} "
            f"{len(row['clones'])}"
        )
        failure = vua._chain_candidate_failure(record, expected)
        if failure is not None:
            return 1, failure
        if os.path.normcase(str(args.origin.resolve())) != os.path.normcase(
            str(Path(str(row["origin"])).resolve())
        ):
            return 1, "origin-mismatch"
        ledger = vua.ChainAuthorityLedger(args.archive_root / CHAIN_LEDGER_NAME)
        if _authorization_spent(ledger, args.message_id):
            return 1, "retire-consumed"
        if not args.origin.is_dir() or p7_common.is_reparse_or_link(args.origin):
            return 4, None
        if not ledger.consume(args.message_id, RETIRE_STEP, "ARCHIVADO", "RETIRADO"):
            return 1, "retire-consumed"
        return None
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Before: command-line arguments are untrusted.
    During: parse defaults and dispatch the fail-closed operation.
    After: print a diagnostic and return the documented integer status.
    """
    parser = argparse.ArgumentParser(
        description="Versioned clone-tree archiver; dry-run is the default"
    )
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--list", dest="list_path", type=Path)
    parser.add_argument("--list-sha256")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-archive", action="store_true")
    parser.add_argument("--apply-retire", action="store_true")
    parser.add_argument("--recover-retirement", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--thread-id")
    parser.add_argument("--message-id")
    parser.add_argument("--min-dias", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=-1)
    parser.add_argument("--min-libre", type=int, default=0)
    parser.add_argument("--hilos", type=int, default=4)
    parser.add_argument("--tamano-lote", type=int, default=0)
    parser.add_argument("--prefijo-familia", dest="prefix", default="clone_archive")
    parser.add_argument("--umbral-hilo", type=int, default=1024 * 1024)
    parser.add_argument("--tree", action="store_true")
    parser.add_argument("--ticket")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--integrated-into")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--owner-session")
    args = parser.parse_args(argv)
    apply_plain = args.apply
    if apply_plain and (args.apply_archive or args.apply_retire):
        print(
            "ERROR: --apply cannot be combined with --apply-archive or --apply-retire",
            file=sys.stderr,
        )
        return 2
    if apply_plain:
        print(
            "ERROR: --apply is disabled; use --apply-archive or --apply-retire",
            file=sys.stderr,
        )
        return 2
    if args.recover_retirement:
        print("ERROR: --recover-retirement is disabled", file=sys.stderr)
        return 2
    if args.resume and args.apply_retire:
        print("ERROR: --resume cannot be used with --apply-retire", file=sys.stderr)
        return 2
    if args.apply_retire and not args.thread_id:
        print("ERROR: --thread-id es obligatorio", file=sys.stderr)
        return 2
    if args.apply_retire and not args.message_id:
        print("ERROR: --message-id es obligatorio", file=sys.stderr)
        return 2
    args.apply = args.apply or args.apply_archive or args.apply_retire
    args.dry_run = not args.apply
    if args.recover_retirement:
        if not args.archive_root.is_dir():
            return 4
        lock = args.archive_root / ".p7.lock"
        try:
            p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(Path.cwd()))
            _recover_retirement(args.archive_root)
            return 0
        except (
            ArchiveTreeError,
            p7_common.ArchiveError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            with suppress(Exception):
                p7_common.release_lock(lock)
    if args.apply and (args.list_path is None or args.list_sha256 is None):
        print("ERROR: --apply requires --list and --list-sha256", file=sys.stderr)
        return 2
    try:
        if args.tree:
            _verify_tree_conditions(args, args.origin)
        if args.apply_retire:
            authorization = _authorize_retire(args)
            if authorization is not None:
                rc, cause = authorization
                if cause is not None:
                    print(f"ERROR: {cause}", file=sys.stderr)
                return rc
        return run(args)
    except (
        ArchiveTreeError,
        p7_common.ArchiveError,
        OSError,
        ValueError,
        zipfile.BadZipFile,
        vua.InfraError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
