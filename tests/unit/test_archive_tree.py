"""Contract tests for the versioned clone archiver.

Before: the archive tool is absent or incomplete.
During: tests exercise the public CLI and independent round-trip checks.
After: the test file documents the fail-closed archive contract.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts.flight import archive_tree, p7_common


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "archive_tree.py"


def _run(*args: str, home: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Before: CLI arguments target only a temporary fixture.
    During: run the script with optional isolated user-home variables.
    After: return captured process evidence without changing the real environment.
    """
    environment = os.environ.copy()
    if home is not None:
        environment["USERPROFILE"] = str(home)
        environment["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


_MESSAGES_DDL_189A = """
CREATE TABLE orchestration_v2_projection_messages (
 message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT, node_id TEXT,
 role TEXT NOT NULL, streaming INTEGER NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
"""
_THREADS_DDL_189A = """
CREATE TABLE orchestration_v2_projection_threads (
 thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
 default_provider TEXT NOT NULL, runtime_mode TEXT NOT NULL,
 interaction_mode TEXT NOT NULL, active_provider_thread_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 deleted_at TEXT, payload_json TEXT NOT NULL, provider_instance_id TEXT);
"""


def _seed_retire_auth(
    tmp_path: Path,
    home: Path,
    *,
    text: str | None = None,
    created_at: str | None = None,
    archive_root: Path | None = None,
) -> tuple[str, str]:
    """Before: archive index contains one ARCHIVADO family.
    During: create the isolated state store with one valid user anchor.
    After: return the thread and message identifiers used by retire subprocesses.
    """
    archive_dir = archive_root if archive_root is not None else tmp_path / "archive"
    row = next(
        item
        for item in reversed(p7_common.load_jsonl_index(archive_dir / "index.jsonl"))
        if item.get("status") == "ARCHIVADO"
    )
    thread_id = "11111111-1111-4111-8111-111111111111"
    message_id = "22222222-2222-4222-8222-222222222222"
    expected = f"RETIRAR {row['family']} {str(row['list_sha256'])[:12].lower()} {len(row['clones'])}"
    text = expected if text is None else text
    created_at = "2026-11-20T12:00:00.000Z" if created_at is None else created_at
    store = home / ".t3" / "userdata" / "statev2.sqlite"
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(store)
    connection.executescript(_MESSAGES_DDL_189A + _THREADS_DDL_189A)
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            thread_id,
            "p",
            "t",
            "provider",
            "mode",
            "mode",
            None,
            created_at,
            created_at,
            None,
            None,
            "{}",
            None,
        ),
    )
    payload = json.dumps({"createdBy": "user", "creationSource": "web", "text": text})
    connection.execute(
        "INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?,?,?,?)",
        (
            message_id,
            thread_id,
            "run",
            "node",
            "user",
            0,
            created_at,
            created_at,
            payload,
        ),
    )
    connection.commit()
    connection.close()
    return thread_id, message_id


def _archive_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """Before: a fresh clone fixture is available.
    During: publish its archive-only evidence in the temporary archive root.
    After: return the roots, approval file, and list digest for retire tests.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    return origin, archive, approved, list_hash


def _retire_args(
    origin: Path,
    archive: Path,
    approved: Path,
    list_hash: str,
    thread: str,
    message: str,
) -> tuple[str, ...]:
    """Before: retire fixture paths and an authorization identity are known.
    During: construct the complete explicit retire argument vector.
    After: return immutable subprocess arguments without executing them.
    """
    return (
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-retire",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
        "--thread-id",
        thread,
        "--message-id",
        message,
    )


def test_189a_apply_is_disabled(tmp_path: Path) -> None:
    """Before: legacy apply is requested.
    During: invoke both its valid and incomplete forms.
    After: both fail before touching either tree.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    digest = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    for extra in (("--list", str(approved), "--list-sha256", digest), ()):
        result = _run(
            "--origin", str(origin), "--archive-root", str(archive), "--apply", *extra
        )
        assert result.returncode == 2
        assert (
            "ERROR: --apply is disabled; use --apply-archive or --apply-retire"
            in result.stderr
        )
    assert archive_tree.tree_hash(origin) == before
    assert not (archive / "index.jsonl").exists()


def test_189a_recover_is_disabled(tmp_path: Path) -> None:
    """Before: archive evidence and recovery state exist.
    During: request the retired recovery command.
    After: the command is rejected without changing the recovery bytes.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    ledger = _write_recovery_ledger(
        archive, origin, row, json.loads(Path(row["manifest"]).read_text())
    )
    before = ledger.read_bytes()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--recover-retirement",
        "--list",
        str(approved),
        "--list-sha256",
        digest,
    )
    assert result.returncode == 2
    assert "ERROR: --recover-retirement is disabled" in result.stderr
    assert ledger.read_bytes() == before
    assert origin.exists()
    assert not (archive / ".p7.lock").exists()


def test_189a_resume_is_forbidden_for_retire(tmp_path: Path) -> None:
    """Before: a valid retire authorization is available.
    During: combine resume with retire.
    After: usage rejection precedes store access and deletion.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message),
        "--resume",
        home=tmp_path,
    )
    assert result.returncode == 2
    assert "ERROR: --resume cannot be used with --apply-retire" in result.stderr
    assert (
        origin.exists()
        and len(p7_common.load_jsonl_index(archive / "index.jsonl")) == 1
    )


def test_189a_exact_phrase_and_replay(tmp_path: Path) -> None:
    """Before: the archive has one exact user authorization.
    During: reject near phrases, consume the exact phrase, then replay it.
    After: only one ledger transition and one RETIRADO row exist.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    exact = f"RETIRAR {row['family']} {digest[:12].lower()} 1"
    ledger_path = archive / "chain_authority_ledger.jsonl"
    seeded = {"messageId": message, "step": 2, "outCode": "X", "inCode": "Y"}
    ledger_path.write_text(json.dumps(seeded) + "\n", encoding="utf-8")
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 1 and "ERROR: retire-consumed" in result.stderr
    assert ledger_path.read_text(encoding="utf-8").splitlines() == [json.dumps(seeded)]
    assert origin.exists()
    assert len(p7_common.load_jsonl_index(archive / "index.jsonl")) == 1
    ledger_path.write_text("", encoding="utf-8")
    ledger_path.unlink()
    db = tmp_path / ".t3" / "userdata" / "statev2.sqlite"
    variants = (
        "wrong",
        f"{exact} 2",
        f"{exact[:-1]}0",
        f"{row['family']}X {digest[:12].lower()} 1",
        f"{exact} por favor",
    )
    for text in variants:
        connection = sqlite3.connect(db)
        connection.execute(
            "UPDATE orchestration_v2_projection_messages SET payload_json=?",
            (json.dumps({"createdBy": "user", "creationSource": "web", "text": text}),),
        )
        connection.commit()
        connection.close()
        result = _run(
            *_retire_args(origin, archive, approved, digest, thread, message),
            home=tmp_path,
        )
        assert result.returncode == 1 and "ERROR: text-mismatch" in result.stderr
        assert not ledger_path.exists()
        assert origin.exists()
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET payload_json=?",
        (json.dumps({"createdBy": "user", "creationSource": "web", "text": exact}),),
    )
    connection.commit()
    connection.close()
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 0, result.stderr
    ledger_rows = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["messageId"] == message
    assert ledger_rows[0]["step"] == 1
    assert ledger_rows[0]["outCode"] == "ARCHIVADO"
    assert ledger_rows[0]["inCode"] == "RETIRADO"
    assert [
        row["status"] for row in p7_common.load_jsonl_index(archive / "index.jsonl")
    ] == [
        "ARCHIVADO",
        "RETIRADO",
    ]
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 1 and "ERROR: retire-consumed" in result.stderr
    assert len(ledger_path.read_text().splitlines()) == 1


def test_189a_origin_record_mismatch(tmp_path: Path) -> None:
    """Before: an archived record names origin one.
    During: retire is requested for an identical but different path.
    After: origin mismatch rejects before consumption.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    other = tmp_path / "origin-copy"
    shutil.copytree(origin, other)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    result = _run(
        *_retire_args(other, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 1 and "ERROR: origin-mismatch" in result.stderr
    assert origin.exists() and other.exists()
    if sys.platform == "win32":
        result = _run(
            *(
                _retire_args(
                    Path(str(origin).upper()),
                    archive,
                    approved,
                    digest,
                    thread,
                    message,
                )
            ),
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert not origin.exists()
        assert (
            sum(
                row.get("status") == "RETIRADO"
                for row in p7_common.load_jsonl_index(archive / "index.jsonl")
            )
            == 1
        )


def test_189a_foreign_message(tmp_path: Path) -> None:
    """Before: the message exists in a different live thread.
    During: authorize with a foreign thread id.
    After: thread mismatch rejects without ledger consumption.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    _thread, message = _seed_retire_auth(tmp_path, tmp_path)
    db = tmp_path / ".t3" / "userdata" / "statev2.sqlite"
    connection = sqlite3.connect(db)
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "33333333-3333-4333-8333-333333333333",
            "p",
            "t",
            "provider",
            "mode",
            "mode",
            None,
            "2026-11-20T12:00:00.000Z",
            "2026-11-20T12:00:00.000Z",
            None,
            None,
            "{}",
            None,
        ),
    )
    connection.commit()
    connection.close()
    result = _run(
        *_retire_args(
            origin,
            archive,
            approved,
            digest,
            "33333333-3333-4333-8333-333333333333",
            message,
        ),
        home=tmp_path,
    )
    assert result.returncode == 1 and "ERROR: thread-mismatch" in result.stderr
    assert origin.exists()


def test_189a_missing_thread_has_cause(tmp_path: Path) -> None:
    """Before: the archive exists and the store has one valid anchor.
    During: use a missing thread and then a missing message.
    After: each cause is explicit and origin remains intact.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    result = _run(
        *_retire_args(
            origin,
            archive,
            approved,
            digest,
            "44444444-4444-4444-8444-444444444444",
            message,
        ),
        home=tmp_path,
    )
    assert result.returncode == 1 and "ERROR: anchor-thread-missing" in result.stderr
    result = _run(
        *_retire_args(
            origin,
            archive,
            approved,
            digest,
            thread,
            "55555555-5555-4555-8555-555555555555",
        ),
        home=tmp_path,
    )
    assert result.returncode == 1 and "ERROR: anchor-missing" in result.stderr
    assert origin.exists()


@pytest.mark.parametrize(
    "extra, expected",
    [
        (
            ("--apply", "--apply-retire"),
            "ERROR: --apply cannot be combined with --apply-archive or --apply-retire",
        ),
        (
            ("--apply", "--apply-retire", "--recover-retirement"),
            "ERROR: --apply cannot be combined with --apply-archive or --apply-retire",
        ),
        (
            ("--apply",),
            "ERROR: --apply is disabled; use --apply-archive or --apply-retire",
        ),
        (
            ("--recover-retirement", "--resume", "--apply-retire"),
            "ERROR: --recover-retirement is disabled",
        ),
        (
            ("--resume", "--apply-retire"),
            "ERROR: --resume cannot be used with --apply-retire",
        ),
        (("--apply-retire",), "ERROR: --thread-id es obligatorio"),
        (("--apply-retire", "--thread-id", "T"), "ERROR: --message-id es obligatorio"),
        (
            ("--apply-retire", "--thread-id", "T", "--message-id", "M"),
            "ERROR: --apply requires --list and --list-sha256",
        ),
    ],
)
def test_189a_exact_rc2_texts(
    tmp_path: Path, extra: tuple[str, ...], expected: str
) -> None:
    """Before: each invalid argument combination is isolated.
    During: invoke the CLI with the contract priority matrix.
    After: rc 2 and the exact required diagnostic are observed.
    """
    result = _run(
        "--origin",
        str(tmp_path / "origin"),
        "--archive-root",
        str(tmp_path / "archive"),
        *extra,
    )
    assert result.returncode == 2 and expected in result.stderr


def test_189a_home_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Before: the process home is redirected to a temporary directory.
    During: inspect the path and perform a complete authorized retirement.
    After: no real home store is consulted and the clone is removed.
    """
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        archive_tree._store_path() == tmp_path / ".t3" / "userdata" / "statev2.sqlite"
    )
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 0, result.stderr


def test_189a_publish_after_origin_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: authorization is valid but deletion fails on its first file.
    During: run retire with a destructive primitive that raises.
    After: no RETIRADO row is published and recovery remains IN_PROGRESS.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    monkeypatch.setattr(
        archive_tree,
        "_safe_remove",
        lambda _path: (_ for _ in ()).throw(PermissionError("blocked")),
    )
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    result = archive_tree.main(
        [*(_retire_args(origin, archive, approved, digest, thread, message))]
    )
    assert result == 1
    assert not any(
        r.get("status") == "RETIRADO"
        for r in p7_common.load_jsonl_index(archive / "index.jsonl")
    )
    assert (
        json.loads((archive / "retirement_recovery.json").read_text())["status"]
        == "IN_PROGRESS"
    )
    assert any(origin.rglob("*"))


def test_189a_noncanonical_timestamp(tmp_path: Path) -> None:
    """Before: the user message timestamp lacks canonical milliseconds.
    During: attempt retirement with an otherwise correct phrase.
    After: timestamp-form rejects before consumption.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(
        tmp_path, tmp_path, created_at="2026-11-20T12:00:00Z"
    )
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=tmp_path
    )
    assert result.returncode == 1 and "ERROR: timestamp-form" in result.stderr
    assert origin.exists()


def test_189a_preflight_fail_after_consume(tmp_path: Path) -> None:
    """Before: archive authorization is valid but the clone is readonly.
    During: consume authority, then let preflight reject the origin.
    After: one spent ledger line exists and replay is refused.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    try:
        (origin / "clone-a" / "data.txt").chmod(0o444)
        result = _run(
            *_retire_args(origin, archive, approved, digest, thread, message),
            home=tmp_path,
        )
        assert result.returncode == 1
        assert (archive / "chain_authority_ledger.jsonl").exists()
        assert not (archive / "retirement_recovery.json").exists()
        assert not any(
            row.get("status") == "RETIRADO"
            for row in p7_common.load_jsonl_index(archive / "index.jsonl")
        )
        assert (origin / "clone-a" / "data.txt").exists()
        assert "read-only" in result.stderr.lower()
        replay = _run(
            *_retire_args(origin, archive, approved, digest, thread, message),
            home=tmp_path,
        )
        assert replay.returncode == 1 and "ERROR: retire-consumed" in replay.stderr
    finally:
        (origin / "clone-a" / "data.txt").chmod(0o666)


@pytest.mark.parametrize("kind", ["missing-store", "corrupt-ledger"])
def test_189a_infra_rc1(tmp_path: Path, kind: str) -> None:
    """Before: either the state store or chain ledger is infrastructure-invalid.
    During: invoke retirement through the subprocess boundary.
    After: rc 1 names the infrastructure cause without a traceback.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    home = tmp_path / "isolated-home"
    if kind == "missing-store":
        thread, message = "T", "M"
        expected = "store-missing"
    else:
        thread, message = _seed_retire_auth(tmp_path, home)
        (archive / "chain_authority_ledger.jsonl").write_text(
            "{broken", encoding="utf-8"
        )
        expected = "chain-ledger-corrupt-line"
    result = _run(
        *_retire_args(origin, archive, approved, digest, thread, message), home=home
    )
    assert result.returncode == 1 and f"ERROR: {expected}" in result.stderr
    assert "Traceback" not in result.stderr and origin.exists()


def _restore_manifest_mtimes(manifest: Path, restored: Path) -> None:
    """Before: ``restored`` was extracted without metadata restoration.
    During: restore each file mtime from the independent manifest recipe.
    After: the independent verifier can compare, rather than manufacture, mtimes.
    """
    for row in json.loads(manifest.read_text(encoding="utf-8")):
        if not row.get("dir"):
            path = restored / row["rel"]
            os.utime(path, (float(row["mtime"]), float(row["mtime"])))


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    clone = origin / "clone-a"
    clone.mkdir(parents=True)
    (clone / "empty").mkdir()
    (clone / "data.txt").write_text("payload", encoding="utf-8")
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps([{"rel": "clone-a"}]), encoding="utf-8")
    return origin, archive, approved


def _approved(origin: Path, approved: Path) -> str:
    value = [{"rel": "clone-a", "sha256": archive_tree.tree_hash(origin / "clone-a")}]
    approved.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(approved.read_bytes()).hexdigest()


def test_cli_dry_run_contract(tmp_path: Path) -> None:
    """Before: the new CLI is not present.
    During: invoke the required dry-run boundary.
    After: the origin is unchanged and candidates are reported.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    before_origin = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--list",
        str(approved),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidates"] == ["clone-a"]
    assert archive_tree.tree_hash(origin) == before_origin
    assert archive_tree.tree_hash(archive) == before_archive


def test_apply_requires_and_checks_approval(tmp_path: Path) -> None:
    """Before: approval is absent or stale.
    During: reject both cases before creating archive evidence.
    After: a valid list is the only accepted apply input.
    """
    origin, archive, approved = _fixture(tmp_path)
    result = _run(
        "--origin", str(origin), "--archive-root", str(archive), "--apply-archive"
    )
    assert result.returncode == 2
    list_hash = _approved(origin, approved)
    approved.write_text(
        approved.read_text(encoding="utf-8").replace("clone-a", "clone-b"),
        encoding="utf-8",
    )
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert not archive.exists()


def test_apply_rejects_missing_root_and_entry_hash(tmp_path: Path) -> None:
    """Before: the archive root is absent or an approved tree changed.
    During: fail before lock-dependent filesystem writes.
    After: rc 4 is used for the absent root and rc 1 for a stale entry.
    """
    origin, archive, approved = _fixture(tmp_path)
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 4
    assert not archive.exists()
    archive.mkdir()
    value = json.loads(approved.read_text(encoding="utf-8"))
    value[0]["sha256"] = "0" * 64
    approved.write_text(json.dumps(value), encoding="utf-8")
    bad_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        bad_hash,
    )
    assert result.returncode == 1
    assert list(archive.iterdir()) == []


def test_dry_run_missing_root_is_rc4(tmp_path: Path) -> None:
    """Before: the archive root is absent.
    During: run the safe default without creating a root.
    After: rc 4 and zero filesystem writes are observed.
    """
    origin, archive, _approved_path = _fixture(tmp_path)
    result = _run("--origin", str(origin), "--archive-root", str(archive))
    assert result.returncode == 4
    assert not archive.exists()


def test_archive_and_retire_are_separate_phases(tmp_path: Path) -> None:
    """Before: an approved clone and an existing archive root exist.
    During: archive-only is followed by retire-only against the original origin.
    After: the first phase preserves origin and the second adds one RETIRADO row.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    archive_result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert archive_result.returncode == 0, archive_result.stderr
    assert (origin / "clone-a").exists()
    thread_id, message_id = _seed_retire_auth(tmp_path, tmp_path)
    retire_result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-retire",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
        "--thread-id",
        thread_id,
        "--message-id",
        message_id,
        home=tmp_path,
    )
    assert retire_result.returncode == 0, retire_result.stderr
    assert not (origin / "clone-a").exists()
    assert [
        row["status"] for row in p7_common.load_jsonl_index(archive / "index.jsonl")
    ] == ["ARCHIVADO", "RETIRADO"]


def test_readonly_abort_keeps_origin_intact(tmp_path: Path) -> None:
    """Before: a selected file is readonly.
    During: combined apply performs preflight before staging.
    After: rc 1 leaves the origin hash and clone path unchanged.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    archive_result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert archive_result.returncode == 0, archive_result.stderr
    thread_id, message_id = _seed_retire_auth(tmp_path, tmp_path)
    file_path = origin / "clone-a" / "data.txt"
    file_path.chmod(0o444)
    before = archive_tree.tree_hash(origin)
    try:
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-retire",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
            "--thread-id",
            thread_id,
            "--message-id",
            message_id,
            home=tmp_path,
        )
        assert result.returncode == 1
        assert (origin / "clone-a").exists()
        assert archive_tree.tree_hash(origin) == before
        assert not any(path.name.startswith(".p7_") for path in origin.parent.iterdir())
    finally:
        file_path.chmod(0o666)


def test_stage_requires_resume_and_resume_returns_clone(tmp_path: Path) -> None:
    """Before: a staged clone remains after an interrupted operation.
    During: reject without resume, then archive with resume and return the clone.
    After: no stage orphan or temporary file remains.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    stage = origin.parent / (".p7_" + "stage_" + "clone_archive")
    stage.mkdir()
    shutil.move(str(origin / "clone-a"), str(stage / "clone-a"))
    rejected = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert rejected.returncode == 1
    resumed = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--resume",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert (origin / "clone-a").exists()
    assert not stage.exists()
    assert not list(archive.rglob("*.tmp"))


@pytest.mark.parametrize("size,expected", [(6, 0), (7, 0), (8, 1)])
def test_max_bytes_boundaries(tmp_path: Path, size: int, expected: int) -> None:
    """Before: a selected clone is exactly below, equal to, or above the limit.
    During: evaluate the byte budget before staging or archive writes.
    After: only the one-byte-over case fails with no archive artifacts.
    """
    origin, archive, approved = _fixture(tmp_path)
    (origin / "clone-a" / "data.txt").write_bytes(b"x" * size)
    list_hash = _approved(origin, approved)
    archive.mkdir()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--max-bytes",
        "7",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == expected
    if expected:
        assert list(archive.iterdir()) == []


def test_apply_round_trip_and_p7_index(tmp_path: Path) -> None:
    """Before: a real clone-shaped tree and an approved hash exist.
    During: archive and retire the same batch.
    After: zip, manifest, ARCHIVADO, RETIRADO, and P7 reconciliation agree.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    result = _run(
        *(_retire_args(origin, archive, approved, list_hash, thread, message)),
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert [row["status"] for row in rows] == ["ARCHIVADO", "RETIRADO"]
    archived = rows[0]
    manifest = json.loads(Path(archived["manifest"]).read_text(encoding="utf-8"))
    with __import__("zipfile").ZipFile(archived["zip"]) as zipped:
        assert set(zipped.namelist()) == {
            row["rel"] for row in manifest if not row.get("dir")
        }
    assert not (origin / "clone-a").exists()
    assert p7_common.reconcile_index(archive, rows, archived["family"]) == []


def _independent_verify(
    zip_path: Path, manifest_path: Path, restored: Path
) -> list[str]:
    """Before: a zip, manifest, and restored directory are independent inputs.
    During: compare mtime, size, digest, extra files, and empty directories.
    After: return discrepancy labels without importing the production archiver.
    """
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    expected_files = set()
    expected_dirs = set()
    for row in rows:
        path = restored / row["rel"]
        if row.get("dir"):
            expected_dirs.add(row["rel"])
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir():
                bad.append("missing-dir")
            continue
        for parent in Path(row["rel"]).parents:
            if str(parent) != ".":
                expected_dirs.add(parent.as_posix())
        expected_files.add(row["rel"])
        if not path.is_file():
            bad.append("missing-file")
            continue
        info = path.stat()
        row_bad = (
            info.st_size != row["size"]
            or abs(info.st_mtime - float(row["mtime"])) > 1e-3
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            row_bad = True
        if row_bad:
            bad.append("discrepant")
    actual_files = {
        p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_file()
    }
    actual_dirs = {
        p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_dir()
    }
    bad.extend(["extra-file"] * len(actual_files - expected_files))
    bad.extend(["extra-dir"] * len(actual_dirs - expected_dirs))
    return bad


def test_independent_round_trip_verifier(tmp_path: Path) -> None:
    """Before: three clone-shaped trees are archived without the verifier helper.
    During: restore and compare through the independent implementation.
    After: the clean restore passes and a byte mutation returns one discrepancy.
    """
    source = inspect.getsource(_independent_verify)
    assert "archive_tree" not in source
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    origin.mkdir()
    archive.mkdir()
    for index in range(3):
        clone = origin / f"clone-{index}"
        clone.mkdir()
        (clone / "empty").mkdir()
        (clone / "payload.bin").write_bytes(bytes([index]) * (1024 + index))
    approved = tmp_path / "approved.json"
    entries = [
        {
            "rel": f"clone-{index}",
            "sha256": archive_tree.tree_hash(origin / f"clone-{index}"),
        }
        for index in range(3)
    ]
    approved.write_text(json.dumps(entries), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    restored = tmp_path / "restored"
    restored.mkdir()
    with zipfile.ZipFile(row["zip"]) as zipped:
        zipped.extractall(restored)
    _restore_manifest_mtimes(Path(row["manifest"]), restored)
    assert _independent_verify(Path(row["zip"]), Path(row["manifest"]), restored) == []
    mutated = next(restored.rglob("payload.bin"))
    mutated.write_bytes(b"mutated")
    assert (
        len(_independent_verify(Path(row["zip"]), Path(row["manifest"]), restored)) == 1
    )


def test_independent_verifier_uses_three_real_git_clones(tmp_path: Path) -> None:
    """Before: a real git source can be cloned without hardlinks.
    During: archive three real clones, including a file above one MiB, and restore independently.
    After: the clean restore has zero discrepancies and one byte mutation has one.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    (source / "README").write_text("git", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture"],
    ):
        result = subprocess.run(
            command, cwd=source, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    origin.mkdir()
    archive.mkdir()
    for index in range(3):
        clone = origin / f"clone-{index}"
        result = subprocess.run(
            ["git", "clone", "--no-hardlinks", str(source), str(clone)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    approved = tmp_path / "approved.json"
    entries = [
        {
            "rel": f"clone-{index}",
            "sha256": archive_tree.tree_hash(origin / f"clone-{index}"),
        }
        for index in range(3)
    ]
    approved.write_text(json.dumps(entries), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--umbral-hilo",
        str(1024 * 1024),
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    restored = tmp_path / "restored"
    restored.mkdir()
    with zipfile.ZipFile(row["zip"]) as zipped:
        zipped.extractall(restored)
    _restore_manifest_mtimes(Path(row["manifest"]), restored)
    assert _independent_verify(Path(row["zip"]), Path(row["manifest"]), restored) == []
    target = next(restored.rglob("large.bin"))
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    target.write_bytes(data)
    assert (
        len(_independent_verify(Path(row["zip"]), Path(row["manifest"]), restored)) == 1
    )


def test_prohibited_strings_scan_uses_constructed_needles() -> None:
    """Before: source must not bake environment-specific archive names.
    During: scan source using both separators and a date regex.
    After: no forbidden literal or date is present in the implementation.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    needles = [
        "C:" + "/" + "Temp",
        "C:" + "\\" + "Temp",
        "p7_" + "stage_" + "tramo1",
        "flight_" + "archive_" + "kilo",
    ]
    assert not any(needle in source for needle in needles)
    date_pattern = re.compile("20" + r"\d\d-\d\d-\d\d")
    assert not date_pattern.search(source)


def test_prohibited_string_control_positive_scans_script_and_test(
    tmp_path: Path,
) -> None:
    """Before: both forbidden separators exist only in a temporary control file.
    During: scan the implementation and test source plus the control file.
    After: production sources have zero hits and the control file has two hits.
    """
    sources = [SCRIPT, Path(__file__)]
    needles = ["C:" + "/" + "Temp", "C:" + "\\" + "Temp"]
    control = tmp_path / "control.txt"
    control.write_text(needles[0] + "\n" + needles[1], encoding="utf-8")
    assert (
        sum(
            source.read_text(encoding="utf-8").count(needle)
            for source in sources
            for needle in needles
        )
        == 0
    )
    assert (
        sum(control.read_text(encoding="utf-8").count(needle) for needle in needles)
        == 2
    )


def test_min_free_existing_root_rejects_without_writes(tmp_path: Path) -> None:
    """Before: an existing archive root has insufficient free space by policy.
    During: run archive-only with an intentionally impossible minimum.
    After: rc 4 and no family or index are written.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--min-libre",
        str(2**63 - 1),
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 4
    assert list(archive.iterdir()) == []


def test_live_lock_rejects_and_orphan_lock_recovers(tmp_path: Path) -> None:
    """Before: the P7 lock is respectively live and orphaned.
    During: execute the CLI against the same archive root.
    After: live lock rejects, dead PID is recovered, and cleanup releases the lock.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    lock = archive / ".p7.lock"
    p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(ROOT))
    try:
        rejected = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        assert rejected.returncode != 0
    finally:
        p7_common.release_lock(lock)
    lock.write_text(json.dumps({"pid": 99999999, "cwd": str(ROOT)}), encoding="utf-8")
    recovered = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert not lock.exists()


def test_existing_family_aborts_before_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: the deterministic family name already exists.
    During: patch the module clock and execute the archive-only route.
    After: rc 1 and no second index row are produced.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    family = "clone_archive_STAMP"
    (archive / family).mkdir()

    class FixedDateTime:
        @classmethod
        def now(cls, _timezone: object) -> object:
            return type("Stamp", (), {"strftime": lambda _self, _fmt: "STAMP"})()

    monkeypatch.setattr(archive_tree, "datetime", FixedDateTime)
    result = archive_tree.main(
        [
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        ]
    )
    assert result != 0
    assert not (archive / "index.jsonl").exists()


def test_corrupt_zip_rejected_by_independent_zip_check(tmp_path: Path) -> None:
    """Before: archive-only has produced a verified family.
    During: corrupt one zip byte and run the independent verifier.
    After: ArchiveTreeError or BadZipFile is raised before retirement.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    zip_path = Path(row["zip"])
    with zipfile.ZipFile(zip_path) as zipped:
        info = zipped.infolist()[0]
        offset = (
            info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 1
        )
    data = bytearray(zip_path.read_bytes())
    data[offset] ^= 1
    zip_path.write_bytes(data)
    with pytest.raises((archive_tree.ArchiveTreeError, zipfile.BadZipFile)):
        archive_tree._verify_zip(
            zip_path, json.loads(Path(row["manifest"]).read_text(encoding="utf-8"))
        )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires the Windows process table and PEB-derived cwd contract.",
)
def test_real_process_cwd_guard(tmp_path: Path) -> None:
    """Before: a real child has its cwd inside a clone.
    During: inspect the Windows process table and PEB-derived cwd.
    After: the live child is detected, then terminated and reaped.
    """
    assert sys.platform == "win32"
    clone = tmp_path / "clone"
    clone.mkdir()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=clone,
    )
    try:
        time.sleep(0.5)
        assert any(pid == child.pid for pid, _ in archive_tree.active_processes(clone))
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires COMSPEC cmd.exe and live Windows command-line inspection.",
)
def test_real_shell_and_claude_commandline_guard(tmp_path: Path) -> None:
    """Before: real cmd and a copied claude.exe reference a clone.
    During: inspect both live command lines while each process is alive.
    After: both PIDs are detected and always terminated in the cleanup block.
    """
    if sys.platform != "win32":
        pytest.fail("Windows real-process contract is required")
    clone = tmp_path / "clone"
    clone.mkdir()
    command_shell = Path(os.environ["COMSPEC"])
    claude = tmp_path / "claude.exe"
    shutil.copy2(command_shell, claude)
    command = f"echo {clone} & ping 127.0.0.1 -n 30 > nul"
    children = [
        subprocess.Popen([str(command_shell), "/c", command], cwd=clone),
        subprocess.Popen([str(claude), "/c", command], cwd=clone),
    ]
    try:
        time.sleep(0.5)
        found = {pid for pid, _ in archive_tree.active_processes(clone)}
        assert {child.pid for child in children} <= found
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=10)


def test_shell_and_claude_commandline_guard_is_not_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: shell-named processes reference the protected clone.
    During: feed the same process-table shape used by the Windows probe.
    After: shell and claude.exe references are reported, not filtered.
    """
    clone = tmp_path / "clone"
    clone.mkdir()
    rows = [
        (901, "bash.exe " + str(clone), None),
        (902, "claude.exe " + str(clone), None),
    ]
    monkeypatch.setattr(archive_tree, "_process_rows", lambda: rows)
    assert {pid for pid, _ in archive_tree.active_processes(clone)} == {901, 902}


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Before: ``process`` is a fixture process that may have descendants.
    During: terminate the complete Windows process tree and wait for its root.
    After: the launched root is reaped, with no fallback that can leave children alive.
    """
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    process.wait(timeout=10)


def _wait_for_process_references(origin: Path, pids: set[int]) -> None:
    """Before: real fixture processes have just been launched.
    During: poll the production process probe until every PID is visible.
    After: the CLI guard can be exercised without a timing race.
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = {pid for pid, _ in archive_tree.active_processes(origin)}
        if pids <= found:
            return
        time.sleep(0.1)
    assert pids <= {pid for pid, _ in archive_tree.active_processes(origin)}


def _assert_process_abort_result(
    result: subprocess.CompletedProcess[str],
    origin: Path,
    archive: Path,
    before_origin: str,
    before_archive: str,
) -> None:
    """Before: a live-process guard should reject before staging or archive writes.
    During: assert the public CLI failure and its exact diagnostic.
    After: both trees are unchanged and no archive artifact family was created.
    """
    assert result.returncode != 0
    assert "live process references origin" in result.stderr
    assert archive_tree.tree_hash(origin) == before_origin
    assert archive_tree.tree_hash(archive) == before_archive
    paths = list(archive.rglob("*"))
    assert not any(path.name.startswith("clone_archive_") for path in paths)
    assert not any(path.name == "index.jsonl" for path in paths)
    assert not any(path.name.endswith(".tmp") for path in paths)


def _assert_abort_keeps_origin(tmp_path: Path, mutate: object) -> None:
    """Before: an approved clone is changed before combined apply.
    During: execute the supplied destructive-boundary mutation.
    After: apply rejects, origin hash is unchanged, and no family exists.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    mutate(origin)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert archive_tree.tree_hash(origin) == before
    assert not any(
        path.is_dir() and path.name.startswith("clone_archive_")
        for path in archive.iterdir()
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("extra"),
        pytest.param("empty"),
        pytest.param("mtime"),
        pytest.param(
            "junction",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="Requires COMSPEC mklink /J junction creation.",
            ),
        ),
        pytest.param("readonly"),
    ],
)
def test_b05_abort_matrix_keeps_origin(tmp_path: Path, case: str) -> None:
    """Before: archive evidence exists and retire authorization is valid.
    During: mutate the origin and run retire-only preflight for one unsafe case.
    After: retirement aborts without changing the mutated origin or family set.
    """
    origin, archive, approved, digest = _archive_fixture(tmp_path)
    thread, message = _seed_retire_auth(tmp_path, tmp_path)
    families_before = {
        path.name
        for path in archive.iterdir()
        if path.is_dir() and not path.name.endswith(".locks")
    }
    target = tmp_path / "junction-target"
    junction = origin / "clone-a" / "link"
    read_only = origin / "clone-a" / "data.txt"
    try:
        if case == "extra":
            (origin / "clone-a" / "extra.txt").write_text("extra", encoding="utf-8")
        elif case == "empty":
            (origin / "clone-a" / "new-empty").mkdir()
        elif case == "mtime":
            path = origin / "clone-a" / "data.txt"
            os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
        elif case == "junction":
            target.mkdir()
            made = subprocess.run(
                [
                    os.environ["COMSPEC"],
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert made.returncode == 0, made.stderr
        else:
            read_only.chmod(0o444)
        mutated_hash = archive_tree.tree_hash(origin)
        result = _run(
            *_retire_args(origin, archive, approved, digest, thread, message),
            home=tmp_path,
        )
        assert result.returncode == 1
        assert archive_tree.tree_hash(origin) == mutated_hash
        assert (origin / "clone-a").exists()
        assert not any(
            row.get("status") == "RETIRADO"
            for row in p7_common.load_jsonl_index(archive / "index.jsonl")
        )
        assert families_before == {
            path.name
            for path in archive.iterdir()
            if path.is_dir() and not path.name.endswith(".locks")
        }
        if case == "junction":
            error = result.stderr.lower()
            assert "link" in error or "reparse" in error or "enlace" in error
    finally:
        if junction.exists():
            subprocess.run(
                [os.environ["COMSPEC"], "/c", "rmdir", str(junction)],
                capture_output=True,
                check=False,
            )
        read_only.chmod(0o666)


def test_resume_never_deletes_data_tmp_in_dry_run_or_archive(tmp_path: Path) -> None:
    """Before: a resumed stage contains a data file ending in ``.tmp``.
    During: dry-run and archive-only resume inspect it without stage cleanup.
    After: the data file remains and the origin hash is unchanged by dry-run.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    data_tmp = origin / "clone-a" / "data.tmp"
    data_tmp.write_text("payload", encoding="utf-8")
    stage = origin.parent / ".p7_stage_clone_archive"
    stage.mkdir()
    shutil.move(str(origin / "clone-a"), str(stage / "clone-a"))
    _approved(stage, approved)
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    before = archive_tree.tree_hash(stage)
    dry = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--resume",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert dry.returncode == 0, dry.stderr
    assert (stage / "clone-a" / "data.tmp").exists()
    assert archive_tree.tree_hash(stage) == before
    applied = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--resume",
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert applied.returncode == 0, applied.stderr
    assert (origin / "clone-a" / "data.tmp").exists()


def _write_recovery_ledger(
    archive: Path,
    origin: Path,
    record: dict[str, object],
    manifest: list[dict[str, object]],
) -> Path:
    ledger = archive / "retirement_recovery.json"
    ledger.write_text(
        json.dumps(
            {
                "status": "IN_PROGRESS",
                "family": record["family"],
                "origin": str(origin),
                "record": record,
                "manifest": manifest,
            }
        ),
        encoding="utf-8",
    )
    return ledger


def test_recovery_fails_closed_for_process_zip_manifest_and_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: recovery evidence is independently challenged.
    During: each live-process or evidence mismatch is rejected before cleanup.
    After: the origin and recovery ledger remain intact in every case.
    """
    original_active_processes = archive_tree.active_processes
    for case in ("process", "zip", "manifest", "origin"):
        root = tmp_path / case
        origin, archive, record, manifest = _archived_fixture(root)
        ledger = _write_recovery_ledger(archive, origin, record, manifest)
        before = archive_tree.tree_hash(origin)
        if case == "process":
            monkeypatch.setattr(
                archive_tree, "active_processes", lambda _origin: [(1, "live")]
            )
        elif case == "zip":
            Path(record["zip"]).write_bytes(b"corrupt")
        elif case == "manifest":
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["record"]["manifest_sha256"] = "0" * 64
            ledger.write_text(json.dumps(data), encoding="utf-8")
        else:
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["origin"] = str(root / "different-origin")
            ledger.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((archive_tree.ArchiveTreeError, zipfile.BadZipFile)):
            archive_tree._recover_retirement(archive)
        assert archive_tree.tree_hash(origin) == before
        assert ledger.exists()
        if case == "process":
            monkeypatch.setattr(
                archive_tree, "active_processes", original_active_processes
            )


def test_recovery_cleans_only_own_hidden_partials(tmp_path: Path) -> None:
    """Before: recovery has own hidden partials and unrelated temporary files.
    During: recover the archived family and scope cleanup to archive/family paths.
    After: own partials disappear while foreign files do not.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    _write_recovery_ledger(archive, origin, record, manifest)
    own_root = archive / ".archive.tmp"
    own_family = Path(record["zip"]).parent / ".family.tmp"
    foreign_root = archive / "foreign.tmp"
    foreign_family = archive / "other-family"
    foreign_family.mkdir()
    foreign_nested = foreign_family / ".foreign.tmp"
    for path in (own_root, own_family, foreign_root, foreign_nested):
        path.write_text("tmp", encoding="utf-8")
    archive_tree._recover_retirement(archive)
    assert not own_root.exists()
    assert not own_family.exists()
    assert foreign_root.exists()
    assert foreign_nested.exists()


def test_retirement_does_not_overwrite_other_pending_ledger(tmp_path: Path) -> None:
    """Before: family A has an interrupted retirement ledger.
    During: family B attempts to retire against the same archive root.
    After: the operation aborts and family A's ledger bytes are unchanged.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    ledger = _write_recovery_ledger(archive, origin, record, manifest)
    before = ledger.read_bytes()
    with pytest.raises(
        archive_tree.ArchiveTreeError, match="retirement recovery pending"
    ):
        archive_tree._retire(origin, archive, "different-family", record, manifest)
    assert ledger.read_bytes() == before
    assert origin.exists()


def test_approved_entry_without_hash_is_rejected_without_writes(tmp_path: Path) -> None:
    """Before: the list hash is correct but an entry omits its tree hash.
    During: apply validates every approved entry before any archive write.
    After: the exact contract error is returned and the archive stays empty.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    approved.write_text(json.dumps([{"rel": "clone-a"}]), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert "every approved entry needs rel and sha256" in result.stderr
    assert not (archive / "index.jsonl").exists()


@pytest.mark.parametrize("failure", ["returncode", "timeout", "oserror"])
def test_windows_process_listing_fails_closed_and_retries(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Before: Windows process enumeration is unavailable or reports failure.
    During: retry once with 30 seconds after the 10-second attempt.
    After: fail closed instead of allowing retirement to proceed.
    """
    calls: list[int] = []
    monkeypatch.setattr(archive_tree.os, "name", "nt")

    def fake_run(*_args: object, **kwargs: object) -> object:
        calls.append(int(kwargs["timeout"]))
        if failure == "returncode":
            return type("Result", (), {"returncode": 1, "stdout": ""})()
        if failure == "timeout":
            raise subprocess.TimeoutExpired("powershell", kwargs["timeout"])
        raise OSError("powershell unavailable")

    monkeypatch.setattr(archive_tree.subprocess, "run", fake_run)
    with pytest.raises(archive_tree.ArchiveTreeError, match="cannot list processes"):
        archive_tree._process_rows()
    assert calls == [10, 30]


def test_m03_direct_retirement_rejects_extra_origin_file(tmp_path: Path) -> None:
    """Before: archive evidence matches an intact clone origin.
    During: add an unapproved file and invoke direct retirement with saved evidence.
    After: retirement rejects the extra file without changing the origin or ledger.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    extra = origin / "clone-a" / "extra.txt"
    extra.write_text("extra", encoding="utf-8")
    original = origin / "clone-a" / "data.txt"

    with pytest.raises(Exception) as excinfo:
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)

    assert isinstance(excinfo.value, archive_tree.ArchiveTreeError)
    assert "origin has extra or missing" in str(excinfo.value)
    assert original.read_text(encoding="utf-8") == "payload"
    assert (origin / "clone-a" / "empty").is_dir()
    assert extra.read_text(encoding="utf-8") == "extra"
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert sum(row.get("status") == "RETIRADO" for row in rows) == 0
    assert not (archive / "retirement_recovery.json").exists()


def test_m15_direct_retirement_rejects_changed_origin_mtime(tmp_path: Path) -> None:
    """Before: archive evidence includes the original file metadata.
    During: bump a file mtime and invoke direct retirement with saved evidence.
    After: retirement rejects the changed mtime without changing the origin or ledger.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    target = origin / "clone-a" / "data.txt"
    original_mtime = target.stat().st_mtime
    os.utime(target, (target.stat().st_atime, original_mtime + 10))

    caught: Exception | None = None
    try:
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)
    except Exception as exc:
        caught = exc

    assert isinstance(caught, archive_tree.ArchiveTreeError)
    assert "origin changed" in str(caught)
    assert target.read_text(encoding="utf-8") == "payload"
    assert (origin / "clone-a" / "empty").is_dir()
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert sum(row.get("status") == "RETIRADO" for row in rows) == 0
    assert not (archive / "retirement_recovery.json").exists()


def test_m16_rejects_valid_approved_list_with_wrong_list_hash(tmp_path: Path) -> None:
    """Before: the approved entries match the current origin tree.
    During: apply archive with a deliberately incorrect approved-list digest.
    After: the exact list-hash error is returned without archive publication.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    _approved(origin, approved)

    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        "0" * 64,
    )

    assert result.returncode != 0
    assert "approved list hash mismatch" in result.stderr
    assert not (archive / "index.jsonl").exists()
    assert not any(
        path.is_dir() and path.name.startswith("clone_archive_")
        for path in archive.iterdir()
    )


def test_m07_verifies_zip_before_publishing_archive_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: an approved clone and archive root are ready for archive-only mode.
    During: make zip verification fail during the real in-process CLI run.
    After: no ARCHIVADO row is published before verification succeeds.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)

    def fail_verification(_zip_path: Path, _manifest: list[dict[str, object]]) -> None:
        raise archive_tree.ArchiveTreeError("simulated zip verification failure")

    monkeypatch.setattr(archive_tree, "_verify_zip", fail_verification)
    result = archive_tree.main(
        [
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        ]
    )

    assert result != 0
    assert not (archive / "index.jsonl").exists()
    assert not any(
        path.is_file() and path.name == "index.jsonl" for path in archive.iterdir()
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires Windows process-table detection and taskkill cleanup.",
)
def test_b05_live_process_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real child owns the clone as current directory.
    During: combined apply checks the process before staging.
    After: rc is nonzero and origin remains intact after child cleanup.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], cwd=origin / "clone-a"
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires Windows process-table command-line detection and taskkill cleanup.",
)
def test_b03_live_process_commandline_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real child runs outside the clone but its command line names it.
    During: combined apply must reject the command-line reference before any write.
    After: rc, diagnostic, hashes, artifact absence, and child cleanup are verified.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    clone = origin / "clone-a"
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(clone)],
        cwd=tmp_path,
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires COMSPEC cmd.exe with cwd inside the clone.",
)
def test_b03_real_shell_cwd_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real cmd.exe descendant has its cwd inside the clone.
    During: combined apply must reject the shell reference before any write.
    After: rc, diagnostic, hashes, artifact absence, and the complete tree cleanup hold.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    command_shell = Path(os.environ["COMSPEC"])
    child = subprocess.Popen(
        [str(command_shell), "/c", "ping 127.0.0.1 -n 30 > nul"],
        cwd=origin / "clone-a",
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Requires a COMSPEC copy named claude.exe with clone cwd.",
)
def test_b03_claude_exe_fixture_cwd_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a copied COMSPEC named claude.exe has cwd inside the clone.
    During: combined apply must reject it through cwd detection before any write.
    After: rc, diagnostic, hashes, artifact absence, and the complete tree cleanup hold.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    command_shell = Path(os.environ["COMSPEC"])
    claude_fixture = tmp_path / "claude.exe"
    shutil.copy2(command_shell, claude_fixture)
    child = subprocess.Popen(
        [str(claude_fixture), "/c", "ping 127.0.0.1 -n 30 > nul"],
        cwd=origin / "clone-a",
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


def _archived_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], list[dict[str, object]]]:
    """Before: a temporary clone fixture exists.
    During: archive it without retirement and load evidence.
    After: return origin, archive, record, and manifest.
    """
    origin, archive, approved = _fixture(tmp_path)
    (origin / "clone-a" / "second.txt").write_text("second", encoding="utf-8")
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    record = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    return (
        origin,
        archive,
        record,
        json.loads(Path(record["manifest"]).read_text(encoding="utf-8")),
    )


def test_b06_permission_error_leaves_recoverable_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: archive evidence exists and retirement is authorized.
    During: the second unlink raises PermissionError.
    After: no RETIRADO row exists and an IN_PROGRESS ledger remains.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    original = archive_tree._safe_remove
    calls = 0

    def fail_second(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated")
        original(path)

    monkeypatch.setattr(archive_tree, "_safe_remove", fail_second)
    with pytest.raises(PermissionError):
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)
    assert not any(
        row.get("status") == "RETIRADO"
        for row in p7_common.load_jsonl_index(archive / "index.jsonl")
    )
    assert (
        json.loads((archive / "retirement_recovery.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "IN_PROGRESS"
    )
    assert any(origin.rglob("*"))


def test_b10_mixed_archive_tree_and_p7_retire_index(tmp_path: Path) -> None:
    """Before: one clone batch and one regular P7 repository share an archive root.
    During: archive both writers and run real p7_retire dry-runs for both families.
    After: both subprocesses return zero and both family reconciliations are empty.
    """
    origin_a, archive, approved_a = _fixture(tmp_path / "a")
    archive.mkdir(parents=True, exist_ok=True)
    list_hash_a = _approved(origin_a, approved_a)
    archived_a = _run(
        "--origin",
        str(origin_a),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved_a),
        "--list-sha256",
        list_hash_a,
    )
    assert archived_a.returncode == 0, archived_a.stderr
    row_a = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    origin_b = tmp_path / "b" / "repo"
    origin_b.mkdir(parents=True)
    tracked = origin_b / "tracked.txt"
    tracked.write_text("p7", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture"],
    ):
        completed = subprocess.run(
            command, cwd=origin_b, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
    approved_b = tmp_path / "b" / "approved.json"
    entry_b = [
        {
            "rel": "tracked.txt",
            "sha256": hashlib.sha256(tracked.read_bytes()).hexdigest(),
        }
    ]
    approved_b.write_text(json.dumps(entry_b), encoding="utf-8")
    list_hash_b = hashlib.sha256(approved_b.read_bytes()).hexdigest()
    p7_apply = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "flight" / "p7_retire.py"),
            "--archive-root",
            str(archive),
            "--family",
            "p7-family",
            "--origin",
            str(origin_b),
            "--list",
            str(approved_b),
            "--list-sha256",
            list_hash_b,
            "--apply-archive",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert p7_apply.returncode == 0, p7_apply.stderr
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    approved_a_p7 = tmp_path / "a" / "p7-approved.json"
    entry_a_p7 = [
        {
            "rel": "clone-a/data.txt",
            "sha256": hashlib.sha256(
                (origin_a / "clone-a" / "data.txt").read_bytes()
            ).hexdigest(),
        }
    ]
    approved_a_p7.write_text(json.dumps(entry_a_p7), encoding="utf-8")
    list_hash_a_p7 = hashlib.sha256(approved_a_p7.read_bytes()).hexdigest()
    for family, origin, list_path, list_sha in (
        (row_a["family"], origin_a, approved_a_p7, list_hash_a_p7),
        ("p7-family", origin_b, approved_b, list_hash_b),
    ):
        dry = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "flight" / "p7_retire.py"),
                "--archive-root",
                str(archive),
                "--family",
                str(family),
                "--origin",
                str(origin),
                "--list",
                str(list_path),
                "--list-sha256",
                list_sha,
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert dry.returncode == 0, dry.stderr
        assert p7_common.reconcile_index(archive, rows, str(family)) == []


# ==============================================================================
# WOT-2026-190a Tests: Mode --tree, Git Deregistration (g-01), R1 checks (g-04),
# and 15-case Negativas Table (g-05).
# ==============================================================================


def _create_worktree_fixture(tmp_path: Path) -> dict[str, Any]:
    """Create a real git repo with an integrated, clean worktree fixture."""
    main_repo = tmp_path / "main_repo"
    main_repo.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init", "-q", "-b", "main", "."],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(cmd, cwd=main_repo, check=True, capture_output=True)
    (main_repo / "init.txt").write_text("initial", encoding="utf-8")
    subprocess.run(
        ["git", "add", "init.txt"], cwd=main_repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-qm", "init"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )

    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "branch-190a"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )
    (wt / "top.txt").write_text("top file", encoding="utf-8")
    (wt / "sub").mkdir()
    (wt / "sub" / "sub.txt").write_text("sub file", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "add files"],
        check=True,
        capture_output=True,
    )

    # Merge into main so merge-base --is-ancestor succeeds
    subprocess.run(
        ["git", "-C", str(main_repo), "merge", "-q", "--ff-only", "branch-190a"],
        check=True,
        capture_output=True,
    )

    project_root = tmp_path / "project_root"
    done_dir = project_root / ".agent" / "collaboration" / "_archive"
    done_dir.mkdir(parents=True)
    done_file = done_dir / "backlog_done.md"
    done_file.write_text(
        "| 2026-11-25 | WOT-2026-190a | Closed ticket |\n", encoding="utf-8"
    )

    registry = tmp_path / "session_registry.json"
    registry.write_text(
        json.dumps(
            {"sessions": [{"code": "IM-190a", "status": "ASENTADA (conforme)"}]}
        ),
        encoding="utf-8",
    )

    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    approved = tmp_path / "approved.json"
    approved_entry = [{"rel": ".", "sha256": archive_tree.tree_hash(wt)}]
    approved.write_text(json.dumps(approved_entry), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()

    return {
        "main_repo": main_repo,
        "wt": wt,
        "project_root": project_root,
        "registry": registry,
        "archive_root": archive_root,
        "approved": approved,
        "list_hash": list_hash,
        "ticket": "WOT-2026-190a",
        "integrated_into": "main",
        "owner_session": "IM-190a",
    }


def _worktree_cli_args(fix: dict[str, Any], *extra: str) -> list[str]:
    return [
        "--origin",
        str(fix["wt"]),
        "--tree",
        "--archive-root",
        str(fix["archive_root"]),
        "--ticket",
        fix["ticket"],
        "--project-root",
        str(fix["project_root"]),
        "--integrated-into",
        fix["integrated_into"],
        "--registry",
        str(fix["registry"]),
        "--owner-session",
        fix["owner_session"],
        *extra,
    ]


def test_t01_characterization_and_mode_tree(tmp_path: Path) -> None:
    """Before: without --tree, retiring a worktree fails with extra or missing files.
    During: archive and retire with --tree.
    After: with --tree the manifest covers the entire tree and origin is removed.
    """
    fix = _create_worktree_fixture(tmp_path)
    wt = fix["wt"]
    archive = fix["archive_root"]

    # 1. State BEFORE: without --tree
    # Approved list for subdirectories only
    sub_approved = tmp_path / "sub_approved.json"
    sub_approved.write_text(
        json.dumps([{"rel": "sub", "sha256": archive_tree.tree_hash(wt / "sub")}]),
        encoding="utf-8",
    )
    sub_hash = hashlib.sha256(sub_approved.read_bytes()).hexdigest()

    # Dry-run without --tree lists only subdirectories
    dry_without = _run(
        "--origin",
        str(wt),
        "--archive-root",
        str(archive),
        "--list",
        str(sub_approved),
        "--list-sha256",
        sub_hash,
    )
    assert dry_without.returncode == 0, dry_without.stderr
    assert json.loads(dry_without.stdout)["candidates"] == ["sub"]

    # Apply-archive without --tree succeeds for sub
    arch_without = _run(
        "--origin",
        str(wt),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(sub_approved),
        "--list-sha256",
        sub_hash,
    )
    assert arch_without.returncode == 0, arch_without.stderr

    # Apply-retire without --tree MUST fail with rc 1 (extra or missing files/directories)
    thread_id, message_id = _seed_retire_auth(tmp_path, tmp_path, archive_root=archive)
    ret_without = _run(
        "--origin",
        str(wt),
        "--archive-root",
        str(archive),
        "--apply-retire",
        "--list",
        str(sub_approved),
        "--list-sha256",
        sub_hash,
        "--thread-id",
        thread_id,
        "--message-id",
        message_id,
        home=tmp_path,
    )
    assert ret_without.returncode == 1
    assert "extra or missing files/directories" in ret_without.stderr
    assert wt.exists() and (wt / "top.txt").exists() and (wt / ".git").exists()

    # 2. State AFTER: WITH --tree in a fresh archive root
    tree_archive = tmp_path / "tree_archive"
    tree_archive.mkdir()
    fix["archive_root"] = tree_archive

    # Dry-run with --tree
    dry_tree = _run(*_worktree_cli_args(fix))
    assert dry_tree.returncode == 0, dry_tree.stderr
    dry_payload = json.loads(dry_tree.stdout)
    assert dry_payload["status"] == "DRY_RUN"
    assert dry_payload["candidates"] == ["."]

    # Apply-archive with --tree
    arch_tree = _run(
        *_worktree_cli_args(
            fix,
            "--apply-archive",
            "--list",
            str(fix["approved"]),
            "--list-sha256",
            fix["list_hash"],
        )
    )
    assert arch_tree.returncode == 0, arch_tree.stderr

    # Manifest rows MUST include .git and top.txt (full tree)
    index_rows = p7_common.load_jsonl_index(tree_archive / "index.jsonl")
    assert len(index_rows) >= 1
    manifest_path = Path(index_rows[-1]["manifest"])
    manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_rels = {r["rel"] for r in manifest_rows}
    assert ".git" in manifest_rels
    assert "top.txt" in manifest_rels
    assert "sub/sub.txt" in manifest_rels
    expected_rows = archive_tree._tree_rows(fix["wt"])
    assert sorted(manifest_rows, key=lambda x: x["rel"]) == sorted(
        expected_rows, key=lambda x: x["rel"]
    )

    # Apply-retire with --tree
    tree_home = tmp_path / "tree_home"
    tree_thread, tree_message = _seed_retire_auth(
        tmp_path, tree_home, archive_root=tree_archive
    )
    ret_tree = _run(
        *_worktree_cli_args(
            fix,
            "--apply-retire",
            "--list",
            str(fix["approved"]),
            "--list-sha256",
            fix["list_hash"],
            "--thread-id",
            tree_thread,
            "--message-id",
            tree_message,
        ),
        home=tree_home,
    )
    assert ret_tree.returncode == 0, ret_tree.stderr
    assert not wt.exists()


def test_g01_git_deregistration_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify git worktree deregistration: Case A, Case B, Case C, and un-registered origin."""
    fix = _create_worktree_fixture(tmp_path)
    wt = fix["wt"]

    # Case A: Injected runner recording argv
    recorded: list[list[str]] = []
    real_run = subprocess.run

    def recording_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        return real_run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    archive_tree.set_git_runner(recording_runner)
    try:
        res_arch = archive_tree.main(
            _worktree_cli_args(
                fix,
                "--apply-archive",
                "--list",
                str(fix["approved"]),
                "--list-sha256",
                fix["list_hash"],
            )
        )
        assert res_arch == 0
        thread_id, message_id = _seed_retire_auth(
            tmp_path, tmp_path, archive_root=fix["archive_root"]
        )
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        recorded.clear()
        res_ret = archive_tree.main(
            _worktree_cli_args(
                fix,
                "--apply-retire",
                "--list",
                str(fix["approved"]),
                "--list-sha256",
                fix["list_hash"],
                "--thread-id",
                thread_id,
                "--message-id",
                message_id,
            )
        )
        assert res_ret == 0
        assert not wt.exists()

        # Check probe
        probe_calls = [
            c
            for c in recorded
            if "worktree" in c and "list" in c and "--porcelain" in c
        ]
        assert len(probe_calls) >= 1

        # Check baja commands
        rem_calls = [c for c in recorded if "worktree" in c and "remove" in c]
        prune_calls = [
            c
            for c in recorded
            if "worktree" in c and "prune" in c and "--dry-run" not in c
        ]
        assert len(rem_calls) == 1
        assert len(prune_calls) == 1
        # Verification MB4: without force option
        assert "--force" not in rem_calls[0]
        # MB6: probe is not counted as baja
        assert rem_calls[0] != probe_calls[0]
        # Order: remove before prune
        assert recorded.index(rem_calls[0]) < recorded.index(prune_calls[0])
    finally:
        archive_tree.set_git_runner(None)

    # Case B: Real subprocess with real git
    fix_b = _create_worktree_fixture(tmp_path / "b_suite")
    arch_b = _run(
        *_worktree_cli_args(
            fix_b,
            "--apply-archive",
            "--list",
            str(fix_b["approved"]),
            "--list-sha256",
            fix_b["list_hash"],
        )
    )
    assert arch_b.returncode == 0, arch_b.stderr
    thread_b, msg_b = _seed_retire_auth(tmp_path / "b_suite", tmp_path / "b_suite")
    ret_b = _run(
        *_worktree_cli_args(
            fix_b,
            "--apply-retire",
            "--list",
            str(fix_b["approved"]),
            "--list-sha256",
            fix_b["list_hash"],
            "--thread-id",
            thread_b,
            "--message-id",
            msg_b,
        ),
        home=tmp_path / "b_suite",
    )
    assert ret_b.returncode == 0, ret_b.stderr
    assert not fix_b["wt"].exists()
    proc_b = subprocess.run(
        ["git", "-C", str(fix_b["main_repo"]), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(fix_b["wt"]) not in proc_b.stdout
    assert "worktree " in proc_b.stdout  # main worktree still listed

    # Case C: Remove fails with rc 1 -> prune still runs, exit != 0, tree retired
    fix_c = _create_worktree_fixture(tmp_path / "c_suite")
    res_arch_c = archive_tree.main(
        _worktree_cli_args(
            fix_c,
            "--apply-archive",
            "--list",
            str(fix_c["approved"]),
            "--list-sha256",
            fix_c["list_hash"],
        )
    )
    assert res_arch_c == 0
    thread_c, msg_c = _seed_retire_auth(tmp_path / "c_suite", tmp_path / "c_suite")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "c_suite"))
    monkeypatch.setenv("HOME", str(tmp_path / "c_suite"))
    recorded_c: list[list[str]] = []

    def failing_remove_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        recorded_c.append(cmd)
        if "worktree" in cmd and "remove" in cmd:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="simulated remove failure"
            )
        return real_run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    archive_tree.set_git_runner(failing_remove_runner)
    try:
        res_ret_c = archive_tree.main(
            _worktree_cli_args(
                fix_c,
                "--apply-retire",
                "--list",
                str(fix_c["approved"]),
                "--list-sha256",
                fix_c["list_hash"],
                "--thread-id",
                thread_c,
                "--message-id",
                msg_c,
            )
        )
        assert res_ret_c != 0
        # MB5: prune must run even after remove failure
        prune_c = [
            c
            for c in recorded_c
            if "worktree" in c and "prune" in c and "--dry-run" not in c
        ]
        assert len(prune_c) == 1
        # Tree is still retired
        assert not fix_c["wt"].exists()
        rows_c = p7_common.load_jsonl_index(fix_c["archive_root"] / "index.jsonl")
        assert any(r.get("status") == "RETIRADO" for r in rows_c)
    finally:
        archive_tree.set_git_runner(None)

    # Control positivo: Un-registered origin executes 0 remove and 0 prune
    fix_unreg = _create_worktree_fixture(tmp_path / "unreg_wt")
    arch_unreg = _run(
        *_worktree_cli_args(
            fix_unreg,
            "--apply-archive",
            "--list",
            str(fix_unreg["approved"]),
            "--list-sha256",
            fix_unreg["list_hash"],
        )
    )
    assert arch_unreg.returncode == 0, arch_unreg.stderr
    thread_unreg, msg_unreg = _seed_retire_auth(
        tmp_path / "unreg_wt",
        tmp_path / "unreg_wt",
        archive_root=fix_unreg["archive_root"],
    )
    recorded_unreg: list[list[str]] = []

    def unreg_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        recorded_unreg.append(cmd)
        if "rev-parse" in cmd:
            return real_run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        if "worktree" in cmd and "list" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="worktree C:/some/other/path\nHEAD 1234\nbranch refs/heads/main\n\n",
                stderr="",
            )
        return real_run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    archive_tree.set_git_runner(unreg_runner)
    try:
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "unreg_wt"))
        monkeypatch.setenv("HOME", str(tmp_path / "unreg_wt"))
        recorded_unreg.clear()
        res_ret_unreg = archive_tree.main(
            _worktree_cli_args(
                fix_unreg,
                "--apply-retire",
                "--list",
                str(fix_unreg["approved"]),
                "--list-sha256",
                fix_unreg["list_hash"],
                "--thread-id",
                thread_unreg,
                "--message-id",
                msg_unreg,
            )
        )
        assert res_ret_unreg == 0
        assert not fix_unreg["wt"].exists()
        baja_unreg = [
            c
            for c in recorded_unreg
            if "worktree" in c
            and ("remove" in c or ("prune" in c and "--dry-run" not in c))
        ]
        assert len(baja_unreg) == 0
    finally:
        archive_tree.set_git_runner(None)


def test_g04_six_rejection_conditions_and_positive(tmp_path: Path) -> None:
    """Test the 6 rejection conditions and the positive control of g-04."""
    # 1. Ticket ausente de backlog_done.md
    fix1 = _create_worktree_fixture(tmp_path / "c1")
    (
        fix1["project_root"]
        / ".agent"
        / "collaboration"
        / "_archive"
        / "backlog_done.md"
    ).write_text("| 2026-11-25 | WOT-2026-999z | Other |\n", encoding="utf-8")
    r1 = _run(*_worktree_cli_args(fix1))
    assert r1.returncode != 0 and fix1["wt"].exists()

    # 2. No integrado
    fix2 = _create_worktree_fixture(tmp_path / "c2")
    (fix2["wt"] / "unmerged.txt").write_text("unmerged", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(fix2["wt"]), "add", "unmerged.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(fix2["wt"]), "commit", "-qm", "unmerged"],
        check=True,
        capture_output=True,
    )
    r2 = _run(*_worktree_cli_args(fix2))
    assert r2.returncode != 0 and fix2["wt"].exists()

    # 3. Sucio (--ignored no vacio)
    fix3 = _create_worktree_fixture(tmp_path / "c3")
    (fix3["wt"] / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (fix3["wt"] / "ignored.log").write_text("dirty", encoding="utf-8")
    r3 = _run(*_worktree_cli_args(fix3))
    assert r3.returncode != 0 and fix3["wt"].exists()

    # 4. Sesion no asentada (MB7 check casefold: accepted uppercase, rejected active)
    fix4 = _create_worktree_fixture(tmp_path / "c4")
    fix4["registry"].write_text(
        json.dumps({"sessions": [{"code": "IM-190a", "status": "activa"}]}),
        encoding="utf-8",
    )
    r4 = _run(*_worktree_cli_args(fix4))
    assert r4.returncode != 0 and fix4["wt"].exists()

    # 5a. Prune pendiente (entrada colgante)
    fix5 = _create_worktree_fixture(tmp_path / "c5")
    wt_stale = tmp_path / "c5" / "wt_stale"
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-q",
            str(wt_stale),
            "-b",
            "stale-branch",
        ],
        cwd=fix5["main_repo"],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(wt_stale)
    r5 = _run(*_worktree_cli_args(fix5))
    assert r5.returncode != 0 and fix5["wt"].exists()

    # 5b. gc.log presente (MB8)
    fix6 = _create_worktree_fixture(tmp_path / "c6")
    (fix6["main_repo"] / ".git" / "gc.log").write_text(
        "gc log file\n", encoding="utf-8"
    )
    r6 = _run(*_worktree_cli_args(fix6))
    assert r6.returncode != 0 and fix6["wt"].exists()

    # Control positivo: All 5 satisfied, uppercase ASENTADA accepted
    fix_pos = _create_worktree_fixture(tmp_path / "c_pos")
    r_pos = _run(*_worktree_cli_args(fix_pos))
    assert r_pos.returncode == 0, r_pos.stderr

    # Argument validation: multiple origins rejected with rc 2
    r_multi = _run(*_worktree_cli_args(fix_pos), str(tmp_path))
    assert r_multi.returncode == 2

    # Verification: rejection by g-04 does not consume the authorization phrase
    fix_nc = _create_worktree_fixture(tmp_path / "c_nc")
    r_arch_nc = _run(
        *_worktree_cli_args(
            fix_nc,
            "--apply-archive",
            "--list",
            str(fix_nc["approved"]),
            "--list-sha256",
            fix_nc["list_hash"],
        )
    )
    assert r_arch_nc.returncode == 0, r_arch_nc.stderr
    nc_home = tmp_path / "nc_home"
    thread_nc, msg_nc = _seed_retire_auth(
        tmp_path, nc_home, archive_root=fix_nc["archive_root"]
    )
    (
        fix_nc["project_root"]
        / ".agent"
        / "collaboration"
        / "_archive"
        / "backlog_done.md"
    ).write_text("| 2026-11-25 | WOT-2026-999z | Other |\n", encoding="utf-8")
    cmd_nc = _worktree_cli_args(
        fix_nc,
        "--apply-retire",
        "--list",
        str(fix_nc["approved"]),
        "--list-sha256",
        fix_nc["list_hash"],
        "--thread-id",
        thread_nc,
        "--message-id",
        msg_nc,
    )
    r_fail = _run(*cmd_nc, home=nc_home)
    assert r_fail.returncode != 0
    assert fix_nc["wt"].exists()
    (
        fix_nc["project_root"]
        / ".agent"
        / "collaboration"
        / "_archive"
        / "backlog_done.md"
    ).write_text(f"| 2026-11-25 | {fix_nc['ticket']} | Done |\n", encoding="utf-8")
    r_succ = _run(*cmd_nc, home=nc_home)
    assert r_succ.returncode == 0, r_succ.stderr
    assert not fix_nc["wt"].exists()


NEGATIVAS: list[dict[str, Any]] = [
    # 8 filas de WOT-2026-189a
    {
        "id": "189a-apply-apply-retire",
        "extra": ("--apply", "--apply-retire"),
        "expected": "ERROR: --apply cannot be combined with --apply-archive or --apply-retire",
    },
    {
        "id": "189a-apply-apply-retire-recover",
        "extra": ("--apply", "--apply-retire", "--recover-retirement"),
        "expected": "ERROR: --apply cannot be combined with --apply-archive or --apply-retire",
    },
    {
        "id": "189a-apply-alone",
        "extra": ("--apply",),
        "expected": "ERROR: --apply is disabled; use --apply-archive or --apply-retire",
    },
    {
        "id": "189a-recover-resume-retire",
        "extra": ("--recover-retirement", "--resume", "--apply-retire"),
        "expected": "ERROR: --recover-retirement is disabled",
    },
    {
        "id": "189a-resume-apply-retire",
        "extra": ("--resume", "--apply-retire"),
        "expected": "ERROR: --resume cannot be used with --apply-retire",
    },
    {
        "id": "189a-missing-thread-id",
        "extra": ("--apply-retire",),
        "expected": "ERROR: --thread-id es obligatorio",
    },
    {
        "id": "189a-missing-message-id",
        "extra": ("--apply-retire", "--thread-id", "T"),
        "expected": "ERROR: --message-id es obligatorio",
    },
    {
        "id": "189a-missing-list",
        "extra": ("--apply-retire", "--thread-id", "T", "--message-id", "M"),
        "expected": "ERROR: --apply requires --list and --list-sha256",
    },
    # 7 filas nuevas de WOT-2026-190a (tn1 + 6 casos de g-04)
    {
        "id": "tn1-tree-single-step",
        "type": "tree-arg",
        "extra": ("--tree", "--apply"),
        "expected": "ERROR: --apply is disabled",
    },
    {
        "id": "g04-ticket-ausente",
        "type": "g04-c1",
        "expected": "backlog",
    },
    {
        "id": "g04-no-integrado",
        "type": "g04-c2",
        "expected": "ancestor",
    },
    {
        "id": "g04-sucio",
        "type": "g04-c3",
        "expected": "clean",
    },
    {
        "id": "g04-sesion-no-asentada",
        "type": "g04-c4",
        "expected": "settled",
    },
    {
        "id": "g04-prune-pendiente",
        "type": "g04-c5a",
        "expected": "prune",
    },
    {
        "id": "g04-gc-log-presente",
        "type": "g04-c5b",
        "expected": "gc",
    },
]


def test_negativas_exact_ids_and_count() -> None:
    """MB10: assert exact 15 rows and IDs in NEGATIVAS."""
    assert len(NEGATIVAS) == 15
    expected_ids = {
        "189a-apply-apply-retire",
        "189a-apply-apply-retire-recover",
        "189a-apply-alone",
        "189a-recover-resume-retire",
        "189a-resume-apply-retire",
        "189a-missing-thread-id",
        "189a-missing-message-id",
        "189a-missing-list",
        "tn1-tree-single-step",
        "g04-ticket-ausente",
        "g04-no-integrado",
        "g04-sucio",
        "g04-sesion-no-asentada",
        "g04-prune-pendiente",
        "g04-gc-log-presente",
    }
    assert {row["id"] for row in NEGATIVAS} == expected_ids


@pytest.mark.parametrize("row", NEGATIVAS, ids=[r["id"] for r in NEGATIVAS])
def test_negativas_exit_nonzero_and_intact_tree(
    tmp_path: Path, row: dict[str, Any]
) -> None:
    """MB11: each negative case exits with rc!=0 and leaves origin tree intact."""
    row_type = row.get("type", "189a")
    if row_type == "189a":
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "file.txt").write_text("intact", encoding="utf-8")
        archive = tmp_path / "archive"
        before_hash = archive_tree.tree_hash(origin)
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            *row["extra"],
        )
        assert result.returncode != 0
        assert archive_tree.tree_hash(origin) == before_hash
    elif row_type == "tree-arg":
        fix = _create_worktree_fixture(tmp_path)
        before_hash = archive_tree.tree_hash(fix["wt"])
        result = _run(
            "--origin",
            str(fix["wt"]),
            "--archive-root",
            str(fix["archive_root"]),
            *row["extra"],
        )
        assert result.returncode != 0
        assert archive_tree.tree_hash(fix["wt"]) == before_hash
    else:
        fix = _create_worktree_fixture(tmp_path)
        if row_type == "g04-c1":
            (
                fix["project_root"]
                / ".agent"
                / "collaboration"
                / "_archive"
                / "backlog_done.md"
            ).write_text("| 2026-11-25 | OTHER-TICKET | x |\n", encoding="utf-8")
        elif row_type == "g04-c2":
            (fix["wt"] / "unmerged.txt").write_text("x", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(fix["wt"]), "add", "."],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(fix["wt"]), "commit", "-qm", "unmerged"],
                check=True,
                capture_output=True,
            )
        elif row_type == "g04-c3":
            (fix["wt"] / ".gitignore").write_text("x.log\n", encoding="utf-8")
            (fix["wt"] / "x.log").write_text("dirty", encoding="utf-8")
        elif row_type == "g04-c4":
            fix["registry"].write_text(
                json.dumps({"sessions": [{"code": "IM-190a", "status": "activa"}]}),
                encoding="utf-8",
            )
        elif row_type == "g04-c5a":
            stale = tmp_path / "stale_wt"
            subprocess.run(
                ["git", "worktree", "add", "-q", str(stale), "-b", "stale"],
                cwd=fix["main_repo"],
                check=True,
                capture_output=True,
            )
            shutil.rmtree(stale)
        elif row_type == "g04-c5b":
            (fix["main_repo"] / ".git" / "gc.log").write_text(
                "gc log\n", encoding="utf-8"
            )

        before_hash = archive_tree.tree_hash(fix["wt"])
        result = _run(*_worktree_cli_args(fix))
        assert result.returncode != 0
        assert archive_tree.tree_hash(fix["wt"]) == before_hash


def test_negativas_positive_controls(tmp_path: Path) -> None:
    """Verify positive controls of g-02 (tree mutated/retired) and g-04 (accepted)."""
    # Positive of g-04: valid dry run accepted
    fix = _create_worktree_fixture(tmp_path / "pos_g04")
    res = _run(*_worktree_cli_args(fix))
    assert res.returncode == 0, res.stderr

    # Positive of g-02: valid retirement mutates tree (removes clone)
    origin, archive, approved = _fixture(tmp_path / "pos_g02")
    archive.mkdir()
    list_hash = _approved(origin, approved)
    _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    thread, message = _seed_retire_auth(tmp_path / "pos_g02", tmp_path / "pos_g02")
    ret_res = _run(
        *(_retire_args(origin, archive, approved, list_hash, thread, message)),
        home=tmp_path / "pos_g02",
    )
    assert ret_res.returncode == 0
    assert not (origin / "clone-a").exists()
