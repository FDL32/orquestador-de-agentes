"""Tests for init_session_scratch.py (WOT-2026-022c).

Discriminating tests: each barrier has a mutation that makes its test FAIL.
Structural isolation (not discipline): all harnesses pass --project-root <tmp under
REAL_SYSTEM_TEMP>; sentinel by unique session_id; session-scoped fixture hashes
ONLY <motor>/.agent/runtime/session/ before/after.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _MOTOR_ROOT / "scripts" / "init_session_scratch.py"

if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.init_session_scratch import (  # noqa: E402
    KEEP_LAST_K,
    TAKEOVER_TTL,
    _acquire_lock,
    _append_record,
    _audit_session,
    _enum_archived_sessions,
    _enum_sessions,
    _hash_prompt,
    _is_pid_alive_best_effort,
    _lock_is_live,
    _read_lock,
    _release_lock,
    _try_create_lock_exclusive,
    _validate_artifact_path,
    _validate_project_root,
    _validate_session_id,
    _write_lock,
)

from tests.conftest import REAL_SYSTEM_TEMP  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sentinel_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%d-%H%M')}-nogit-{uuid.uuid4().hex}"


def _make_repo(base: Path, name: str, with_git: bool = True) -> Path:
    repo = base / name
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".agent").mkdir(exist_ok=True)
    if with_git:
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
    return repo


def _run_scratch(
    args: list[str],
    cwd: str | None = None,
    env: dict | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCRIPT), *args]
    run_env = os.environ.copy() if env is None else env
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=run_env,
        timeout=timeout,
    )


def _hash_dir(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        rel = item.relative_to(path)
        h.update(str(rel).encode("utf-8"))
        h.update(b"\0")
        if item.is_file():
            h.update(item.read_bytes())
    return h.hexdigest()


def _init_session(
    repo: Path, sid: str, generator: str = "test", **kwargs: str
) -> subprocess.CompletedProcess:
    args = [
        "--project-root",
        str(repo),
        "init",
        "--session-id",
        sid,
        "--generator",
        generator,
    ]
    for k, v in kwargs.items():
        args.extend([f"--{k.replace('_', '-')}", v])
    return _run_scratch(args)


def _add_record(
    repo: Path, sid: str, event: str = "artifact_added", **kwargs: str
) -> subprocess.CompletedProcess:
    args = [
        "--project-root",
        str(repo),
        "add",
        "--session-id",
        sid,
        "--event",
        event,
    ]
    for k, v in kwargs.items():
        args.extend([f"--{k.replace('_', '-')}", v])
    return _run_scratch(args)


# ---------------------------------------------------------------------------
# Session-scoped isolation fixture (hashes ONLY motor session/ before/after)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _motor_session_pristine():
    motor_session = _MOTOR_ROOT / ".agent" / "runtime" / "session"
    before = _hash_dir(motor_session)
    yield before
    after = _hash_dir(motor_session)
    assert before == after, (
        f"Motor session dir changed (state leak): "
        f"before={before[:16]}, after={after[:16]}"
    )


# ---------------------------------------------------------------------------
# M1: Agnosticism (3 disjoint axes)
# ---------------------------------------------------------------------------


class TestM1Agnosticism:
    """M1: the script MUST write to --project-root, NEVER to motor or cwd.

    3 disjoint axes: cwd=neutral, __file__=motor (fixed), --project-root=repoA/repoB.
    Subprocess with env=os.environ.copy(). Asserts in order: returncode==0,
    POSITIVE, then NEGATIVE.
    """

    def test_m1_writes_to_project_root_not_motor(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"m1_repo_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        neutral_dir = _make_repo(REAL_SYSTEM_TEMP, f"m1_neutral_{uuid.uuid4().hex[:8]}")

        result = _run_scratch(
            ["--project-root", str(repo), "init", "--session-id", sid],
            cwd=str(neutral_dir),
        )

        assert result.returncode == 0, f"stdout={result.stdout}, stderr={result.stderr}"

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        assert session_dir.is_dir(), f"Session not created in repo: {session_dir}"

        motor_session = _MOTOR_ROOT / ".agent" / "runtime" / "session" / sid
        assert not motor_session.exists(), f"Session leaked to MOTOR: {motor_session}"

        neutral_session = neutral_dir / ".agent" / "runtime" / "session" / sid
        assert not neutral_session.exists(), (
            f"Session leaked to cwd (neutral dir): {neutral_session}"
        )

    def test_m1_two_distinct_repos(self, tmp_path):
        repo_a = _make_repo(REAL_SYSTEM_TEMP, f"m1_A_{uuid.uuid4().hex[:8]}")
        repo_b = _make_repo(REAL_SYSTEM_TEMP, f"m1_B_{uuid.uuid4().hex[:8]}")
        sid_a = _sentinel_id()
        sid_b = _sentinel_id()

        r_a = _run_scratch(
            ["--project-root", str(repo_a), "init", "--session-id", sid_a],
            cwd=str(REAL_SYSTEM_TEMP),
        )
        r_b = _run_scratch(
            ["--project-root", str(repo_b), "init", "--session-id", sid_b],
            cwd=str(REAL_SYSTEM_TEMP),
        )

        assert r_a.returncode == 0
        assert r_b.returncode == 0

        assert (repo_a / ".agent" / "runtime" / "session" / sid_a).is_dir()
        assert (repo_b / ".agent" / "runtime" / "session" / sid_b).is_dir()
        assert not (repo_b / ".agent" / "runtime" / "session" / sid_a).exists()
        assert not (repo_a / ".agent" / "runtime" / "session" / sid_b).exists()


# ---------------------------------------------------------------------------
# T-LEDGER-CONC: concurrent writes, all present, 0 CRLF
# ---------------------------------------------------------------------------


class TestLedgerConcurrency:
    """B1/B2: O_APPEND + O_BINARY + OS lock -> no lost/corrupted records, 0 CRLF."""

    def test_concurrent_adds_all_present_no_crlf(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"conc_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        n_procs = 4
        m_adds = 25

        procs: list[subprocess.Popen] = []
        idx = 0
        for _ in range(n_procs):
            for _ in range(m_adds):
                p = subprocess.Popen(
                    [
                        sys.executable,
                        str(_SCRIPT),
                        "--project-root",
                        str(repo),
                        "add",
                        "--session-id",
                        sid,
                        "--event",
                        "artifact_added",
                        "--generator",
                        "conc_test",
                        "--artifact-path",
                        f"artifact_{idx}.txt",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ.copy(),
                )
                procs.append(p)
                idx += 1

        for p in procs:
            p.wait(timeout=60)

        manifest = repo / ".agent" / "runtime" / "session" / sid / "manifest.jsonl"
        raw = manifest.read_bytes()

        assert b"\r\n" not in raw, "CRLF bytes found in manifest (B2 violation)"

        lines = [ln for ln in raw.split(b"\n") if ln.strip()]
        expected = n_procs * m_adds
        assert len(lines) == expected, (
            f"Lost records: expected {expected}, got {len(lines)} (B1 violation)"
        )

        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
                assert rec["event"] == "artifact_added"
            except (json.JSONDecodeError, KeyError) as exc:  # noqa: PERF203
                pytest.fail(f"Corrupt record at line {i}: {exc}: {line!r}")


# ---------------------------------------------------------------------------
# T-TAKEOVER-FOSIL: old .takeover marker -> not blocked
# ---------------------------------------------------------------------------


class TestTakeoverFosil:
    """B4: marker .takeover with TTL -> old marker doesn't deadlock."""

    def test_old_takeover_marker_does_not_block(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"fosil_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        old_lock = {
            "pid": 999999,
            "session_id": "old",
            "op": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=100)
            ).isoformat(),
        }
        (session_dir / "lock.json").write_text(json.dumps(old_lock), encoding="utf-8")

        takeover_path = session_dir / ".takeover"
        takeover_path.write_text("stale", encoding="utf-8")

        old_time = time.time() - (TAKEOVER_TTL + 30)
        os.utime(str(takeover_path), (old_time, old_time))

        result = _acquire_lock(session_dir, sid, "init")
        assert result is True, "Takeover blocked by stale .takeover marker (B4)"

        lock_data = _read_lock(session_dir / "lock.json")
        assert lock_data is not None
        assert lock_data["pid"] == os.getpid()

    def test_fresh_takeover_marker_blocks(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"fresh_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        old_lock = {
            "pid": 999999,
            "session_id": "old",
            "op": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=100)
            ).isoformat(),
        }
        (session_dir / "lock.json").write_text(json.dumps(old_lock), encoding="utf-8")

        takeover_path = session_dir / ".takeover"
        takeover_path.write_text("active", encoding="utf-8")

        result = _acquire_lock(session_dir, sid, "init")
        assert result is False, "Takeover should be blocked by fresh .takeover marker"


# ---------------------------------------------------------------------------
# T-ARCHIVE-DEST-EXISTE: _archive/<id> exists -> STOP fail-closed
# ---------------------------------------------------------------------------


class TestArchiveDestExists:
    """B3: archive destination exists -> STOP, session INTACT."""

    def test_archive_dest_exists_stop(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"arch_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        archive_dir = repo / ".agent" / "runtime" / "session" / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        dest = archive_dir / sid
        dest.mkdir()

        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid]
        )

        assert result.returncode != 0, "Archive should STOP when dest exists"
        output = json.loads(result.stdout)
        assert output["status"] == "stop"
        assert "already exists" in output["reason"], (
            f"Should report dest-exists, got: {output['reason']}"
        )
        assert output["session_intact"] is True

        assert session_dir.is_dir(), "Session dir should be INTACT (not moved)"


# ---------------------------------------------------------------------------
# Fail-open (exit 0 + degraded) and exit 2 (usage error)
# ---------------------------------------------------------------------------


class TestExitCodes:
    """E1: infrastructure -> exit 0 + degraded; usage -> exit 2; OK -> exit 0."""

    def test_add_fail_open_manifest_not_writable(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"fo_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        manifest = repo / ".agent" / "runtime" / "session" / sid / "manifest.jsonl"
        manifest.write_text("", encoding="utf-8")
        os.chmod(str(manifest), stat.S_IREAD)

        result = _add_record(repo, sid, generator="test", artifact_path="file.txt")

        os.chmod(str(manifest), stat.S_IWRITE | stat.S_IREAD)

        assert result.returncode == 0, (
            f"add should be fail-OPEN (exit 0): stdout={result.stdout}"
        )
        output = json.loads(result.stdout)
        assert output["written"] is False
        assert output.get("degraded") is True

    def test_add_exit2_artifact_path_outside(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"e2_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(
            repo,
            sid,
            generator="test",
            artifact_path="../../etc/passwd",
        )

        assert result.returncode == 2, (
            f"add should exit 2 for bad artifact_path: stdout={result.stdout}"
        )
        output = json.loads(result.stdout)
        assert output["written"] is False

    def test_add_exit2_unknown_event(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"ev_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(repo, sid, event="bogus_event", generator="test")

        assert result.returncode == 2

    def test_add_exit2_missing_generator_for_artifact_added(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"mg_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(
            repo, sid, event="artifact_added", artifact_path="file.txt"
        )

        assert result.returncode == 2

    def test_add_exit2_missing_artifact_path_for_artifact_added(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"map_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(repo, sid, event="artifact_added", generator="test")

        assert result.returncode == 2, (
            f"add should exit 2 for artifact_added without artifact_path: "
            f"stdout={result.stdout}"
        )
        output = json.loads(result.stdout)
        assert "artifact_path" in output["reason"]

    def test_init_exit2_invalid_project_root(self, tmp_path):
        result = _run_scratch(["--project-root", "C:/nonexistent/path", "init"])
        assert result.returncode == 2


# ---------------------------------------------------------------------------
# lock_reclaimed without generator -> audit clean (anti-fosilizacion)
# ---------------------------------------------------------------------------


class TestLockReclaimedAudit:
    """D6: lock_reclaimed requires NO generator/artifact_path -> audit clean."""

    def test_lock_reclaimed_no_generator_audit_clean(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"lr_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "lock_reclaimed",
                "repo_role": "unknown",
            },
        )

        result = _audit_session(session_dir, sid)
        assert result["valid"] is True, (
            f"lock_reclaimed should be valid without generator: {result['findings']}"
        )

    def test_artifact_decision_requires_decision(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"ad_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "artifact_decision",
                "repo_role": "unknown",
                "generator": "test",
            },
        )

        result = _audit_session(session_dir, sid)
        assert result["valid"] is False, (
            "artifact_decision without decision should be invalid"
        )

    def test_artifact_added_requires_artifact_path(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"aap_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "artifact_added",
                "repo_role": "unknown",
                "generator": "test",
            },
        )

        result = _audit_session(session_dir, sid)
        assert result["valid"] is False, (
            "artifact_added without artifact_path should be invalid "
            f"(022e would consume it empty): {result['findings']}"
        )


# ---------------------------------------------------------------------------
# CRLF/LF -> same sha256
# ---------------------------------------------------------------------------


class TestPromptHashNormalization:
    """D8: prompt_version.sha256 over normalized bytes (CRLF->LF + rstrip)."""

    def test_crlf_lf_same_hash(self):
        lf_content = "line1\nline2\nline3\n"
        crlf_content = "line1\r\nline2\r\nline3\r\n"
        assert _hash_prompt(lf_content) == _hash_prompt(crlf_content)

    def test_rstrip_normalization(self):
        content_with_trailing = "line1\nline2\n  \n"
        content_stripped = "line1\nline2"
        assert _hash_prompt(content_with_trailing) == _hash_prompt(content_stripped)

    def test_bytes_and_str_same(self):
        text = "hello world\n"
        assert _hash_prompt(text) == _hash_prompt(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# list/gc ignore _archive; gc keep-last-K
# ---------------------------------------------------------------------------


class TestEnumAndGc:
    """D4': ALLOWLIST filters _archive; gc keep-last-K of ARCHIVED sessions."""

    def test_enum_sessions_ignores_archive(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"enum_{uuid.uuid4().hex[:8]}")
        active_sid = _sentinel_id()
        archived_sid = _sentinel_id()

        session_root = repo / ".agent" / "runtime" / "session"
        (session_root / active_sid).mkdir(parents=True, exist_ok=True)
        archive_dir = session_root / "_archive"
        (archive_dir / archived_sid).mkdir(parents=True, exist_ok=True)

        garbage_dir = session_root / "garbage_dir"
        garbage_dir.mkdir()

        result = _enum_sessions(repo)
        assert active_sid in result
        assert archived_sid not in result
        assert "_archive" not in result
        assert "garbage_dir" not in result, (
            "Regex filter should reject non-session-id dirs"
        )

    def test_enum_sessions_include_archive(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"ina_{uuid.uuid4().hex[:8]}")
        active_sid = _sentinel_id()
        archived_sid = _sentinel_id()

        session_root = repo / ".agent" / "runtime" / "session"
        (session_root / active_sid).mkdir(parents=True, exist_ok=True)
        archive_dir = session_root / "_archive"
        (archive_dir / archived_sid).mkdir(parents=True, exist_ok=True)

        result = _enum_sessions(repo, include_archive=True)
        assert active_sid in result
        assert archived_sid in result

    def test_gc_keep_last_k(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"gck_{uuid.uuid4().hex[:8]}")
        archive_dir = repo / ".agent" / "runtime" / "session" / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        total = KEEP_LAST_K + 5
        sids: list[str] = []
        for i in range(total):
            sid = f"20260101-0001-nogit-{i:032x}"
            sids.append(sid)
            (archive_dir / sid).mkdir()

        result = _run_scratch(["--project-root", str(repo), "gc", "--dry-run"])
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["archived_count"] == total
        assert output["would_keep"] == KEEP_LAST_K
        assert output["would_delete"] == total - KEEP_LAST_K

        result = _run_scratch(["--project-root", str(repo), "gc"])
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["deleted"] == total - KEEP_LAST_K

        remaining = _enum_archived_sessions(repo)
        assert len(remaining) == KEEP_LAST_K


# ---------------------------------------------------------------------------
# Audit modes: exit 1 default, --report-only exit 0
# ---------------------------------------------------------------------------


class TestAuditModes:
    """D11: audit exit 1 by default, --report-only exit 0 ALWAYS."""

    def test_audit_exit1_when_invalid(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"au1_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "artifact_decision",
                "repo_role": "unknown",
                "generator": "test",
            },
        )

        result = _run_scratch(
            ["--project-root", str(repo), "audit", "--session-id", sid]
        )
        assert result.returncode == 1

    def test_audit_report_only_exit0_when_invalid(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"au0_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "artifact_decision",
                "repo_role": "unknown",
                "generator": "test",
            },
        )

        result = _run_scratch(
            [
                "--project-root",
                str(repo),
                "audit",
                "--session-id",
                sid,
                "--report-only",
            ]
        )
        assert result.returncode == 0

    def test_audit_exit0_when_valid(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"auok_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")

        result = _run_scratch(
            ["--project-root", str(repo), "audit", "--session-id", sid]
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Lock: TTL pure, release only if mine, pid alive best-effort
# ---------------------------------------------------------------------------


class TestLockManagement:
    """D10': lock TTL pure (expires_at); release only if mine; pid fail-safe."""

    def test_lock_is_live_ttl_pure(self, tmp_path):
        now = datetime.now(timezone.utc)
        live_lock = {
            "pid": 999999,
            "session_id": "test",
            "op": "init",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=300)).isoformat(),
        }
        assert _lock_is_live(live_lock) is True

        expired_lock = {
            "pid": os.getpid(),
            "session_id": "test",
            "op": "init",
            "created_at": now.isoformat(),
            "expires_at": (now - timedelta(seconds=1)).isoformat(),
        }
        assert _lock_is_live(expired_lock) is False

    def test_lock_is_live_corrupt(self, tmp_path):
        assert _lock_is_live(None) is False
        assert _lock_is_live({}) is False
        assert _lock_is_live({"pid": 1}) is False
        assert _lock_is_live({"expires_at": "not-a-date"}) is False

    def test_release_lock_not_mine(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"rl_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        foreign_lock = {
            "pid": 999999,
            "session_id": "not-my-sid",
            "op": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=300)
            ).isoformat(),
        }
        lock_path = session_dir / "lock.json"
        lock_path.write_text(json.dumps(foreign_lock), encoding="utf-8")

        result = _release_lock(session_dir, sid)
        assert result is False
        assert lock_path.exists(), "release_lock should NOT delete foreign lock"

    def test_release_lock_mine(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"rm_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        _write_lock(session_dir, sid, "init")
        result = _release_lock(session_dir, sid)
        assert result is True
        assert not (session_dir / "lock.json").exists()

    def test_pid_alive_best_effort_self(self, tmp_path):
        assert _is_pid_alive_best_effort(os.getpid()) is True

    def test_pid_alive_best_effort_dead(self, tmp_path):
        assert _is_pid_alive_best_effort(-1) is False
        assert _is_pid_alive_best_effort(0) is False

    def test_acquire_lock_new(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"al_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        assert _acquire_lock(session_dir, sid, "init") is True
        lock_data = _read_lock(session_dir / "lock.json")
        assert lock_data is not None
        assert lock_data["pid"] == os.getpid()
        assert lock_data["session_id"] == sid

    def test_acquire_lock_expired_takeover(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"at_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        old_lock = {
            "pid": 999999,
            "session_id": "old-session",
            "op": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=100)
            ).isoformat(),
        }
        (session_dir / "lock.json").write_text(json.dumps(old_lock), encoding="utf-8")

        assert _acquire_lock(session_dir, sid, "init") is True
        lock_data = _read_lock(session_dir / "lock.json")
        assert lock_data["pid"] == os.getpid()

    def test_try_create_lock_exclusive_only_one_wins(self, tmp_path):
        """Deterministic test of the atomic lock primitive (portable).

        The threading race test (test_takeover_competition_exactly_one_wins)
        is environment-dependent: it only catches the race on Linux/CI, not on
        Windows (GIL + scheduling). This test verifies the atomic primitive
        directly: O_CREAT|O_EXCL guarantees exactly 1 winner on ANY OS.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tcx_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        assert _try_create_lock_exclusive(session_dir, sid, "init") is True
        assert _try_create_lock_exclusive(session_dir, sid, "init") is False

        lock_data = _read_lock(session_dir / "lock.json")
        assert lock_data is not None
        assert lock_data["pid"] == os.getpid()
        assert lock_data["session_id"] == sid


# ---------------------------------------------------------------------------
# Init idempotency: resume vs fail-closed
# ---------------------------------------------------------------------------


class TestInitIdempotency:
    """init: resume if identity matches, fail-closed if not."""

    def test_init_resume_same_identity(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"res_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()

        r1 = _init_session(repo, sid, generator="orchestrator")
        assert r1.returncode == 0
        assert json.loads(r1.stdout)["resumed"] is False

        r2 = _init_session(repo, sid, generator="orchestrator")
        assert r2.returncode == 0
        assert json.loads(r2.stdout)["resumed"] is True

    def test_init_fail_closed_identity_mismatch(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"mm_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()

        r1 = _init_session(repo, sid, generator="orchestrator")
        assert r1.returncode == 0

        r2 = _init_session(repo, sid, generator="different_generator")
        assert r2.returncode == 2
        output = json.loads(r2.stdout)
        assert output["session_intact"] is True

    def test_init_creates_container_and_leaf(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"cl_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()

        result = _init_session(repo, sid)
        assert result.returncode == 0

        session_root = repo / ".agent" / "runtime" / "session"
        assert session_root.is_dir()
        assert (session_root / sid).is_dir()
        assert (session_root / sid / ".session_state.json").is_file()
        assert (session_root / sid / "lock.json").is_file()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidation:
    """D2/D4': validate project root, session_id, artifact_path."""

    def test_validate_project_root_no_agent(self, tmp_path):
        base = REAL_SYSTEM_TEMP / f"npa_{uuid.uuid4().hex[:8]}"
        base.mkdir()
        assert _validate_project_root(str(base)) is None

    def test_validate_project_root_nonexistent(self, tmp_path):
        assert _validate_project_root("C:/nonexistent/path/xyz") is None

    def test_validate_project_root_valid(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"vp_{uuid.uuid4().hex[:8]}")
        result = _validate_project_root(str(repo))
        assert result is not None
        assert result == repo.resolve()

    def test_session_id_regex_valid(self, tmp_path):
        assert _validate_session_id("20260711-1432-b4cd641-3f2a")
        assert _validate_session_id("20260711-1432-nogit-abc123")
        assert _validate_session_id("20260711-1432-nogit-" + "a" * 32)

    def test_session_id_regex_invalid(self, tmp_path):
        assert not _validate_session_id("_archive")
        assert not _validate_session_id("SENTINEL-abc123")
        assert not _validate_session_id("20260711-1432-b4cd641")
        assert not _validate_session_id("")

    def test_validate_artifact_path_relative_ok(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"apr_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        assert _validate_artifact_path("subdir/file.txt", session_dir) is True
        assert _validate_artifact_path("file.txt", session_dir) is True

    def test_validate_artifact_path_absolute_rejected(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"apa_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        assert _validate_artifact_path("C:/tmp/file.txt", session_dir) is False

    def test_validate_artifact_path_escape_rejected(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"ape_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        assert _validate_artifact_path("../../etc/passwd", session_dir) is False


# ---------------------------------------------------------------------------
# Archive: full flow
# ---------------------------------------------------------------------------


class TestArchiveFlow:
    """D12': archive fail-closed, audit-then-move, session INTACT on failure."""

    def test_archive_success(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"as_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")

        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid]
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "ok"

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        archive_dest = repo / ".agent" / "runtime" / "session" / "_archive" / sid
        assert not session_dir.exists()
        assert archive_dest.is_dir()

    def test_archive_dry_run(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"adr_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")

        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid, "--dry-run"]
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["dry_run"] is True

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        assert session_dir.is_dir(), "Dry-run should NOT move the session"

    def test_archive_audit_fail_stops(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"af_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = session_dir / "manifest.jsonl"
        _append_record(
            manifest,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "event": "artifact_decision",
                "repo_role": "unknown",
                "generator": "test",
            },
        )

        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid]
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "stop"
        assert output["session_intact"] is True
        assert session_dir.is_dir(), "Session should be INTACT after audit fail"


# ---------------------------------------------------------------------------
# Maiden voyage: 2 sessions, takeover competition
# ---------------------------------------------------------------------------


class TestMaidenVoyage:
    """Maiden voyage: 2 sessions don't collide; takeover competition."""

    def test_two_sessions_no_collision(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"mv_{uuid.uuid4().hex[:8]}")
        sid_a = _sentinel_id()
        sid_b = _sentinel_id()

        r_a = _init_session(repo, sid_a, generator="procA")
        r_b = _init_session(repo, sid_b, generator="procB")

        assert r_a.returncode == 0
        assert r_b.returncode == 0

        dir_a = repo / ".agent" / "runtime" / "session" / sid_a
        dir_b = repo / ".agent" / "runtime" / "session" / sid_b
        assert dir_a.is_dir()
        assert dir_b.is_dir()
        assert dir_a != dir_b

    def test_takeover_competition_exactly_one_wins(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tc_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        session_dir.mkdir(parents=True, exist_ok=True)

        old_lock = {
            "pid": 999999,
            "session_id": "old",
            "op": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=100)
            ).isoformat(),
        }
        (session_dir / "lock.json").write_text(json.dumps(old_lock), encoding="utf-8")

        results: list[bool] = []

        def try_acquire():
            results.append(_acquire_lock(session_dir, sid, "init"))

        import threading

        threads = [threading.Thread(target=try_acquire) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wins = sum(1 for r in results if r is True)
        assert wins == 1, f"Exactly 1 should win, got {wins}"

    def test_interruption_leaves_session_intact(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"int_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")

        audit_result = _run_scratch(
            ["--project-root", str(repo), "audit", "--session-id", sid]
        )
        assert audit_result.returncode == 0

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        assert session_dir.is_dir(), "Session should be intact after audit-only"

        resume = _init_session(repo, sid, generator="test")
        assert resume.returncode == 0
        assert json.loads(resume.stdout)["resumed"] is True


# ---------------------------------------------------------------------------
# List subcommand
# ---------------------------------------------------------------------------


class TestListCommand:
    """list: enumerate sessions, exclude _archive."""

    def test_list_shows_active_sessions(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"ls_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _run_scratch(["--project-root", str(repo), "list"])
        assert result.returncode == 0
        output = json.loads(result.stdout)
        sids = [s["session_id"] for s in output["sessions"]]
        assert sid in sids

    def test_list_excludes_archive(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"la_{uuid.uuid4().hex[:8]}")
        active_sid = _sentinel_id()
        archived_sid = _sentinel_id()

        _init_session(repo, active_sid)
        _init_session(repo, archived_sid)
        _add_record(repo, archived_sid, generator="test", artifact_path="file.txt")
        _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", archived_sid]
        )

        result = _run_scratch(["--project-root", str(repo), "list"])
        assert result.returncode == 0
        output = json.loads(result.stdout)
        sids = [s["session_id"] for s in output["sessions"]]
        assert active_sid in sids
        assert archived_sid not in sids


# ---------------------------------------------------------------------------
# repo_role detection
# ---------------------------------------------------------------------------


class TestRepoRole:
    """D7: repo_role motor/no_motor/unknown."""

    def test_detect_motor(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"rm_{uuid.uuid4().hex[:8]}")
        (repo / ".agent" / "agent_controller.py").write_text(
            "# motor", encoding="utf-8"
        )
        from scripts.init_session_scratch import _detect_repo_role

        assert _detect_repo_role(repo) == "motor"

    def test_detect_no_motor(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"rnm_{uuid.uuid4().hex[:8]}")
        from scripts.init_session_scratch import _detect_repo_role

        assert _detect_repo_role(repo) == "no_motor"
