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

from scripts import init_session_scratch as _iss  # noqa: E402
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


def _write_stale_lock(session_dir: Path) -> dict:
    """Write the lock every takeover test starts from: EXPIRED, held by a foreign pid.

    Returned so the caller can assert its own setup: a takeover test that never had a
    stale lock certifies nothing (WOT-2026-021k: a barrier must assert its own fixture).
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stale = {
        "pid": 999999,
        "session_id": "old",
        "op": "init",
        "created_at": now.isoformat(),
        "expires_at": (now - timedelta(seconds=100)).isoformat(),
    }
    (session_dir / "lock.json").write_text(json.dumps(stale), encoding="utf-8")
    return stale


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
# WOT-2026-023w: autonomous-batch anti-loop fields survive the allowlist scrub
# ---------------------------------------------------------------------------


_ANTILOOP_023W = {
    "ticket_id": "WOT-2026-023w",
    "stage": "BUILDER",
    "gate_fallante": "pytest-safe",
    "subtipo_cem": "mock_drift",
    "evidencia": "rc=1 focal red en test_scrub",
    "enfoque_intentado": "parchear el scrub sin ampliar la allowlist",
    "refutacion": "el probe no reproduce la ruta productiva del ledger",
}


class TestBatchRetryAntiLoop023w:
    """The batch anti-loop rule persists each failed attempt so a retry can
    declare a DIFFERENT enfoque. Before this ticket cmd_add scrubbed every
    record to LEDGER_FIELDS and NONE of the 6 anti-loop fields were in it, so
    they were dropped SILENTLY -- the rule would have been unverifiable on the
    first batch run with retries.
    """

    def test_batch_retry_fields_round_trip(self, tmp_path):
        """add(event=batch_retry, <6 anti-loop fields>) -> all persisted INTACT.

        Mutation-to-prove (DoD c): removing the fields from LEDGER_FIELDS makes
        the scrub drop them again and this exact assertion goes red.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"br_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(repo, sid, event="batch_retry", **_ANTILOOP_023W)
        assert result.returncode == 0, f"add failed: {result.stdout}"

        manifest = repo / ".agent" / "runtime" / "session" / sid / "manifest.jsonl"
        records = [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 1
        rec = records[0]
        assert rec["event"] == "batch_retry"
        # Every anti-loop field must round-trip with its exact value.
        for key, value in _ANTILOOP_023W.items():
            assert rec.get(key) == value, (
                f"anti-loop field {key!r} lost/altered in the scrub:"
                f" got {rec.get(key)!r}, expected {value!r}"
            )

        # And the audit must accept the record (batch_retry is a known event).
        session_dir = repo / ".agent" / "runtime" / "session" / sid
        audit = _audit_session(session_dir, sid)
        assert audit["valid"] is True, audit["findings"]

    def test_batch_retry_requires_enfoque_intentado(self, tmp_path):
        """enfoque_intentado is the anti-loop discriminator -> required."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"bre_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(
            repo, sid, event="batch_retry", ticket_id="WOT-2026-023w", stage="BUILDER"
        )
        assert result.returncode == 2, (
            f"batch_retry without enfoque_intentado should exit 2: {result.stdout}"
        )
        assert "enfoque_intentado" in json.loads(result.stdout)["reason"]


# ---------------------------------------------------------------------------
# WOT-2026-026d: process-audit reference events
# ---------------------------------------------------------------------------


_PROCESS_AUDIT_EVENTS_026D = (
    "prompt_designed",
    "tool_used",
    "ensemble_ref",
    "backlog_triage_decision",
)


class TestProcessAuditRefEvents026d:
    """The close audit (Bloque 2.5) crosses prompts-designed / tools-used /
    ensemble rounds / triage decisions against the scorecard. Each is a
    REFERENCE event carrying a `reference` pointer (hash/path/id), never a copy
    (the scorecard owns the per-round verdict -- one datum, one writer). Before
    this ticket these events did not exist; the scrub to LEDGER_FIELDS would
    have dropped `reference` and cmd_add would have rejected the event as
    unknown.
    """

    def test_reference_event_round_trips(self, tmp_path):
        """add(event=<ref event>, generator, reference) -> reference persisted INTACT.

        Mutation-to-prove: removing `reference` from LEDGER_FIELDS makes the
        scrub drop it and this exact assertion goes red; removing the event from
        EVENTS makes cmd_add reject it as unknown (returncode 2).
        """
        for event in _PROCESS_AUDIT_EVENTS_026D:
            repo = _make_repo(REAL_SYSTEM_TEMP, f"pa_{uuid.uuid4().hex[:8]}")
            sid = _sentinel_id()
            _init_session(repo, sid)

            ref = f"sha256:deadbeef/{event}"
            result = _add_record(
                repo, sid, event=event, generator="orchestrator", reference=ref
            )
            assert result.returncode == 0, f"{event} add failed: {result.stdout}"

            manifest = repo / ".agent" / "runtime" / "session" / sid / "manifest.jsonl"
            records = [
                json.loads(line)
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert len(records) == 1
            rec = records[0]
            assert rec["event"] == event
            assert rec.get("reference") == ref, (
                f"{event}: reference lost/altered in the scrub: got "
                f"{rec.get('reference')!r}, expected {ref!r}"
            )
            # The audit must accept the record (it is a known event with its
            # required fields present).
            session_dir = repo / ".agent" / "runtime" / "session" / sid
            audit = _audit_session(session_dir, sid)
            assert audit["valid"] is True, f"{event}: {audit['findings']}"

    def test_reference_event_requires_reference(self, tmp_path):
        """`reference` is the pointer that keeps the event from being an empty
        marker -> required for every process-audit event."""
        for event in _PROCESS_AUDIT_EVENTS_026D:
            repo = _make_repo(REAL_SYSTEM_TEMP, f"par_{uuid.uuid4().hex[:8]}")
            sid = _sentinel_id()
            _init_session(repo, sid)

            result = _add_record(repo, sid, event=event, generator="orchestrator")
            assert result.returncode == 2, (
                f"{event} without reference should exit 2: {result.stdout}"
            )
            reason = json.loads(result.stdout)["reason"]
            assert "reference" in reason, f"{event}: unexpected reason {reason!r}"

    def test_reference_event_requires_generator(self, tmp_path):
        """`generator` names WHO produced the referenced artifact -> required."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"pag_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)

        result = _add_record(repo, sid, event="prompt_designed", reference="sha256:abc")
        assert result.returncode == 2, (
            f"prompt_designed without generator should exit 2: {result.stdout}"
        )
        assert "generator" in json.loads(result.stdout)["reason"]

    def test_reference_event_does_not_trigger_completeness_invariant(self, tmp_path):
        """A lone reference event must NOT trip the 022e added-vs-decided check.

        The cross-record completeness invariant is scoped to
        artifact_added/artifact_decision by artifact_path; a process-audit event
        carries no artifact_path, so a session with only reference events is
        vacuously complete and archivable.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"pac_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        for event in _PROCESS_AUDIT_EVENTS_026D:
            r = _add_record(
                repo, sid, event=event, generator="orchestrator", reference="ref:x"
            )
            assert r.returncode == 0, f"{event}: {r.stdout}"

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        audit = _audit_session(session_dir, sid)
        assert audit["valid"] is True, audit["findings"]
        # No "missing artifact_decision" finding: there was no artifact_added.
        assert not any(
            "missing artifact_decision" in f.get("error", "") for f in audit["findings"]
        ), audit["findings"]


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
        # WOT-2026-032a: this barrier was degraded by 022e. 022e made
        # artifact_path a REQUIRED field for artifact_decision too, so a record
        # that omits BOTH `decision` and `artifact_path` is invalid for TWO
        # reasons -- and asserting only `valid is False` no longer isolates
        # "decision is required": the artifact_path finding alone would satisfy
        # it. Restore specificity by (a) supplying a valid artifact_path so the
        # ONLY remaining defect is the missing decision, and (b) asserting the
        # SPECIFIC decision finding is present while the artifact_path finding
        # is absent. Mutation: removing `decision` from REQUIRED_BY_EVENT makes
        # the record fully valid -> this test goes red on the specific finding.
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
                # Present + non-empty so 022e's artifact_path requirement is
                # satisfied and does NOT contribute a finding: the record's
                # ONLY defect is the missing `decision`.
                "artifact_path": "reports/decided.md",
            },
        )

        result = _audit_session(session_dir, sid)
        assert result["valid"] is False, (
            "artifact_decision without decision should be invalid"
        )
        errors = [f.get("error", "") for f in result["findings"]]
        decision_finding = (
            "missing required field for event=artifact_decision: decision"
        )
        assert decision_finding in errors, (
            "the test must fail on the SPECIFIC missing-decision finding, not "
            f"merely on `valid is False`; findings were: {result['findings']}"
        )
        # Isolation: artifact_path was supplied, so it must NOT be flagged --
        # proving the missing `decision` is the sole reason this record fails.
        assert not any("artifact_decision: artifact_path" in e for e in errors), (
            "artifact_path was supplied and must not be a finding: the barrier "
            f"must isolate the missing decision. findings were: {result['findings']}"
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
        # WOT-2026-022e: the completeness invariant requires a matching
        # artifact_decision for every artifact_added, or this session would be
        # INCOMPLETE -- not the "valid" case this test is about.
        _add_record(
            repo,
            sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )

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
        # WOT-2026-022e: completeness invariant -- archive needs a decision
        # for every artifact_added, or it refuses (see
        # TestArtifactCompletenessInvariant for the refusal path itself).
        _add_record(
            repo,
            sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )

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
        # WOT-2026-022e: cmd_archive audits BEFORE checking --dry-run, so an
        # incomplete session (added without its decision) would stop here too.
        _add_record(
            repo,
            sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )

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
# WOT-2026-022e: cross-record completeness invariant (added-vs-decided)
# ---------------------------------------------------------------------------


class TestArtifactCompletenessInvariant:
    """An artifact_added with no matching artifact_decision (same
    artifact_path) makes the session audit INCOMPLETE -> archive refuses
    (fail-safe, session left intact for debugging). Since gc only ever
    touches ARCHIVED sessions, an incomplete session can never reach it, so
    an artifact without a recorded decision is never silently lost.
    """

    def test_missing_decision_blocks_archive(self, tmp_path):
        """One artifact_added (file.txt), no artifact_decision.

        _audit_session must report EXACTLY the completeness finding -- and
        NOT a generic "missing required field" finding, which would mean
        archive stopped for the WRONG reason (the floor this assertion rules
        out, per the CF-audit Q4 amendment). archive itself must then refuse,
        leaving the session directory untouched.

        Mutation-to-prove (DoD d): removing the completeness check from
        _audit_session makes this go green-to-red the other way -- the
        findings assertion fails first (empty findings), and if that check
        were removed too, archive would exit 0 instead of 1.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"mdba_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        audit = _audit_session(session_dir, sid)
        errors = [f["error"] for f in audit["findings"]]
        assert errors == ["missing artifact_decision for artifact_path: file.txt"], (
            f"expected EXACTLY the completeness finding, got: {errors}"
        )
        assert not any("missing required field" in e for e in errors), (
            "a required-field finding would mean archive stops for the WRONG "
            f"reason (the floor this test rules out): {errors}"
        )
        assert audit["valid"] is False

        archive_dest = repo / ".agent" / "runtime" / "session" / "_archive" / sid
        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid]
        )
        assert result.returncode == 1, (
            f"archive should refuse an incomplete session: {result.stdout}"
        )
        output = json.loads(result.stdout)
        assert output["status"] == "stop"
        assert output["session_intact"] is True
        assert session_dir.is_dir(), "session must survive the refused archive"
        assert not archive_dest.exists(), "nothing should have been archived"

    def test_matching_decision_unblocks_archive(self, tmp_path):
        """Same shape as above, PLUS the artifact_decision for file.txt ->
        the session is COMPLETE (set-by-path, not multiset) and archive
        succeeds.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"mdua_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")
        _add_record(
            repo,
            sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )

        session_dir = repo / ".agent" / "runtime" / "session" / sid
        audit = _audit_session(session_dir, sid)
        assert audit["valid"] is True, audit["findings"]

        result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", sid]
        )
        assert result.returncode == 0, f"archive should succeed: {result.stdout}"
        output = json.loads(result.stdout)
        assert output["status"] == "ok"


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

    def test_takeover_competition_exactly_one_wins(self, tmp_path, monkeypatch):
        """Two contenders race to reclaim ONE stale lock. They are DIFFERENT sessions.

        The contenders must NOT share a session_id. Ownership is (pid, session_id)
        (WOT-2026-023n), so two threads of one process sharing a sid are the SAME
        logical owner: the second re-enters idempotently and `wins == 2` is CORRECT.
        This test used to give both threads the same sid and assert `wins == 1` -- it
        called a legitimate re-entry a bug and went red on roughly 3 of 4 loaded runs
        (WOT-2026-023r). With distinct sids that mode is gone BY CONSTRUCTION:
        _acquire_lock returns `holder == sid`, False for a foreign session, so the
        re-entry branch can never hand out a second win.

        A residual `got 2` here is NOT this test lying again: it is the TOCTOU in
        _takeover_lock (WOT-2026-023s) -- a contender whose "stale" verdict went stale
        unlinks a LIVE lock and takes it. `creates` tells the two apart, which is why
        the assert reports it:
            creates == 2 -> the second contender rewrote the lock -> 023s, a REAL bug
            creates == 1 -> a same-session re-entry -> this test lost its distinct sids
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tc_{uuid.uuid4().hex[:8]}")
        sid_a = _sentinel_id()
        sid_b = _sentinel_id()
        assert sid_a != sid_b, "the contenders must be DIFFERENT sessions"

        session_dir = repo / ".agent" / "runtime" / "session" / "contended"
        _write_stale_lock(session_dir)

        # Assert the setup: the race only means anything over a lock that is genuinely
        # reclaimable -- EXPIRED and owned by someone ELSE.
        stale = _read_lock(session_dir / "lock.json")
        assert stale["pid"] != os.getpid(), "the stale lock must be a FOREIGN pid"
        assert not _lock_is_live(stale), "the stale lock must be EXPIRED"

        creates: list[str] = []
        real_create = _iss._try_create_lock_exclusive

        def counting_create(target: Path, sid: str, op: str) -> bool:
            won = real_create(target, sid, op)
            if won:
                creates.append(sid)  # list.append is atomic under the GIL
            return won

        # Patch the MODULE attribute: _takeover_lock resolves it as a global.
        monkeypatch.setattr(_iss, "_try_create_lock_exclusive", counting_create)

        results: list[bool] = []

        def try_acquire(sid: str):
            results.append(_acquire_lock(session_dir, sid, "init"))

        import threading

        threads = [
            threading.Thread(target=try_acquire, args=(sid,)) for sid in (sid_a, sid_b)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wins = sum(1 for r in results if r is True)
        assert wins == 1, (
            f"Exactly 1 should win, got {wins} (creates={len(creates)}). "
            "wins==2, creates==2 -> WOT-2026-023s: the loser's stale reclaim verdict "
            "unlinked a LIVE lock (TOCTOU in _takeover_lock) -- a REAL production bug, "
            "NOT a regression of this test. "
            "wins==2, creates==1 -> a same-session idempotent re-entry, meaning this "
            "test lost its distinct-sid setup. "
            "wins==0 -> WOT-2026-023l: NOBODY acquired (the `got 0` flaky, mechanism "
            "still undetermined) -- a different bug, do not attribute it to either."
        )

    def test_interruption_leaves_session_intact(self, tmp_path):
        repo = _make_repo(REAL_SYSTEM_TEMP, f"int_{uuid.uuid4().hex[:8]}")
        sid = _sentinel_id()
        _init_session(repo, sid)
        _add_record(repo, sid, generator="test", artifact_path="file.txt")
        # WOT-2026-022e: this test asserts audit-only leaves the session
        # intact, not the completeness invariant -- give it a matching
        # decision so the audit is VALID (0/0) rather than incomplete.
        _add_record(
            repo,
            sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )

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
# Lock ownership: (pid, session_id), not pid alone (WOT-2026-023l)
# ---------------------------------------------------------------------------


class TestLockOwnershipIsIdentityAware:
    """A live lock is owned by (pid, session_id) -- the same pair _release_lock
    demands. Acquisition used to check only the pid, so a live lock written by THIS
    process for a DIFFERENT session got stolen: the `pid != os.getpid()` guard was
    False, execution fell through to _takeover_lock, which unlinks and recreates the
    lock (O_EXCL cannot protect a path that was just unlinked). The thief then held a
    lock it could never release. Two SEQUENTIAL acquisitions both returned True --
    which is what surfaced as `Exactly 1 should win, got 2` under xdist load.

    These tests are deterministic: no threads, no timing, no flakiness. The old
    takeover test (2 threads on an EXPIRED lock) passes with or without the fix, so
    it cannot guard this behaviour.
    """

    @staticmethod
    def _live_lock(session_dir: Path, holder_sid: str, pid: int) -> bytes:
        """Write a LIVE lock owned by (pid, holder_sid). Returns its exact bytes."""
        session_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        payload = json.dumps(
            {
                "pid": pid,
                "session_id": holder_sid,
                "op": "init",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=300)).isoformat(),
            }
        )
        lock_path = session_dir / "lock.json"
        lock_path.write_text(payload, encoding="utf-8")
        return lock_path.read_bytes()

    def test_same_process_other_session_cannot_steal_a_live_lock(self) -> None:
        """THE BUG. Same pid, DIFFERENT session_id, live lock -> must NOT acquire,
        and the lock must survive byte-for-byte.

        Mutation-to-prove: drop the identity check in _acquire_lock and this goes red
        -- the caller acquires (True) and the lock becomes theirs.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"own_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        before = self._live_lock(session_dir, holder_sid="A", pid=os.getpid())

        acquired = _acquire_lock(session_dir, "B", "init")

        assert acquired is False, "session B stole a live lock held by session A"
        assert (session_dir / "lock.json").read_bytes() == before, (
            "the lock was rewritten: B unlinked A's lock and recreated it"
        )

    def test_same_process_same_session_resume_is_idempotent(self) -> None:
        """The legitimate resume path: same pid, SAME session_id -> acquires, and
        leaves the lock untouched. It used to go through the takeover and rewrite the
        lock for no reason."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"res_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        before = self._live_lock(session_dir, holder_sid="A", pid=os.getpid())

        acquired = _acquire_lock(session_dir, "A", "init")

        assert acquired is True
        assert (session_dir / "lock.json").read_bytes() == before, (
            "an idempotent re-acquire must not rewrite the lock"
        )

    def test_live_lock_of_a_living_foreign_process_still_blocks(self) -> None:
        """Unchanged by the fix: pid 4 (System on Windows) is alive and foreign."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"fgn_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        self._live_lock(session_dir, holder_sid="X", pid=4)

        assert _acquire_lock(session_dir, "B", "init") is False

    def test_expired_lock_of_a_dead_pid_is_still_reclaimed(self) -> None:
        """Unchanged by the fix: the legitimate takeover must keep working, or the
        identity check would have turned a fix into a deadlock."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"stl_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        session_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        (session_dir / "lock.json").write_text(
            json.dumps(
                {
                    "pid": 999999,
                    "session_id": "old",
                    "op": "init",
                    "created_at": now.isoformat(),
                    "expires_at": (now - timedelta(seconds=100)).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        assert _acquire_lock(session_dir, "B", "init") is True


# ---------------------------------------------------------------------------
# Ownership of a lock produced by a REAL takeover (WOT-2026-023r)
# ---------------------------------------------------------------------------


class TestTakeoverProducedLockOwnership:
    """Ownership holds on a lock written by _takeover_lock, not just a hand-written one.

    TestLockOwnershipIsIdentityAware pins the same two verdicts, but it hand-writes the
    live lock. Nothing pinned the route that actually produced the `got 2`: thread A
    RECLAIMS the stale lock, and the lock B then reads is the one A's takeover wrote.
    These two tests walk that route, deterministically -- no threads, no timing.

    Both are barriers: reverting the identity check in _acquire_lock (pid-only
    ownership, the pre-023n code) makes BOTH go red. Verify them in ISOLATION -- the
    same mutation also kills the two tests above, so "the mutant died" proves nothing
    about these (the mutation-verify false-green of WOT-2026-021t/021u).
    """

    @staticmethod
    def _reclaimed_by(session_dir: Path, sid: str) -> None:
        """Drive a REAL takeover, then assert the lock is genuinely the takeover's.

        The PRE assert is what makes these tests about the takeover at all. Without a
        foreign, EXPIRED lock to reclaim, _acquire_lock takes the `not lock_path.exists()`
        branch and creates the lock outright -- _takeover_lock never runs, and the POST
        state (ours, live, our sid) is satisfied ALL THE SAME. Both tests then pass green
        while certifying a route they never walked, which is exactly what they exist to
        cover. Measured: with the fixture sabotaged to write no lock, both went green.
        """
        pre = _read_lock(session_dir / "lock.json")
        assert pre is not None, (
            "no lock to reclaim: the takeover route is not exercised"
        )
        assert pre["pid"] != os.getpid(), "the lock to reclaim must be a FOREIGN pid"
        assert not _lock_is_live(pre), "the lock to reclaim must be EXPIRED"

        assert _acquire_lock(session_dir, sid, "init") is True, (
            "the stale lock must be reclaimable, or this fixture proves nothing"
        )
        lock = _read_lock(session_dir / "lock.json")
        assert lock is not None
        assert lock["pid"] == os.getpid(), "the reclaimed lock must be OURS"
        assert lock["session_id"] == sid, "the reclaimed lock must name the reclaimer"
        assert _lock_is_live(lock), "the reclaimed lock must be LIVE"

    def test_takeover_then_foreign_session_cannot_steal(self) -> None:
        """THE ROUTE OF THE FALSE RED. After A reclaims, a foreign session must NOT
        acquire -- and A's lock must survive byte-for-byte.

        Mutation-to-prove: drop the identity check in _acquire_lock and the second
        acquisition returns True, taking a lock it could never release.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tpo_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        _write_stale_lock(session_dir)

        self._reclaimed_by(session_dir, "sid-a")
        before = (session_dir / "lock.json").read_bytes()

        acquired = _acquire_lock(session_dir, "sid-b", "init")

        assert acquired is False, "a foreign session stole a freshly reclaimed lock"
        assert (session_dir / "lock.json").read_bytes() == before, (
            "the reclaimed lock was rewritten: sid-b unlinked it and recreated it"
        )

    def test_toctuo_stale_read_cannot_steal_a_reclaimed_lock(self) -> None:
        """WOT-2026-023s. THE TOCTOU. Contender B reads the lock, decides "stale", is
        descheduled; contender A completes its takeover and now owns a LIVE lock; B
        wakes with its stale verdict already made and enters _takeover_lock directly. It
        must NOT steal A's live lock.

        Serialized deterministically -- no threads. Measured: with real threads this
        interleaving surfaces ~1% of the time (198/200 gave wins=1 even WITHOUT the
        fix), so a threaded test would pass on the broken code and the mutation would
        have no teeth. Serializing is the only way this barrier bites.

        Mutation-to-prove: drop the revalidation (unlink blindly) and B's takeover
        returns True, taking a lock A can never release.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"toc_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        _write_stale_lock(session_dir)

        # A reclaims the stale lock legitimately -> A now owns a LIVE lock.
        self._reclaimed_by(session_dir, "sid-a")
        a_lock = (session_dir / "lock.json").read_bytes()

        # B already decided "stale" before A ran; it enters the takeover directly with a
        # FOREIGN session id. The revalidation must see the lock is now live+foreign.
        stolen = _iss._takeover_lock(session_dir, "sid-b", "init")

        assert stolen is False, (
            "B's stale-read takeover stole A's freshly reclaimed lock"
        )
        assert (session_dir / "lock.json").read_bytes() == a_lock, (
            "A's live lock was unlinked and rewritten by B (the TOCTOU)"
        )
        assert _release_lock(session_dir, "sid-a") is True, (
            "A cannot release its own lock -> false ownership: the TOCTOU is not fixed"
        )

    def test_toctuo_stale_read_same_session_reentry_is_idempotent(self) -> None:
        """WOT-2026-023s companion: the SAME contender re-entering its own reclaimed
        lock via the takeover path is idempotent -> True, lock untouched. Guards against
        a fix that returns False for the legitimate re-entry too."""
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tor_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        _write_stale_lock(session_dir)

        self._reclaimed_by(session_dir, "sid-a")
        before = (session_dir / "lock.json").read_bytes()

        again = _iss._takeover_lock(session_dir, "sid-a", "init")

        assert again is True, "the owner cannot re-enter its own lock via the takeover"
        assert (session_dir / "lock.json").read_bytes() == before, (
            "an idempotent re-entry through the takeover must not rewrite the lock"
        )

    def test_toctuo_stale_read_cannot_steal_a_live_foreign_process_lock(
        self, monkeypatch
    ) -> None:
        """WOT-2026-023s, the CROSS-PROCESS half. The other two takeover tests run in one
        process, so the reclaimed lock always carries os.getpid() and B's revalidation
        takes the `cur_pid == os.getpid()` branch. The branch that actually fires when
        the racing owner is a DIFFERENT process -- live pid, foreign -- was untested:
        deleting it left the whole suite green (found by the Review 2 mutation of that
        single branch). This test forces a lock owned by a foreign pid.

        A real foreign-yet-alive pid is not deterministic, so _is_pid_alive_best_effort
        is pinned True for the foreign pid -- exactly the ambiguity the guard resolves in
        favour of "alive -> do not steal".

        Mutation-to-prove: neutralise the `_is_pid_alive_best_effort(cur_pid) -> False`
        branch in _revalidate_before_unlink and this goes red (B reclaims a live foreign
        lock); the in-process tests stay green, so only THIS test guards that branch.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tfp_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        session_dir.mkdir(parents=True, exist_ok=True)

        # A LIVE lock owned by another process (pid 4242, not ours). This is the state B
        # sees when it revalidates after a foreign process reclaimed the lock.
        now = datetime.now(timezone.utc)
        foreign = {
            "pid": 4242,
            "session_id": "sid-a",
            "op": "init",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=300)).isoformat(),
        }
        (session_dir / "lock.json").write_text(json.dumps(foreign), encoding="utf-8")
        before = (session_dir / "lock.json").read_bytes()

        # Setup assertion: the lock really is live and NOT ours (or this proves nothing).
        assert foreign["pid"] != os.getpid()
        assert _lock_is_live(foreign)

        # The foreign pid is alive -> the guard must refuse to steal.
        monkeypatch.setattr(_iss, "_is_pid_alive_best_effort", lambda pid: pid == 4242)

        stolen = _iss._takeover_lock(session_dir, "sid-b", "init")

        assert stolen is False, "B stole a live lock held by a foreign PROCESS"
        assert (session_dir / "lock.json").read_bytes() == before, (
            "the foreign process's live lock was unlinked and rewritten"
        )

    def test_takeover_then_same_session_reentry_is_idempotent(
        self, monkeypatch
    ) -> None:
        """The legitimate `wins == 2`. After A reclaims, A re-acquiring is idempotent:
        True, and the lock is left untouched.

        This is the behaviour the old threaded test called a bug: two threads sharing a
        sid are ONE logical owner, so the second acquisition is a resume, not a theft.
        Pinned here deterministically so nobody "fixes" it back into a race.

        Mutation-to-prove: without the identity check the re-entry falls through to the
        takeover, which unlinks and REWRITES the lock. The discriminant is that
        _takeover_lock RAN, not that the bytes changed: the two writes differ only in
        their timestamps, so on a machine with a coarse clock both could land in the same
        tick and produce a byte-identical lock -- the byte assert alone would then pass
        against the mutant. The call counter does not depend on clock resolution.
        """
        repo = _make_repo(REAL_SYSTEM_TEMP, f"tpr_{uuid.uuid4().hex[:8]}")
        session_dir = repo / ".agent" / "runtime" / "session" / "s"
        _write_stale_lock(session_dir)

        self._reclaimed_by(session_dir, "sid-a")
        before = (session_dir / "lock.json").read_bytes()

        takeovers: list[str] = []
        real_takeover = _iss._takeover_lock

        def counting_takeover(target: Path, sid: str, op: str) -> bool:
            takeovers.append(sid)
            return real_takeover(target, sid, op)

        # Patch the MODULE attribute: _acquire_lock resolves it as a global.
        monkeypatch.setattr(_iss, "_takeover_lock", counting_takeover)

        acquired = _acquire_lock(session_dir, "sid-a", "init")

        assert acquired is True, "the owner cannot re-enter its own session"
        assert takeovers == [], (
            "the re-entry went through the TAKEOVER instead of the identity branch: it "
            "unlinked and recreated a lock it already held"
        )
        assert (session_dir / "lock.json").read_bytes() == before, (
            "an idempotent re-acquire must not rewrite the lock"
        )


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
        # WOT-2026-022e: without its decision the session is INCOMPLETE, so
        # archive would refuse and the session would never leave the active
        # listing -- give it a matching decision so archive actually succeeds
        # (this test is about list/_archive, not about the refusal path).
        _add_record(
            repo,
            archived_sid,
            event="artifact_decision",
            generator="test",
            artifact_path="file.txt",
            decision="kept",
        )
        archive_result = _run_scratch(
            ["--project-root", str(repo), "archive", "--session-id", archived_sid]
        )
        assert archive_result.returncode == 0, (
            f"archive setup for this test must succeed: {archive_result.stdout}"
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
