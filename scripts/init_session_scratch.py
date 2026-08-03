#!/usr/bin/env python3
# ruff: noqa: S603, S607
"""Session scratch infrastructure (WOT-2026-022c).

Manages ``<root>/.agent/runtime/session/<session_id>/`` with 6 subcommands:
init, add, list, audit, archive, gc.

Design decisions (plan v2, plan-audit adversarial with probes executed):
- ``--project-root`` OBLIGATORIO. NEVER calls ``resolve_project_root()`` (lru_cache
  trap: ``runtime/project_root.py:82`` is ``@lru_cache(maxsize=1)`` with NO args ->
  constant cache key, heated at import-time -> override does not win).
- Writer: ``O_APPEND`` + ``O_BINARY`` + OS-level exclusive lock
  (``msvcrt.locking`` on nt, ``fcntl.flock`` on posix). Append-only strict, no tail-cap.
- Lock: TTL pure (``expires_at``, 900s, primary authority; pattern
  ``bus/builder_locks.py:104-132`` ``builder_alive``). ``is_pid_alive_best_effort``
  = pattern ``tests/conftest.py:114`` (fail-safe to ALIVE), auxiliary signal only in
  archive/gc. Takeover atomic (``O_CREAT|O_EXCL``) + marker ``.takeover`` with TTL 60s.
- ``required`` CONDITIONAL by event: ``lock_reclaimed`` -> ``frozenset()`` empty.
- Exit codes hybrid (E1): infrastructure -> exit 0 + ``degraded: true``; usage -> exit 2;
  OK -> exit 0.
- E1 OPT-OUT (WOT-2026-043t): ``add --require-write`` -> exit 3 when the append
  fails. E1 is right for telemetry (a disk failure must not kill a flight) and
  WRONG when the record IS the audit trail: a failed append writes NOTHING, so
  the loss is silent and indistinguishable from "nothing happened". Opt-in, so
  every existing caller keeps E1 unchanged.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# MOTOR_ROOT for sys.path (from __file__). NEVER resolve_project_root().
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from bus.redact import redact_payload  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCK_TTL = 900
TAKEOVER_TTL = 60
KEEP_LAST_K = 10
# WOT-2026-043t: exit code for `add --require-write` when the append fails. It is
# NOT 2 (usage) nor 0 (the E1 degraded default): a caller must be able to tell
# "the evidence did not land" apart from both a bad invocation and a soft skip.
EXIT_WRITE_REQUIRED = 3
MANIFEST_NAME = "manifest.jsonl"
LOCK_NAME = "lock.json"
STATE_NAME = ".session_state.json"
TAKEOVER_NAME = ".takeover"
ARCHIVE_DIRNAME = "_archive"

SESSION_ID_RE = re.compile(r"^\d{8}-\d{4}-(?:[0-9a-f]{4,40}|nogit)-[0-9a-f]{4,32}$")

EVENTS = frozenset(
    {
        "artifact_added",
        "artifact_decision",
        "lock_reclaimed",
        "batch_retry",
        # WOT-2026-026d: process-audit REFERENCE events. Each captures a POINTER
        # (hash/path/id) to something produced during the session so the close
        # audit (Bloque 2.5) can cross prompts-designed / tools-used / ensemble
        # rounds / triage decisions against the scorecard. They carry a
        # `reference`, NEVER a copy of the payload (the scorecard owns the
        # per-round verdict -- one datum, one writer).
        "prompt_designed",
        "tool_used",
        "ensemble_ref",
        "backlog_triage_decision",
    }
)

REQUIRED_BY_EVENT: dict[str, frozenset[str]] = {
    "artifact_added": frozenset({"generator", "artifact_path"}),
    # WOT-2026-022e: artifact_path is required here too so the cross-record
    # completeness check below (added-vs-decided, matched BY artifact_path) has
    # a path to match on. The CLI parser already accepted --artifact-path on
    # any event (cmd_add writes it whenever present) -- this only tightens the
    # per-record contract, it does not add new CLI surface.
    "artifact_decision": frozenset({"generator", "decision", "artifact_path"}),
    "lock_reclaimed": frozenset(),
    # WOT-2026-023w: the autonomous-batch anti-loop rule
    # (prompts/orchestrator_autonomous_ticket_batch.md) records each failed
    # attempt so a retry can declare a DIFFERENT enfoque than the ones already
    # tried. Without enfoque_intentado the record cannot discriminate a repeat,
    # so it is the one mandatory field; the rest are allowlisted below.
    "batch_retry": frozenset({"enfoque_intentado"}),
    # WOT-2026-026d: each process-audit event needs its `reference` pointer so
    # the record is not an empty marker. `generator` names WHO produced it; the
    # rest of the payload is a reference (hash/path/id), never a copy.
    "prompt_designed": frozenset({"generator", "reference"}),
    "tool_used": frozenset({"generator", "reference"}),
    "ensemble_ref": frozenset({"generator", "reference"}),
    "backlog_triage_decision": frozenset({"generator", "reference"}),
}

LEDGER_FIELDS = frozenset(
    {
        "ts",
        "session_id",
        "event",
        "repo_role",
        "generator",
        "prompt_version",
        "prompt_override",
        "artifact_path",
        "ticket_id",
        "invocation_count",
        "error_count",
        "corrected_after_use",
        "decision",
        # WOT-2026-023w: autonomous-batch anti-loop record (event=batch_retry).
        # Before this, the allowlist scrub (cmd_add) silently DROPPED every one
        # of these, so the batch's anti-loop rule would have been unverifiable
        # on the first run WITH retries -- the executor could not read the
        # enfoques already tried because the ledger threw them away. The ticket
        # field maps to the existing ticket_id above.
        "stage",
        "gate_fallante",
        "subtipo_cem",
        "evidencia",
        "enfoque_intentado",
        "refutacion",
        # WOT-2026-026d: pointer for the process-audit reference events
        # (prompt_designed / tool_used / ensemble_ref / backlog_triage_decision).
        # A reference (hash/path/id), never a copy of the referenced payload.
        "reference",
    }
)

REPO_ROLES = frozenset({"motor", "no_motor", "unknown"})

# ---------------------------------------------------------------------------
# OS-level file locking (conditional import, portable)
# ---------------------------------------------------------------------------

if os.name == "nt":
    import msvcrt

    def _lock_fd_exclusive(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        for _ in range(200):
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:  # noqa: PERF203
                time.sleep(0.005)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _unlock_fd(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_fd_exclusive(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_prompt_bytes(data: str | bytes) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data.replace(b"\r\n", b"\n").rstrip()


def _hash_prompt(data: str | bytes) -> str:
    return hashlib.sha256(_normalize_prompt_bytes(data)).hexdigest()


def _short_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "nogit"


def _generate_session_id(root: Path) -> str:
    now = datetime.now(timezone.utc)
    sha = _short_sha(root)
    suffix = secrets.token_hex(2)
    return f"{now.strftime('%Y%m%d-%H%M')}-{sha}-{suffix}"


def _validate_session_id(sid: str) -> bool:
    return bool(SESSION_ID_RE.match(sid))


def _validate_project_root(root_str: str) -> Path | None:
    root = Path(root_str).resolve()
    if not root.is_dir():
        return None
    if not (root / ".agent").is_dir():
        return None
    return root


def _detect_repo_role(root: Path) -> str:
    if (root / ".agent" / "agent_controller.py").is_file():
        return "motor"
    if (root / ".agent").is_dir():
        return "no_motor"
    return "unknown"


def _session_root(root: Path) -> Path:
    return root / ".agent" / "runtime" / "session"


def _session_dir(root: Path, sid: str) -> Path:
    return _session_root(root) / sid


def _archive_root(root: Path) -> Path:
    return _session_root(root) / ARCHIVE_DIRNAME


def _lock_path(session_dir: Path) -> Path:
    return session_dir / LOCK_NAME


def _manifest_path(session_dir: Path) -> Path:
    return session_dir / MANIFEST_NAME


def _state_path(session_dir: Path) -> Path:
    return session_dir / STATE_NAME


def _enum_sessions(root: Path, include_archive: bool = False) -> list[str]:  # noqa: C901
    sroot = _session_root(root)
    if not sroot.is_dir():
        return []
    result: list[str] = []
    for child in sorted(sroot.iterdir()):
        if not child.is_dir():
            continue
        if not _validate_session_id(child.name):
            continue
        if child.name == ARCHIVE_DIRNAME:
            continue
        result.append(child.name)
    if include_archive:
        adir = _archive_root(root)
        if adir.is_dir():
            for child in sorted(adir.iterdir()):
                if not child.is_dir():
                    continue
                if not _validate_session_id(child.name):
                    continue
                result.append(child.name)
    return result


def _enum_archived_sessions(root: Path) -> list[str]:
    adir = _archive_root(root)
    if not adir.is_dir():
        return []
    result: list[str] = []
    for child in sorted(adir.iterdir()):
        if not child.is_dir():
            continue
        if not _validate_session_id(child.name):
            continue
        result.append(child.name)
    return result


_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _validate_artifact_path(path_str: str, session_dir: Path) -> bool:
    try:
        p = Path(path_str)
    except (ValueError, TypeError):
        return False
    if p.is_absolute():
        return False
    if _DRIVE_LETTER_RE.match(path_str):
        return False
    resolved = (session_dir / p).resolve()
    try:
        resolved.relative_to(session_dir.resolve())
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Ledger writer (append-only with OS-level lock)
# ---------------------------------------------------------------------------


def _append_record(manifest: Path, record: dict) -> None:
    """Append a record to the manifest ledger.

    Append-only strict: never edit or delete a record. Uses O_APPEND + O_BINARY +
    OS-level exclusive lock to prevent corruption under concurrency (B1/B2).
    """
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    flags = os.O_CREAT | os.O_APPEND | os.O_RDWR | getattr(os, "O_BINARY", 0)
    fd = os.open(str(manifest), flags)
    try:
        _lock_fd_exclusive(fd)
        try:
            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, payload)
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def _read_manifest(manifest: Path) -> list[dict]:
    if not manifest.exists():
        return []
    records: list[dict] = []
    raw = manifest.read_bytes()
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            records.append(
                {"_parse_error": True, "_raw": line.decode("utf-8", "replace")}
            )
    return records


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------


def _read_lock(lock_path: Path) -> dict | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _lock_is_live(lock_data: dict | None) -> bool:
    if not lock_data:
        return False
    expires_at_str = lock_data.get("expires_at")
    if not expires_at_str:
        return False
    try:
        expires_at = datetime.fromisoformat(str(expires_at_str))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) < expires_at


def _is_pid_alive_best_effort(pid: int) -> bool:
    """Check if a process is alive. Fail-safe to ALIVE (conftest.py:114 pattern).

    On any doubt or error, returns True (treat as alive -> do NOT purge/archive).
    Only unambiguously-dead pids return False.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        tasklist = shutil.which("tasklist")
        if not tasklist:
            return True
        try:
            result = subprocess.run(
                [tasklist, "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return True
        return result.returncode == 0 and str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _write_lock(session_dir: Path, sid: str, op: str) -> Path:
    lock_path = _lock_path(session_dir)
    now = datetime.now(timezone.utc)
    data = {
        "pid": os.getpid(),
        "session_id": sid,
        "op": op,
        "created_at": now.isoformat(),
        "expires_at": (now + _td_seconds(LOCK_TTL)).isoformat(),
    }
    lock_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return lock_path


def _try_create_lock_exclusive(session_dir: Path, sid: str, op: str) -> bool:
    """Atomically create lock.json via O_CREAT|O_EXCL. Returns True if won."""
    lock_path = _lock_path(session_dir)
    try:
        fd = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        )
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        now = datetime.now(timezone.utc)
        data = {
            "pid": os.getpid(),
            "session_id": sid,
            "op": op,
            "created_at": now.isoformat(),
            "expires_at": (now + _td_seconds(LOCK_TTL)).isoformat(),
        }
        os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _td_seconds(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def _acquire_lock(session_dir: Path, sid: str, op: str) -> bool:
    """Acquire the session lock. Returns True if acquired (new or reclaimed).

    Ownership is (pid, session_id) -- the SAME pair ``_release_lock`` requires to
    let go of a lock (WOT-2026-023l). Acquisition used to check only the pid, so a
    live lock written by THIS process for a DIFFERENT session was stolen: the
    ``pid != os.getpid()`` guard was False, execution fell through to
    ``_takeover_lock``, which unlinks the lock and recreates it. O_EXCL does not
    protect against that -- the unlink frees the path first. The thief then held a
    lock it could never release (``_release_lock`` demands a matching session_id):
    false ownership. Reproduced deterministically: two SEQUENTIAL acquisitions both
    returned True.

    On a LIVE lock:
      - held by a living foreign process -> False;
      - held by THIS process for THIS session -> True, idempotent: the lock is left
        byte-for-byte untouched (this is the legitimate resume path; it used to go
        through the takeover and rewrite the lock for no reason);
      - held by THIS process for ANOTHER session -> False. Same process, different
        owner.
    A STALE lock (expired, or a dead pid) is reclaimed via the atomic takeover, as
    before.
    """
    lock_path = _lock_path(session_dir)
    if not lock_path.exists():
        return _try_create_lock_exclusive(session_dir, sid, op)

    lock_data = _read_lock(lock_path)
    if _lock_is_live(lock_data):
        pid = lock_data.get("pid", 0) if lock_data else 0
        if pid == os.getpid():
            holder = lock_data.get("session_id") if lock_data else None
            return holder == sid
        if _is_pid_alive_best_effort(pid):
            return False
    return _takeover_lock(session_dir, sid, op)


def _revalidate_before_unlink(lock_path: Path, sid: str) -> bool | None:
    """WOT-2026-023s: re-read the lock inside the takeover, before unlinking it.

    Returns a final verdict to short-circuit the takeover, or None to proceed with the
    unlink+create. Called ONLY with the ``.takeover`` marker held, which serialises
    takeovers: the only other writer of lock.json in this window is the O_EXCL creation
    of a lock that did NOT exist, so it cannot resurrect a live one.

    Without this, a contender whose "stale" verdict (taken in _acquire_lock, before the
    marker) went out of date unlinks a LIVE, FOREIGN lock and takes it -- false
    ownership (_release_lock then refuses to let go). Identity order is pid THEN sid,
    matching _acquire_lock, so a foreign process sharing a session_id is not us.
    """
    current = _read_lock(lock_path)
    if not _lock_is_live(current):
        return None  # genuinely stale -> proceed with the reclaim
    cur_pid = current.get("pid", 0) if current else 0
    if cur_pid == os.getpid():
        # our own live lock: idempotent re-entry, leave it byte-for-byte
        return (current.get("session_id") if current else None) == sid
    if _is_pid_alive_best_effort(cur_pid):
        return False  # live and foreign: do NOT steal it (this was the TOCTOU)
    return None  # foreign but dead -> a legitimate reclaim, proceed


def _takeover_lock(session_dir: Path, sid: str, op: str) -> bool:
    """Atomically reclaim a stale lock via ``.takeover`` marker with TTL.

    Pattern: ``bus/builder_locks.py:246-289`` ``_claim_requeue``.
    The ``.takeover`` marker has its own TTL (60s) to prevent permanent deadlock
    if the process dies after creating the marker (B4).
    """
    takeover_path = session_dir / TAKEOVER_NAME
    try:
        fd = os.open(str(takeover_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            age = time.time() - takeover_path.stat().st_mtime
        except OSError:
            return False
        if age < TAKEOVER_TTL:
            return False
        with contextlib.suppress(OSError):
            takeover_path.unlink()
        try:
            fd = os.open(str(takeover_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError:
            return False
    except OSError:
        return False

    try:
        lock_path = _lock_path(session_dir)
        # WOT-2026-023s: revalidate WITH the marker held, BEFORE the unlink (the read
        # that decided "stale" in _acquire_lock may itself be stale by now).
        verdict = _revalidate_before_unlink(lock_path, sid)
        if verdict is not None:
            return verdict
        with contextlib.suppress(OSError):
            lock_path.unlink()
        if not _try_create_lock_exclusive(session_dir, sid, op):
            return False
        manifest = _manifest_path(session_dir)
        if manifest.exists():
            record = {
                "ts": _now_iso(),
                "session_id": sid,
                "event": "lock_reclaimed",
            }
            with contextlib.suppress(OSError):
                _append_record(manifest, record)
        return True
    finally:
        with contextlib.suppress(OSError):
            takeover_path.unlink()


def _release_lock(session_dir: Path, sid: str) -> bool:
    """Release the lock only if it belongs to us (pid + session_id)."""
    lock_path = _lock_path(session_dir)
    if not lock_path.exists():
        return True
    lock_data = _read_lock(lock_path)
    if not lock_data:
        return False
    if lock_data.get("pid") == os.getpid() and lock_data.get("session_id") == sid:
        with contextlib.suppress(OSError):
            lock_path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _ensure_verification_mode(root: Path) -> None:
    """Enciende el modo verificacion del Stop hook al abrir sesion (WOT-2026-044u).

    Cierra el cableado: sin esto, el centinela dependia de que un humano se
    acordara de crearlo, y una barrera que nadie invoca es una norma, no un
    mecanismo (AGENTS.md).

    Usa `ensure_on`, NO `turn_on`: si el centinela ya existe se conserva su
    baseline. Re-medirlo en un resume lo compararia contra un arbol que YA
    incluye el trabajo hecho, y la mutacion dejaria de verse.

    FAIL-OPEN TOTAL y silencioso: encender una barrera de higiene jamas puede
    romper un `init` ni ensuciar su salida JSON, que otros consumen.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from verification_mode import ensure_on

        ensure_on(root, quiet=True)
    except Exception:
        return


def cmd_init(args: argparse.Namespace) -> int:  # noqa: C901
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"status": "error", "reason": "invalid project root"}))
        return 2

    sid = args.session_id if args.session_id else _generate_session_id(root)
    if not _validate_session_id(sid):
        print(json.dumps({"status": "error", "reason": f"invalid session_id: {sid}"}))
        return 2

    repo_role = args.repo_role if args.repo_role else _detect_repo_role(root)
    if repo_role not in REPO_ROLES:
        print(
            json.dumps({"status": "error", "reason": f"invalid repo_role: {repo_role}"})
        )
        return 2

    sdir = _session_dir(root, sid)
    prompt_version: dict[str, str] | None = None
    if args.prompt_type or args.prompt_content:
        pv_type = args.prompt_type or ""
        pv_hash = _hash_prompt(args.prompt_content) if args.prompt_content else ""
        prompt_version = {"type": pv_type, "sha256": pv_hash}

    if sdir.exists():
        state_path = _state_path(sdir)
        if not state_path.exists():
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "session dir exists but state file absent",
                        "session_intact": True,
                    }
                )
            )
            return 2
        try:
            existing_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "session state file unreadable",
                        "session_intact": True,
                    }
                )
            )
            return 2

        identity_match = (
            existing_state.get("generator") == (args.generator or "")
            and existing_state.get("prompt_version") == prompt_version
            and existing_state.get("repo_role") == repo_role
        )
        if not identity_match:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "session identity mismatch (not a resume)",
                        "session_intact": True,
                    }
                )
            )
            return 2

        if not _acquire_lock(sdir, sid, "init"):
            print(
                json.dumps(
                    {
                        "status": "error",
                        "reason": "lock held by live foreign process",
                        "session_intact": True,
                    }
                )
            )
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "session_id": sid,
                    "session_dir": str(sdir),
                    "resumed": True,
                }
            )
        )
        return 0

    sroot = _session_root(root)
    try:
        sroot.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": f"cannot create session root: {exc}",
                }
            )
        )
        return 2

    try:
        os.mkdir(str(sdir))
    except FileExistsError:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "session dir created concurrently",
                    "session_intact": True,
                }
            )
        )
        return 2
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": f"cannot create session dir: {exc}",
                }
            )
        )
        return 2

    state = {
        "session_id": sid,
        "generator": args.generator or "",
        "prompt_version": prompt_version,
        "repo_role": repo_role,
        "created_at": _now_iso(),
    }
    _state_path(sdir).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_lock(sdir, sid, "init")
    _ensure_verification_mode(root)
    print(
        json.dumps(
            {
                "status": "ok",
                "session_id": sid,
                "session_dir": str(sdir),
                "resumed": False,
            }
        )
    )
    return 0


def cmd_add(args: argparse.Namespace) -> int:  # noqa: C901
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"written": False, "reason": "invalid project root"}))
        return 2

    sid = args.session_id
    if not _validate_session_id(sid):
        print(json.dumps({"written": False, "reason": f"invalid session_id: {sid}"}))
        return 2

    event = args.event
    if event not in EVENTS:
        print(json.dumps({"written": False, "reason": f"unknown event: {event}"}))
        return 2

    sdir = _session_dir(root, sid)
    if not sdir.is_dir():
        print(
            json.dumps(
                {"written": False, "reason": f"session dir does not exist: {sid}"}
            )
        )
        return 2

    repo_role = args.repo_role if args.repo_role else _detect_repo_role(root)
    if repo_role not in REPO_ROLES:
        print(
            json.dumps({"written": False, "reason": f"invalid repo_role: {repo_role}"})
        )
        return 2

    required = REQUIRED_BY_EVENT[event]
    if "generator" in required and not args.generator:
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": f"missing required field for event={event}: generator",
                }
            )
        )
        return 2
    if "decision" in required and not args.decision:
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": f"missing required field for event={event}: decision",
                }
            )
        )
        return 2
    if "artifact_path" in required and not args.artifact_path:
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": f"missing required field for event={event}: artifact_path",
                }
            )
        )
        return 2
    if "enfoque_intentado" in required and not args.enfoque_intentado:
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": (
                        f"missing required field for event={event}: enfoque_intentado"
                    ),
                }
            )
        )
        return 2
    if "reference" in required and not args.reference:
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": f"missing required field for event={event}: reference",
                }
            )
        )
        return 2

    artifact_path = args.artifact_path
    if artifact_path is not None and not _validate_artifact_path(artifact_path, sdir):
        print(
            json.dumps(
                {
                    "written": False,
                    "reason": f"artifact_path outside session dir: {artifact_path}",
                }
            )
        )
        return 2

    prompt_version: dict[str, str] | None = None
    if args.prompt_type or args.prompt_content:
        pv_type = args.prompt_type or ""
        pv_hash = _hash_prompt(args.prompt_content) if args.prompt_content else ""
        prompt_version = {"type": pv_type, "sha256": pv_hash}

    prompt_override: dict[str, str] | None = None
    if args.override_name:
        prompt_override = {args.override_name: args.override_reason or ""}

    record: dict[str, Any] = {
        "ts": _now_iso(),
        "session_id": sid,
        "event": event,
        "repo_role": repo_role,
    }
    if args.generator:
        record["generator"] = args.generator
    if prompt_version:
        record["prompt_version"] = prompt_version
    if prompt_override:
        record["prompt_override"] = prompt_override
    if artifact_path is not None:
        record["artifact_path"] = artifact_path
    if args.ticket_id:
        record["ticket_id"] = args.ticket_id
    if args.invocation_count is not None:
        record["invocation_count"] = args.invocation_count
    if args.error_count is not None:
        record["error_count"] = args.error_count
    if args.corrected_after_use:
        record["corrected_after_use"] = True
    if args.decision:
        record["decision"] = args.decision
    # WOT-2026-023w: anti-loop fields for event=batch_retry.
    if args.stage:
        record["stage"] = args.stage
    if args.gate_fallante:
        record["gate_fallante"] = args.gate_fallante
    if args.subtipo_cem:
        record["subtipo_cem"] = args.subtipo_cem
    if args.evidencia:
        record["evidencia"] = args.evidencia
    if args.enfoque_intentado:
        record["enfoque_intentado"] = args.enfoque_intentado
    if args.refutacion:
        record["refutacion"] = args.refutacion
    # WOT-2026-026d: reference pointer for the process-audit events.
    if args.reference:
        record["reference"] = args.reference

    scrubbed: dict[str, Any] = {k: v for k, v in record.items() if k in LEDGER_FIELDS}
    scrubbed = redact_payload(scrubbed)

    manifest = _manifest_path(sdir)
    try:
        _append_record(manifest, scrubbed)
    except OSError as exc:
        # WOT-2026-043t: --require-write turns the E1 degraded exit 0 into a hard
        # failure for callers whose record IS the evidence. Default behaviour is
        # unchanged (exit 0 + degraded), so no existing caller regresses.
        degraded_payload = {
            "written": False,
            "degraded": True,
            "reason": f"manifest not writable: {exc}",
        }
        if getattr(args, "require_write", False):
            degraded_payload["required_write"] = True
            print(json.dumps(degraded_payload))
            return EXIT_WRITE_REQUIRED
        print(json.dumps(degraded_payload))
        return 0
    print(json.dumps({"written": True, "session_id": sid, "event": event}))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"status": "error", "reason": "invalid project root"}))
        return 2

    session_ids = _enum_sessions(root, include_archive=args.include_archive)
    sessions: list[dict[str, Any]] = []
    for sid in session_ids:
        sdir = _session_dir(root, sid)
        if _archive_root(root) in sdir.parents or sdir.parent == _archive_root(root):
            actual_dir = _archive_root(root) / sid
        else:
            actual_dir = sdir
        manifest = _manifest_path(actual_dir)
        records = _read_manifest(manifest) if manifest.exists() else []
        lock_data = _read_lock(_lock_path(actual_dir))
        lock_state = "live" if _lock_is_live(lock_data) else "stale"
        if lock_data is None:
            lock_state = "none"
        sessions.append(
            {
                "session_id": sid,
                "record_count": len(records),
                "lock_state": lock_state,
                "archived": actual_dir.parent == _archive_root(root),
            }
        )
    print(json.dumps({"sessions": sessions}))
    return 0


def _audit_session(sdir: Path, sid: str) -> dict[str, Any]:
    manifest = _manifest_path(sdir)
    records = _read_manifest(manifest) if manifest.exists() else []
    findings: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        line_no = i + 1
        if rec.get("_parse_error"):
            findings.append(
                {
                    "line": line_no,
                    "error": "parse error: invalid JSON",
                }
            )
            continue
        event = rec.get("event")
        if event not in EVENTS:
            findings.append(
                {
                    "line": line_no,
                    "error": f"unknown event: {event}",
                }
            )
            continue
        required = REQUIRED_BY_EVENT.get(event, frozenset())
        findings.extend(
            {
                "line": line_no,
                "error": f"missing required field for event={event}: {field}",
            }
            for field in required
            if field not in rec or rec[field] in (None, "", [])
        )
        repo_role = rec.get("repo_role")
        if repo_role is not None and repo_role not in REPO_ROLES:
            findings.append(
                {
                    "line": line_no,
                    "error": f"invalid repo_role: {repo_role}",
                }
            )
        ts = rec.get("ts")
        if ts:
            try:
                datetime.fromisoformat(str(ts))
            except (ValueError, TypeError):
                findings.append(
                    {
                        "line": line_no,
                        "error": f"invalid ts: {ts}",
                    }
                )
        pv = rec.get("prompt_version")
        if pv is not None and (not isinstance(pv, dict) or "sha256" not in pv):
            findings.append(
                {
                    "line": line_no,
                    "error": "prompt_version missing sha256",
                }
            )

    # WOT-2026-022e: cross-record completeness invariant. Identity of an
    # artifact = artifact_path (SET semantics, not multiset: the same path
    # added twice is still one artifact, one decision covers it). Matching is
    # order-insensitive -- the ledger is append-only, so a decision covers its
    # artifact_path whether it was recorded before or after the corresponding
    # artifact_added. An empty session (no artifact_added at all) satisfies
    # the invariant vacuously: there is nothing to lose.
    added_paths = {
        rec["artifact_path"]
        for rec in records
        if rec.get("event") == "artifact_added" and rec.get("artifact_path")
    }
    decided_paths = {
        rec["artifact_path"]
        for rec in records
        if rec.get("event") == "artifact_decision" and rec.get("artifact_path")
    }
    findings.extend(
        {
            "line": None,
            "error": f"missing artifact_decision for artifact_path: {path}",
        }
        for path in sorted(added_paths - decided_paths)
    )

    return {
        "session_id": sid,
        "records": len(records),
        "findings": findings,
        "valid": len(findings) == 0,
    }


def cmd_audit(args: argparse.Namespace) -> int:
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"status": "error", "reason": "invalid project root"}))
        return 2

    sid = args.session_id
    if not _validate_session_id(sid):
        print(json.dumps({"status": "error", "reason": f"invalid session_id: {sid}"}))
        return 2

    sdir = _session_dir(root, sid)
    if not sdir.is_dir():
        print(
            json.dumps(
                {"status": "error", "reason": f"session dir does not exist: {sid}"}
            )
        )
        return 2

    result = _audit_session(sdir, sid)
    print(json.dumps(result))
    if result["valid"]:
        return 0
    return 0 if args.report_only else 1


def cmd_archive(args: argparse.Namespace) -> int:  # noqa: C901
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"status": "error", "reason": "invalid project root"}))
        return 2

    sid = args.session_id
    if not _validate_session_id(sid):
        print(json.dumps({"status": "error", "reason": f"invalid session_id: {sid}"}))
        return 2

    sdir = _session_dir(root, sid)
    if not sdir.is_dir():
        print(
            json.dumps(
                {"status": "error", "reason": f"session dir does not exist: {sid}"}
            )
        )
        return 2

    lock_data = _read_lock(_lock_path(sdir))
    if _lock_is_live(lock_data):
        pid = lock_data.get("pid", 0) if lock_data else 0
        if pid != os.getpid() and _is_pid_alive_best_effort(pid):
            print(
                json.dumps(
                    {
                        "status": "stop",
                        "reason": f"lock live: pid {pid} alive",
                        "session_intact": True,
                    }
                )
            )
            return 2

    audit_result = _audit_session(sdir, sid)
    if not audit_result["valid"]:
        print(
            json.dumps(
                {
                    "status": "stop",
                    "reason": "audit failed",
                    "findings": audit_result["findings"],
                    "session_intact": True,
                }
            )
        )
        return 1

    adir = _archive_root(root)
    dest = adir / sid
    if dest.exists():
        print(
            json.dumps(
                {
                    "status": "stop",
                    "reason": f"archive destination already exists: {sid}",
                    "session_intact": True,
                }
            )
        )
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "dry_run": True,
                    "session_id": sid,
                    "archive_dir": str(dest),
                }
            )
        )
        return 0

    try:
        adir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "stop",
                    "reason": f"cannot create archive dir: {exc}",
                    "session_intact": True,
                }
            )
        )
        return 2

    try:
        os.replace(str(sdir), str(dest))
    except (PermissionError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "stop",
                    "reason": f"os.replace failed: {exc}",
                    "session_intact": True,
                }
            )
        )
        return 2

    print(
        json.dumps(
            {
                "status": "ok",
                "session_id": sid,
                "archive_dir": str(dest),
            }
        )
    )
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    root = _validate_project_root(args.project_root)
    if root is None:
        print(json.dumps({"status": "error", "reason": "invalid project root"}))
        return 2

    archived = _enum_archived_sessions(root)
    archived.sort()
    to_delete = archived[:-KEEP_LAST_K] if len(archived) > KEEP_LAST_K else []
    kept = archived[-KEEP_LAST_K:] if len(archived) > KEEP_LAST_K else archived

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "dry_run": True,
                    "archived_count": len(archived),
                    "would_keep": len(kept),
                    "would_delete": len(to_delete),
                    "would_delete_sessions": to_delete,
                }
            )
        )
        return 0

    deleted: list[str] = []
    for sid in to_delete:
        adir = _archive_root(root) / sid
        try:
            shutil.rmtree(str(adir))
            deleted.append(sid)
        except OSError:
            pass

    print(
        json.dumps(
            {
                "status": "ok",
                "archived_count": len(archived),
                "kept": len(kept),
                "deleted": len(deleted),
                "deleted_sessions": deleted,
            }
        )
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Session scratch infrastructure (WOT-2026-022c)."
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Target repo root (must exist and have .agent/). OBLIGATORIO.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_p = subparsers.add_parser("init", help="Initialize a session scratch dir.")
    init_p.add_argument("--session-id", default=None, help="Override session ID.")
    init_p.add_argument("--generator", default=None, help="Generator name.")
    init_p.add_argument("--prompt-type", default=None, help="Prompt type.")
    init_p.add_argument(
        "--prompt-content", default=None, help="Prompt content to hash."
    )
    init_p.add_argument("--repo-role", default=None, help="Override repo role.")
    init_p.set_defaults(func=cmd_init)

    add_p = subparsers.add_parser("add", help="Append a record to the session ledger.")
    add_p.add_argument("--session-id", required=True, help="Session ID.")
    add_p.add_argument("--event", required=True, help="Event type.")
    add_p.add_argument("--generator", default=None, help="Generator name.")
    add_p.add_argument("--prompt-type", default=None, help="Prompt type.")
    add_p.add_argument("--prompt-content", default=None, help="Prompt content to hash.")
    add_p.add_argument("--override-name", default=None, help="Prompt override name.")
    add_p.add_argument(
        "--override-reason", default=None, help="Prompt override reason."
    )
    add_p.add_argument("--artifact-path", default=None, help="Relative artifact path.")
    add_p.add_argument("--ticket-id", default=None, help="Ticket ID.")
    add_p.add_argument("--invocation-count", type=int, default=None)
    add_p.add_argument("--error-count", type=int, default=None)
    add_p.add_argument(
        "--corrected-after-use",
        action="store_true",
        default=False,
    )
    add_p.add_argument("--decision", default=None, help="Decision text.")
    add_p.add_argument("--repo-role", default=None, help="Override repo role.")
    # WOT-2026-043t: opt-in fail-closed for records that ARE the evidence.
    # The E1 hybrid contract (module docstring) is deliberate: a disk failure in
    # session infrastructure must NOT kill a flight, so `add` returns exit 0 with
    # `degraded: true`. That is right for telemetry -- and WRONG when the record
    # is the audit trail itself: a `preexisting_gate_unblock` receipt that never
    # lands leaves NO line in the manifest (measured 2026-08-04: the 3 real
    # manifests contain 0 `degraded` markers, because a failed append writes
    # nothing at all). The absence is silent and indistinguishable from "there
    # was no unblock". Callers whose record is evidence pass this flag; E1 is
    # preserved for every existing caller, which is why it is opt-in.
    add_p.add_argument(
        "--require-write",
        action="store_true",
        help=(
            "Fail closed (exit 3) if the record cannot be appended, instead of "
            "the default degraded exit 0. Use when the record IS the evidence."
        ),
    )
    # WOT-2026-023w: anti-loop fields for event=batch_retry.
    add_p.add_argument(
        "--stage", default=None, help="Owner-stage of the failed attempt."
    )
    add_p.add_argument(
        "--gate-fallante", default=None, help="Gate that failed on this attempt."
    )
    add_p.add_argument(
        "--subtipo-cem", default=None, help="CEM subtype of the failure."
    )
    add_p.add_argument(
        "--evidencia",
        default=None,
        help="Evidence (command/exit/output) of the failure.",
    )
    add_p.add_argument(
        "--enfoque-intentado",
        default=None,
        help="Approach attempted (anti-loop discriminator; required for batch_retry).",
    )
    add_p.add_argument(
        "--refutacion", default=None, help="Why the attempted approach was refuted."
    )
    # WOT-2026-026d: reference pointer for process-audit events
    # (prompt_designed / tool_used / ensemble_ref / backlog_triage_decision).
    add_p.add_argument(
        "--reference",
        default=None,
        help=(
            "Reference pointer (hash/path/id) for a process-audit event; "
            "never a copy of the referenced payload."
        ),
    )
    add_p.set_defaults(func=cmd_add)

    list_p = subparsers.add_parser("list", help="List sessions.")
    list_p.add_argument(
        "--include-archive",
        action="store_true",
        default=False,
        help="Also list archived sessions.",
    )
    list_p.set_defaults(func=cmd_list)

    audit_p = subparsers.add_parser("audit", help="Audit a session ledger.")
    audit_p.add_argument("--session-id", required=True, help="Session ID.")
    audit_p.add_argument(
        "--report-only",
        action="store_true",
        default=False,
        help="Report only, always exit 0 (for 022e informational use).",
    )
    audit_p.set_defaults(func=cmd_audit)

    archive_p = subparsers.add_parser("archive", help="Archive a session.")
    archive_p.add_argument("--session-id", required=True, help="Session ID.")
    archive_p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be archived without writing.",
    )
    archive_p.set_defaults(func=cmd_archive)

    gc_p = subparsers.add_parser("gc", help="Garbage-collect archived sessions.")
    gc_p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be deleted without writing.",
    )
    gc_p.set_defaults(func=cmd_gc)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
