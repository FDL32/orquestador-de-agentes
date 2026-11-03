"""Tests de WOT-2026-153v: verificador de procedencia del mensaje del usuario.

Privacidad: NINGUN texto, messageId ni threadId reales aparecen aqui. El
esquema es el DDL REAL medido en el PASO 0 contra una copia de statev2.sqlite
(solo `sqlite_master`, sin datos); las filas son SINTETICAS con las mismas
formas que el productor imprime.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.flight import verify_user_authorization as vua  # noqa: E402


# DDL REAL copiado de sqlite_master de la copia de statev2.sqlite (solo esquema).
MESSAGES_DDL = """
CREATE TABLE orchestration_v2_projection_messages (
      message_id TEXT PRIMARY KEY,
      thread_id TEXT NOT NULL,
      run_id TEXT,
      node_id TEXT,
      role TEXT NOT NULL,
      streaming INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload_json TEXT NOT NULL
    );
"""

THREADS_DDL = """
CREATE TABLE orchestration_v2_projection_threads (
      thread_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      title TEXT NOT NULL,
      default_provider TEXT NOT NULL,
      runtime_mode TEXT NOT NULL,
      interaction_mode TEXT NOT NULL,
      active_provider_thread_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      archived_at TEXT,
      deleted_at TEXT,
      payload_json TEXT NOT NULL
    , provider_instance_id TEXT);
"""

INDEXES_DDL = """
CREATE INDEX orchestration_v2_projection_messages_thread_created_idx
    ON orchestration_v2_projection_messages(thread_id, created_at, message_id);
CREATE INDEX orchestration_v2_projection_messages_run_idx
    ON orchestration_v2_projection_messages(run_id);
CREATE INDEX orchestration_v2_projection_threads_project_updated_idx
    ON orchestration_v2_projection_threads(project_id, updated_at);
"""

SYNTH_THREAD = "11111111-1111-4111-8111-111111111111"
SYNTH_THREAD_MCP = "mcp:22222222-2222-4222-8222-222222222222"
SYNTH_THREAD_BARE = "22222222-2222-4222-8222-222222222222"
ANCHOR_ID = "message:synthetic-anchor-0001"
ANCHOR_CREATED = "2026-01-01T00:00:00.000Z"
CANDIDATE_CREATED = "2026-01-01T00:00:01.000Z"
SHA12 = "0123456789ab"
COMMITS = 3
EXPECTED = vua.ExpectedAuthorization.from_git_parts(
    repo="demo_repo",
    remote="origin",
    branch="feature/x",
    sha12=SHA12,
    commit_count=COMMITS,
)
PHRASE = EXPECTED.phrase
_MISSING = object()


def _payload(
    *,
    message_id: str,
    thread_id: str,
    text: str,
    created_at: str,
    updated_at: str,
    created_by: str = "user",
    creation_source: str = "web",
    sender: object = _MISSING,
    streaming: bool = False,
    role: str = "user",
) -> str:
    payload = {
        "createdBy": created_by,
        "creationSource": creation_source,
        "id": message_id,
        "threadId": thread_id,
        "runId": "run:synthetic",
        "nodeId": "node:synthetic",
        "role": role,
        "text": text,
        "attachments": [],
        "streaming": streaming,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }
    if sender is not _MISSING:
        payload["senderThreadId"] = sender
    return json.dumps(payload, ensure_ascii=False)


def _insert_message(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    thread_id: str = SYNTH_THREAD,
    text: str = PHRASE,
    created_at: str = CANDIDATE_CREATED,
    updated_at: str | None = None,
    created_by: str = "user",
    creation_source: str = "web",
    sender: object = _MISSING,
    streaming: bool = False,
    role: str = "user",
    raw_payload: str | None = None,
) -> None:
    payload = (
        raw_payload
        if raw_payload is not None
        else _payload(
            message_id=message_id,
            thread_id=thread_id,
            text=text,
            created_at=created_at,
            updated_at=updated_at or created_at,
            created_by=created_by,
            creation_source=creation_source,
            sender=sender,
            streaming=streaming,
            role=role,
        )
    )
    connection.execute(
        "INSERT INTO orchestration_v2_projection_messages "
        "(message_id, thread_id, run_id, node_id, role, streaming, "
        " created_at, updated_at, payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            message_id,
            thread_id,
            "run:synthetic",
            "node:synthetic",
            role,
            int(streaming),
            created_at,
            updated_at or created_at,
            payload,
        ),
    )


def _insert_thread(
    connection: sqlite3.Connection,
    *,
    thread_id: str = SYNTH_THREAD,
    deleted_at: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads "
        "(thread_id, project_id, title, default_provider, runtime_mode, "
        " interaction_mode, created_at, updated_at, deleted_at, payload_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            thread_id,
            "project-synthetic",
            "Synthetic thread",
            "synthetic-provider",
            "default",
            "default",
            ANCHOR_CREATED,
            ANCHOR_CREATED,
            deleted_at,
            "{}",
        ),
    )


def build_db(
    tmp_path: Path,
    *,
    rows: list[dict] | None = None,
    anchor: dict | None = None,
    thread_deleted: str | None = None,
    insert_threads: bool = True,
    connection_hook=None,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "state_synthetic.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(MESSAGES_DDL + THREADS_DDL + INDEXES_DDL)
    if insert_threads:
        _insert_thread(connection, deleted_at=thread_deleted)
    anchor_values = {
        "message_id": ANCHOR_ID,
        "text": "peticion sintetica del agente",
        "created_at": ANCHOR_CREATED,
        "created_by": "agent",
        "creation_source": "provider",
        "role": "assistant",
    }
    if anchor:
        anchor_values.update(anchor)
    _insert_message(connection, **anchor_values)
    for row in rows or []:
        _insert_message(connection, **row)
    if connection_hook is not None:
        connection_hook(connection)
    connection.commit()
    connection.close()
    return path


def run(
    db_path: Path,
    *,
    anchor_id: str = ANCHOR_ID,
    consumed: set[str] | None = None,
    expected: vua.ExpectedAuthorization = EXPECTED,
) -> vua.Decision:
    connection = vua.open_store_ro(db_path)
    try:
        predicate = (lambda mid: mid in consumed) if consumed is not None else None
        return vua.find_authorization(
            connection,
            anchor_message_id=anchor_id,
            expected=expected,
            is_consumed=predicate,
        )
    finally:
        connection.close()


# --------------------------------------------------------------------------
# Esquema real y fallos de infraestructura (fail-closed con causa nombrada)
# --------------------------------------------------------------------------


def test_schema_real_ddl_passes(tmp_path):
    connection = vua.open_store_ro(build_db(tmp_path))
    try:
        assert vua.check_schema(connection) is None
    finally:
        connection.close()


def test_missing_table_is_named_infra(tmp_path):
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    connection = vua.open_store_ro(path)
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            vua.check_schema(connection)
        assert excinfo.value.cause == "schema-missing-table"
    finally:
        connection.close()


def test_missing_column_is_named_infra(tmp_path):
    path = tmp_path / "old_schema.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE orchestration_v2_projection_messages ("
        "message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);" + THREADS_DDL
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            vua.check_schema(ro)
        assert excinfo.value.cause == "schema-missing-column"
    finally:
        ro.close()


def test_missing_store_is_named_infra(tmp_path):
    with pytest.raises(vua.InfraError) as excinfo:
        vua.open_store_ro(tmp_path / "does_not_exist.sqlite")
    assert excinfo.value.cause == "store-missing"


def test_corrupt_store_is_named_infra(tmp_path):
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"this is not a sqlite database")
    with pytest.raises(vua.InfraError) as excinfo:
        vua.open_store_ro(path)
    assert excinfo.value.cause == "store-corrupt"


def test_store_is_opened_read_only(tmp_path):
    connection = vua.open_store_ro(build_db(tmp_path))
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO orchestration_v2_projection_threads (thread_id) "
                "VALUES ('x')"
            )
    finally:
        connection.close()


def test_store_sets_query_only(tmp_path):
    connection = vua.open_store_ro(build_db(tmp_path))
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        connection.close()


def test_locked_store_is_named_infra(tmp_path):
    path = tmp_path / "locked.sqlite"
    holder = sqlite3.connect(path)
    holder.execute("CREATE TABLE t(x)")
    holder.commit()
    holder.execute("PRAGMA journal_mode=DELETE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            vua.open_store_ro(path)
        assert excinfo.value.cause == "store-locked"
    finally:
        holder.rollback()
        holder.close()


def test_existing_unopenable_path_is_store_permission(tmp_path):
    path = tmp_path / "directory.sqlite"
    path.mkdir()
    with pytest.raises(vua.InfraError) as excinfo:
        vua.open_store_ro(path)
    assert excinfo.value.cause == "store-permission"


def test_locked_after_open_check_schema_is_infra(tmp_path):
    path = build_db(tmp_path)
    ro = vua.open_store_ro(path)
    holder = sqlite3.connect(path)
    holder.execute("PRAGMA journal_mode=DELETE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            vua.check_schema(ro)
        assert excinfo.value.cause == "store-read-error"
    finally:
        holder.rollback()
        holder.close()
        ro.close()


def test_locked_during_revalidate_is_infra(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    ro = vua.open_store_ro(path)
    holder = sqlite3.connect(path)
    holder.execute("PRAGMA journal_mode=DELETE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            vua.revalidate(
                ro,
                message_id=decision.message_id,
                thread_id=decision.thread_id,
                created_at=decision.created_at,
                text_sha256=decision.text_sha256,
                anchor_message_id=ANCHOR_ID,
                expected=EXPECTED,
            )
        assert excinfo.value.cause == "store-read-error"
    finally:
        holder.rollback()
        holder.close()
        ro.close()


def test_locked_during_pagination_is_infra(tmp_path):
    path = build_db(tmp_path)
    ro = vua.open_store_ro(path)
    holder = sqlite3.connect(path)
    holder.execute("PRAGMA journal_mode=DELETE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(vua.InfraError) as excinfo:
            list(
                vua._iter_thread_messages(
                    ro, SYNTH_THREAD, "0000-00-00T00:00:00.000Z", ""
                )
            )
        assert excinfo.value.cause == "store-read-error"
    finally:
        holder.rollback()
        holder.close()
        ro.close()


def test_wal_reader_works_with_concurrent_writer(tmp_path):
    path = build_db(tmp_path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        _insert_thread(writer, thread_id="55555555-5555-4555-8555-555555555555")
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        reader = vua.open_store_ro(path)
        try:
            count = reader.execute(
                "SELECT count(*) FROM orchestration_v2_projection_threads"
            ).fetchone()[0]
            assert count == 2
            assert vua.check_schema(reader) is None
        finally:
            reader.close()
    finally:
        writer.rollback()
        writer.close()


# --------------------------------------------------------------------------
# Positivos (el predicado DEBE permitir el caso legitimo)
# --------------------------------------------------------------------------


def test_user_web_authorizes(tmp_path):
    decision = run(build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}]))
    assert decision.allowed is True
    assert decision.reason == "authorized"
    assert decision.message_id == SYNTH_THREAD
    assert decision.text_sha256 == vua.sha256_text(PHRASE)


def test_user_mobile_authorizes(tmp_path):
    decision = run(
        build_db(
            tmp_path,
            rows=[{"message_id": SYNTH_THREAD, "creation_source": "mobile"}],
        )
    )
    assert decision.allowed is True


def test_verb_case_insensitive(tmp_path):
    lowered = PHRASE.replace("PUSH", "push", 1)
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": lowered}])
    )
    assert decision.allowed is True


def test_extra_spaces_and_tabs_collapsed(tmp_path):
    spaced = "  " + PHRASE.replace(" ", "  \t ", 2) + "  "
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": spaced}])
    )
    assert decision.allowed is True


def test_nbsp_collapsed(tmp_path):
    text = PHRASE.replace(" ", "\u00a0", 3)
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is True


def test_single_code_fence_unwrapped(tmp_path):
    text = "```\n" + PHRASE + "\n```"
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is True


@pytest.mark.parametrize("mark", ['"', "'", "`"])
def test_each_quote_wrapper_unwrapped(tmp_path, mark):
    decision = run(
        build_db(
            tmp_path,
            rows=[{"message_id": SYNTH_THREAD, "text": f"{mark}{PHRASE}{mark}"}],
        )
    )
    assert decision.allowed is True


def test_sender_thread_id_null_is_absent(tmp_path):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "sender": None}])
    )
    assert decision.allowed is True


def test_uppercase_uuid_form_accepted(tmp_path):
    upper = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    decision = run(build_db(tmp_path, rows=[{"message_id": upper}]))
    assert decision.allowed is True


def test_two_valid_messages_consumes_earliest(tmp_path):
    rows = [
        {"message_id": SYNTH_THREAD, "created_at": CANDIDATE_CREATED},
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
    ]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is True
    assert decision.message_id == SYNTH_THREAD


def test_consumed_earliest_falls_through_to_next(tmp_path):
    rows = [
        {"message_id": SYNTH_THREAD, "created_at": CANDIDATE_CREATED},
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
    ]
    decision = run(build_db(tmp_path, rows=rows), consumed={SYNTH_THREAD})
    assert decision.allowed is True
    assert decision.message_id == "33333333-3333-4333-8333-333333333333"


# --------------------------------------------------------------------------
# Negativos: procedencia, messageId, sender, hilo y orden
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    [
        "scheduled-task-message:",
        "async-answer:",
        "limit-resume:",
        "import:",
        "message:",
        "mcp:",
    ],
)
def test_each_forbidden_prefix_is_rejected(tmp_path, prefix):
    mid = prefix + "synthetic-0001"
    decision = run(build_db(tmp_path, rows=[{"message_id": mid}]))
    assert decision.allowed is False
    assert decision.reason == "message-id-prefix"


def test_forbidden_prefix_wins_even_on_uuid_shaped_id(tmp_path):
    mid = "mcp:" + SYNTH_THREAD
    decision = run(build_db(tmp_path, rows=[{"message_id": mid}]))
    assert decision.allowed is False
    assert decision.reason == "message-id-prefix"


def test_non_uuid_without_prefix_is_message_id_form(tmp_path):
    decision = run(build_db(tmp_path, rows=[{"message_id": "not-a-uuid"}]))
    assert decision.allowed is False
    assert decision.reason == "message-id-form"


@pytest.mark.parametrize(
    "created_by, source",
    [
        ("agent", "web"),
        ("agent", "mcp"),
        ("agent", "provider"),
        ("user", "server"),
        ("agent", "server"),
        ("", "web"),
    ],
)
def test_source_not_accepted_is_rejected(tmp_path, created_by, source):
    decision = run(
        build_db(
            tmp_path,
            rows=[
                {
                    "message_id": SYNTH_THREAD,
                    "created_by": created_by,
                    "creation_source": source,
                }
            ],
        )
    )
    assert decision.allowed is False
    assert decision.reason == "source-not-accepted"


def test_sender_thread_id_present_is_rejected(tmp_path):
    decision = run(
        build_db(
            tmp_path,
            rows=[{"message_id": SYNTH_THREAD, "sender": SYNTH_THREAD_MCP}],
        )
    )
    assert decision.allowed is False
    assert decision.reason == "sender-thread"


def test_sender_thread_id_empty_string_is_rejected(tmp_path):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "sender": ""}])
    )
    assert decision.allowed is False
    assert decision.reason == "sender-thread"


@pytest.mark.parametrize("sender", [123, {"x": 1}, ["mcp:y"], True])
def test_sender_thread_id_non_string_is_rejected(tmp_path, sender):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "sender": sender}])
    )
    assert decision.allowed is False
    assert decision.reason == "sender-thread"


def test_message_from_another_thread_is_not_read(tmp_path):
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "thread_id": SYNTH_THREAD_MCP,
        }
    ]
    path = build_db(tmp_path, rows=rows)
    connection = sqlite3.connect(path)
    _insert_thread(connection, thread_id=SYNTH_THREAD_MCP)
    connection.commit()
    connection.close()
    decision = run(path)
    assert decision.allowed is False
    assert decision.reason == "no-message-after-anchor"


def test_thread_forms_are_not_normalized_anchor_mcp_message_bare(tmp_path):
    anchor = {"thread_id": SYNTH_THREAD_MCP}

    def add_other_thread(connection):
        _insert_thread(connection, thread_id=SYNTH_THREAD_MCP)

    path = build_db(
        tmp_path,
        rows=[{"message_id": SYNTH_THREAD, "thread_id": SYNTH_THREAD_BARE}],
        anchor=anchor,
        connection_hook=add_other_thread,
    )
    decision = run(path)
    assert decision.allowed is False
    assert decision.reason == "no-message-after-anchor"


def test_two_valid_same_timestamp_picks_lower_message_id(tmp_path):
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "created_at": CANDIDATE_CREATED,
        },
        {
            "message_id": "11111111-1111-4111-8111-111111111111",
            "created_at": CANDIDATE_CREATED,
        },
    ]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is True
    assert decision.message_id == "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize(
    "bad",
    [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00.1Z",
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01 00:00:00.000Z",
        " 2026-01-01T00:00:00.000Z",
        "2026-01-01T00:00:00.000+01:00",
    ],
)
def test_anchor_bad_timestamp_form_is_rejected(tmp_path, bad):
    decision = run(build_db(tmp_path, anchor={"created_at": bad}))
    assert decision.allowed is False
    assert decision.reason == "timestamp-form"


@pytest.mark.parametrize(
    "bad",
    [
        "2026-01-01T00:00:30Z",
        "2026-01-01T00:00:30.1Z",
        "2026-01-01T00:00:30.000000Z",
        "2026-01-02 00:00:00.000Z",
        "2026-01-01T00:00:30.000+01:00",
    ],
)
def test_candidate_bad_timestamp_form_is_rejected(tmp_path, bad):
    rows = [{"message_id": SYNTH_THREAD, "created_at": bad}]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is False
    assert decision.reason == "timestamp-form"


@pytest.mark.parametrize(
    "text",
    [
        "PUSH <repo> origin/feature/x 0123456789ab 3",
        "PUSH demo_repo origin/<branch> 0123456789ab 3",
        "PUSH demo_repo origin/feature/x <sha12> 3",
        "PUSH demo_repo origin/feature/x 0123456789ab <N>",
        "PUSH demo_repo origin/feature/x ... 3",
    ],
)
def test_placeholder_template_is_rejected(tmp_path, text):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


def test_message_before_anchor_is_rejected(tmp_path):
    decision = run(
        build_db(
            tmp_path,
            rows=[
                {"message_id": SYNTH_THREAD, "created_at": "2025-12-31T23:59:59.000Z"}
            ],
        )
    )
    assert decision.allowed is False
    assert decision.reason == "no-message-after-anchor"


def test_scan_limit_never_authorizes_after_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(vua, "PAGE_SIZE", 1)
    monkeypatch.setattr(vua, "MAX_PAGES", 1)
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "created_at": CANDIDATE_CREATED,
        },
        {
            "message_id": "44444444-4444-4444-8444-444444444444",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
    ]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is False
    assert decision.reason == "scan-limit"


def _scan_rows(count: int) -> list[dict]:
    ids = [
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
    ]
    rows = [
        {
            "message_id": ids[index],
            "text": "no",
            "created_at": f"2026-01-01T00:00:{index + 1:02d}.000Z",
        }
        for index in range(count)
    ]
    rows[-1]["text"] = PHRASE
    return rows


def test_scan_limit_exactly_max_does_not_truncate(tmp_path, monkeypatch):
    monkeypatch.setattr(vua, "PAGE_SIZE", 2)
    monkeypatch.setattr(vua, "MAX_PAGES", 2)
    decision = run(build_db(tmp_path, rows=_scan_rows(4)))
    assert decision.allowed is True


def test_scan_limit_above_max_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(vua, "PAGE_SIZE", 2)
    monkeypatch.setattr(vua, "MAX_PAGES", 2)
    decision = run(build_db(tmp_path, rows=_scan_rows(5)))
    assert decision.allowed is False
    assert decision.reason == "scan-limit"


def test_scan_limit_new_anchor_authorizes(tmp_path, monkeypatch):
    monkeypatch.setattr(vua, "PAGE_SIZE", 1)
    monkeypatch.setattr(vua, "MAX_PAGES", 1)
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "text": "no",
            "created_at": "2026-01-01T00:00:01.000Z",
        },
        {
            "message_id": "44444444-4444-4444-8444-444444444444",
            "text": "no",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
        {
            "message_id": "55555555-5555-4555-8555-555555555555",
            "text": PHRASE,
            "created_at": "2026-01-01T00:00:03.000Z",
        },
    ]
    path = build_db(tmp_path, rows=rows)
    old = run(path)
    assert old.allowed is False
    assert old.reason == "scan-limit"
    new = run(path, anchor_id="44444444-4444-4444-8444-444444444444")
    assert new.allowed is True


def test_scan_limit_self_service_asks_new_anchor():
    text = vua.format_decision(vua.Decision(False, "scan-limit"), EXPECTED)
    assert "NUEVA peticion" in text
    assert "--anchor-message-id" in text
    assert "NO lo resuelve" in text


def test_scan_starts_after_anchor_in_long_thread(tmp_path):
    path = build_db(tmp_path)
    connection = sqlite3.connect(path)
    old_created = "2025-12-01T00:00:00.000Z"
    batch = []
    for index in range(10050):
        mid = f"00000000-0000-4000-8000-{index:012d}"
        payload = _payload(
            message_id=mid,
            thread_id=SYNTH_THREAD,
            text="mensaje antiguo",
            created_at=old_created,
            updated_at=old_created,
            created_by="agent",
            creation_source="mcp",
        )
        batch.append(
            (
                mid,
                SYNTH_THREAD,
                "run:synthetic",
                "node:synthetic",
                "user",
                0,
                old_created,
                old_created,
                payload,
            )
        )
    connection.executemany(
        "INSERT INTO orchestration_v2_projection_messages "
        "(message_id, thread_id, run_id, node_id, role, streaming, "
        " created_at, updated_at, payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
        batch,
    )
    _insert_message(connection, message_id=SYNTH_THREAD, created_at=CANDIDATE_CREATED)
    connection.commit()
    connection.close()
    decision = run(path)
    assert decision.allowed is True


def test_same_timestamp_higher_message_id_is_after(tmp_path):
    anchor = {
        "message_id": "00000000-0000-4000-8000-000000000000",
        "created_at": ANCHOR_CREATED,
        "created_by": "agent",
        "creation_source": "provider",
    }
    rows = [{"message_id": SYNTH_THREAD, "created_at": ANCHOR_CREATED}]
    decision = run(
        build_db(tmp_path, rows=rows, anchor=anchor), anchor_id=anchor["message_id"]
    )
    assert decision.allowed is True


def test_same_timestamp_lower_message_id_is_before(tmp_path):
    anchor = {
        "message_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "created_at": ANCHOR_CREATED,
        "created_by": "agent",
        "creation_source": "provider",
    }
    rows = [{"message_id": SYNTH_THREAD, "created_at": ANCHOR_CREATED}]
    decision = run(
        build_db(tmp_path, rows=rows, anchor=anchor), anchor_id=anchor["message_id"]
    )
    assert decision.allowed is False
    assert decision.reason == "no-message-after-anchor"


def test_evaluate_record_rejects_before_anchor():
    anchor = vua.MessageRecord(
        message_id="message:anchor",
        thread_id=SYNTH_THREAD,
        created_at=ANCHOR_CREATED,
        updated_at=ANCHOR_CREATED,
        streaming=False,
        created_by="agent",
        creation_source="provider",
        sender_thread_id=None,
        sender_thread_present=False,
        text="x",
        normalized_text="x",
        created_dt=vua._parse_iso(ANCHOR_CREATED),
    )
    before = replace(
        anchor,
        message_id="11111111-1111-4111-8111-111111111111",
        created_at="2025-12-31T23:59:59.000Z",
        updated_at="2025-12-31T23:59:59.000Z",
        created_by="user",
        creation_source="web",
        text=PHRASE,
        normalized_text=PHRASE,
        created_dt=vua._parse_iso("2025-12-31T23:59:59.000Z"),
    )
    decision, failure = vua._evaluate_record(
        before, anchor=anchor, expected=EXPECTED, is_consumed=None
    )
    assert decision is None
    assert failure is None


def test_anchor_missing_is_rejected(tmp_path):
    decision = run(build_db(tmp_path), anchor_id="message:no-such-anchor")
    assert decision.allowed is False
    assert decision.reason == "anchor-missing"


def test_anchor_thread_missing_is_rejected(tmp_path):
    anchor = {"thread_id": "99999999-9999-4999-8999-999999999999"}
    decision = run(build_db(tmp_path, anchor=anchor, insert_threads=False))
    assert decision.allowed is False
    assert decision.reason == "anchor-thread-missing"


def test_deleted_thread_is_rejected(tmp_path):
    decision = run(
        build_db(
            tmp_path,
            rows=[{"message_id": SYNTH_THREAD}],
            thread_deleted="2026-01-02T00:00:00.000Z",
        )
    )
    assert decision.allowed is False
    assert decision.reason == "thread-deleted"


def test_streaming_message_is_not_final(tmp_path):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "streaming": True}])
    )
    assert decision.allowed is False
    assert decision.reason == "not-final"


def test_unreadable_payload_is_reported(tmp_path):
    decision = run(
        build_db(
            tmp_path,
            rows=[{"message_id": SYNTH_THREAD, "raw_payload": "{not json"}],
        )
    )
    assert decision.allowed is False
    assert decision.reason == "payload-unreadable"


def test_best_failure_source_then_text_prefers_text(tmp_path):
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "created_by": "agent",
            "creation_source": "mcp",
            "created_at": CANDIDATE_CREATED,
        },
        {
            "message_id": "44444444-4444-4444-8444-444444444444",
            "text": "no",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
    ]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


def test_best_failure_text_then_source_prefers_text(tmp_path):
    rows = [
        {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "text": "no",
            "created_at": CANDIDATE_CREATED,
        },
        {
            "message_id": "44444444-4444-4444-8444-444444444444",
            "created_by": "agent",
            "creation_source": "mcp",
            "created_at": "2026-01-01T00:00:02.000Z",
        },
    ]
    decision = run(build_db(tmp_path, rows=rows))
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


# --------------------------------------------------------------------------
# Negativos: texto ENTERO (subcadena, plantilla, multilinea, confusables)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "¿escribo " + PHRASE + "?",
        PHRASE + " por favor",
        "PUSH demo_repo origin/feature/x 0123456789ab ",  # 4 tokens
        PHRASE.replace("PUSH", "PUSH PUSH"),
        "```\n```\n" + PHRASE + "\n```",  # doble envoltura
        PHRASE.replace(" ", "-"),
    ],
)
def test_text_not_exactly_the_phrase_is_rejected(tmp_path, text):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


@pytest.mark.parametrize(
    "text",
    [
        PHRASE.replace(" ", "\n", 1),
        PHRASE.replace(" ", "\r\n", 1),
    ],
)
def test_multiline_text_is_rejected(tmp_path, text):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


@pytest.mark.parametrize(
    "text",
    [
        "PUSH demo_repo origin/feature/x 0123456789AB 3",  # SHA mayusculas
        "PUSH demo_repo origin/feature/x 0123456 3",  # SHA abreviado
        "PUSH demo_repo origin/feature/x 0123456789ab 03",  # N con cero
        "PUSH demo_repo origin/feature/x 0123456789ab 0",  # N cero
        "ＰＵＳＨ demo_repo origin/feature/x 0123456789ab 3",  # noqa: RUF001 full-width
        "PU\u017fH demo_repo origin/feature/x 0123456789ab 3",  # long s
        "pu\u017fH demo_repo origin/feature/x 0123456789ab 3",  # long s minuscula
        "PUSH\u2003demo_repo origin/feature/x 0123456789ab 3",  # em space
        "PUSH DEMO_REPO origin/feature/x 0123456789ab 3",  # repo con caja
    ],
)
def test_ambiguous_or_confusable_tokens_are_rejected(tmp_path, text):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"


def test_matches_phrase_rejects_unicode_confusables_in_tokens():
    expected = vua.ExpectedAuthorization.from_git_parts(
        repo="demo_Krepo",
        remote="origin",
        branch="feature/ix",
        sha12="0123456789ab",
        commit_count=3,
    )
    typed_repo = "PUSH demo_\u212arepo origin/feature/ix 0123456789ab 3"
    typed_branch = "PUSH demo_Krepo origin/feature/\u0131x 0123456789ab 3"
    assert vua.matches_phrase(vua.normalize_text(typed_repo), expected.phrase) is False
    assert (
        vua.matches_phrase(vua.normalize_text(typed_branch), expected.phrase) is False
    )


def test_ascii_upper_does_not_fold_long_s():
    assert vua._ascii_upper("pu\u017fh") == "PU\u017fH"
    assert vua._ascii_upper("pu\u017fh") != "PUSH"


@pytest.mark.parametrize("wrong_sha", ["fedcba987654", "01234567ffff"])
def test_different_valid_sha_is_text_mismatch_with_correct_phrase(tmp_path, wrong_sha):
    text = f"PUSH demo_repo origin/feature/x {wrong_sha} 3"
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD, "text": text}])
    )
    assert decision.allowed is False
    assert decision.reason == "text-mismatch"
    message = vua.format_decision(decision, EXPECTED)
    assert EXPECTED.phrase in message
    assert wrong_sha not in message


# --------------------------------------------------------------------------
# Consumo y no-vacuidad (las DOS direcciones de la decision)
# --------------------------------------------------------------------------


def test_every_valid_message_consumed_is_rejected(tmp_path):
    decision = run(
        build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}]), consumed={SYNTH_THREAD}
    )
    assert decision.allowed is False
    assert decision.reason == "consumed"


@pytest.mark.parametrize(
    "mutation",
    [
        {"creation_source": "server"},
        {"created_by": "agent"},
        {"sender": "mcp:synthetic"},
        {"text": PHRASE + "!"},
        {"created_at": "2025-12-31T23:59:59.000Z"},
    ],
)
def test_one_field_flip_turns_allow_into_reject(tmp_path, mutation):
    base = {"message_id": SYNTH_THREAD}
    allowed = run(build_db(tmp_path / "a", rows=[dict(base)]))
    assert allowed.allowed is True
    flipped = run(build_db(tmp_path / "b", rows=[{**base, **mutation}]))
    assert flipped.allowed is False


def test_allow_and_reject_are_not_constant(tmp_path):
    allowed = run(build_db(tmp_path / "ok", rows=[{"message_id": SYNTH_THREAD}]))
    rejected = run(build_db(tmp_path / "no", rows=[]))
    assert allowed.allowed is True
    assert rejected.allowed is False


# --------------------------------------------------------------------------
# Unidades de normalizacion, frase y self-service
# --------------------------------------------------------------------------


def test_expected_phrase_exact_format():
    assert PHRASE == "PUSH demo_repo origin/feature/x 0123456789ab 3"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sha12": "0123456789AB", "commit_count": 3},
        {"sha12": "0123456", "commit_count": 3},
        {"sha12": "0123456789ab", "commit_count": 0},
        {"sha12": "0123456789ab", "commit_count": 3, "repo": "demo repo"},
        {"sha12": "0123456789ab", "commit_count": 3, "branch": "feat`x"},
    ],
)
def test_expected_rejects_bad_parts(kwargs):
    base = {
        "repo": "demo_repo",
        "remote": "origin",
        "branch": "feature/x",
        "sha12": SHA12,
        "commit_count": COMMITS,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        vua.ExpectedAuthorization.from_git_parts(**base)


@pytest.mark.parametrize(
    "bad_sha",
    [
        "0123456789a",
        "0123456789abc",
        "0123456789ab0",
        "0123456789AB",
        "0123456789ag",
        "",
    ],
)
def test_expected_rejects_sha_not_12_lower_hex(bad_sha):
    with pytest.raises(ValueError):
        vua.ExpectedAuthorization.from_git_parts(
            repo="demo_repo",
            remote="origin",
            branch="feature/x",
            sha12=bad_sha,
            commit_count=3,
        )


def test_normalize_non_string_returns_none():
    assert vua.normalize_text(None) is None
    assert vua.normalize_text(42) is None


def test_normalize_keeps_newlines():
    assert "\n" in vua.normalize_text("PUSH a\nb")


def test_matches_phrase_is_whole_text():
    assert vua.matches_phrase(PHRASE, PHRASE) is True
    assert vua.matches_phrase("x " + PHRASE, PHRASE) is False
    assert vua.matches_phrase(None, PHRASE) is False


def test_self_service_message_has_reason_and_phrase():
    decision = vua.Decision(False, "text-mismatch")
    text = vua.format_decision(decision, EXPECTED)
    assert "NO AUTORIZADO" in text
    assert PHRASE in text
    assert "Como repetir" in text


def test_self_service_push_failed_says_burned():
    decision = vua.Decision(False, "push-failed")
    text = vua.format_decision(decision, EXPECTED)
    assert "CONSUMIDA" in text
    assert "mensaje NUEVO" in text
    assert PHRASE in text


@pytest.mark.parametrize(
    "reason",
    [
        "revalidation-edited",
        "revalidation-missing",
        "revalidation-unreadable",
        "revalidation-provenance",
        "revalidation-text",
    ],
)
def test_revalidation_reason_text_is_self_service(reason):
    text = vua.format_decision(vua.Decision(False, reason), EXPECTED)
    assert "motivo no autorizado" not in text
    assert "CONSUMIDA" in text


def test_authorized_message_is_short():
    decision = vua.Decision(True, "authorized", message_id=SYNTH_THREAD)
    assert "AUTORIZADO" in vua.format_decision(decision, EXPECTED)


# --------------------------------------------------------------------------
# Revalidacion justo antes del push
# --------------------------------------------------------------------------


def test_revalidate_accepts_unchanged_message(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            connection,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        connection.close()
    assert again.allowed is True


def test_revalidate_detects_edition(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET payload_json = ? "
        "WHERE message_id = ?",
        (
            _payload(
                message_id=SYNTH_THREAD,
                thread_id=SYNTH_THREAD,
                text=PHRASE + " (editado)",
                created_at=CANDIDATE_CREATED,
                updated_at="2026-01-01T00:00:09.000Z",
            ),
            SYNTH_THREAD,
        ),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-edited"


def test_revalidate_detects_deletion(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "DELETE FROM orchestration_v2_projection_messages WHERE message_id = ?",
        (SYNTH_THREAD,),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-missing"


def test_revalidate_detects_thread_change(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET thread_id = ? "
        "WHERE message_id = ?",
        (SYNTH_THREAD_MCP, SYNTH_THREAD),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-thread"


def test_revalidate_detects_deleted_thread(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_threads SET deleted_at = ? "
        "WHERE thread_id = ?",
        ("2026-01-02T00:00:00.000Z", SYNTH_THREAD),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-thread-state"


def test_revalidate_detects_anchor_moved_after_candidate(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET created_at = ? "
        "WHERE message_id = ?",
        ("2026-01-01T00:00:05.000Z", ANCHOR_ID),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-after-anchor"


def test_revalidate_detects_anchor_deleted(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "DELETE FROM orchestration_v2_projection_messages WHERE message_id = ?",
        (ANCHOR_ID,),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-anchor-missing"


def test_revalidate_detects_created_at_change(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET created_at = ? "
        "WHERE message_id = ?",
        ("2026-01-01T00:00:09.000Z", SYNTH_THREAD),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-edited"


def test_revalidate_candidate_offset_is_revalidation_timestamp_form(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET created_at = ? "
        "WHERE message_id = ?",
        ("2026-01-01T00:00:09.000+01:00", SYNTH_THREAD),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-timestamp-form"


def test_revalidate_detects_anchor_thread_change(tmp_path):
    path = build_db(tmp_path, rows=[{"message_id": SYNTH_THREAD}])
    decision = run(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE orchestration_v2_projection_messages SET thread_id = ? "
        "WHERE message_id = ?",
        (SYNTH_THREAD_MCP, ANCHOR_ID),
    )
    connection.commit()
    connection.close()
    ro = vua.open_store_ro(path)
    try:
        again = vua.revalidate(
            ro,
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
            anchor_message_id=ANCHOR_ID,
            expected=EXPECTED,
        )
    finally:
        ro.close()
    assert again.allowed is False
    assert again.reason == "revalidation-thread"


def test_revalidate_blocks_message_edited_between_find_and_push(tmp_path, monkeypatch):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    base = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    real_find = vua.find_authorization

    def find_then_edit(connection, **kwargs):
        decision = real_find(connection, **kwargs)
        writer = sqlite3.connect(db, timeout=10)
        writer.execute(
            "UPDATE orchestration_v2_projection_messages SET payload_json = ? "
            "WHERE message_id = ?",
            (
                _payload(
                    message_id=SYNTH_THREAD,
                    thread_id=SYNTH_THREAD,
                    text=context.expected.phrase + " (editado)",
                    created_at=CANDIDATE_CREATED,
                    updated_at="2026-01-01T00:00:09.000Z",
                ),
                SYNTH_THREAD,
            ),
        )
        writer.commit()
        writer.close()
        return decision

    monkeypatch.setattr(vua, "find_authorization", find_then_edit)
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_REJECTED
    assert result.decision.reason == "revalidation-edited"
    assert _git(bare, "rev-parse", "refs/heads/main").stdout.strip() == base
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    text = vua.format_decision(result.decision, context.expected)
    assert "CONSUMIDA" in text
    assert "mensaje NUEVO" in text


def test_revalidate_blocks_message_deleted_between_find_and_push(tmp_path, monkeypatch):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    base = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    real_find = vua.find_authorization

    def find_then_delete(connection, **kwargs):
        decision = real_find(connection, **kwargs)
        writer = sqlite3.connect(db, timeout=10)
        writer.execute(
            "DELETE FROM orchestration_v2_projection_messages WHERE message_id = ?",
            (SYNTH_THREAD,),
        )
        writer.commit()
        writer.close()
        return decision

    monkeypatch.setattr(vua, "find_authorization", find_then_delete)
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_REJECTED
    assert result.decision.reason == "revalidation-missing"
    assert _git(bare, "rev-parse", "refs/heads/main").stdout.strip() == base
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


# --------------------------------------------------------------------------
# CAJA 2: ledger O_EXCL, contexto desde git y push a remoto bare TEMPORAL
# --------------------------------------------------------------------------


def _ledger_record(**overrides):
    record = {
        "messageId": "33333333-3333-4333-8333-333333333333",
        "createdAt": CANDIDATE_CREATED,
        "textSha256": vua.sha256_text(PHRASE),
        "fullSha": "a" * 40,
        "anchorMessageId": ANCHOR_ID,
    }
    record.update(overrides)
    return record


def test_ledger_default_path_is_the_contract_path(tmp_path):
    ledger = vua.PushAuthorityLedger.default(tmp_path)
    assert ledger.path == (
        tmp_path.resolve()
        / ".agent"
        / "runtime"
        / "session"
        / "push_authority_ledger.jsonl"
    )


def test_ledger_consumes_only_once(tmp_path):
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    assert ledger.consume(_ledger_record()) is True
    assert ledger.consume(_ledger_record()) is False
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


def test_ledger_line_is_authoritative_without_lock(tmp_path):
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    assert ledger.consume(_ledger_record()) is True
    shutil.rmtree(ledger.lock_dir)
    assert ledger.is_consumed("33333333-3333-4333-8333-333333333333") is True


def test_orphan_lock_counts_as_consumed(tmp_path):
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    ledger.lock_dir.mkdir(parents=True)
    ledger._lock_path("33333333-3333-4333-8333-333333333333").write_text(
        "orphan", encoding="utf-8"
    )
    assert ledger.is_consumed("33333333-3333-4333-8333-333333333333") is True
    assert ledger.consume(_ledger_record()) is False
    assert "lock" in vua.describe_reason("consumed").lower()


def test_ledger_rejects_incomplete_record(tmp_path):
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError):
        ledger.consume({"messageId": "x"})


def test_ledger_consume_loses_lock_race_returns_false(tmp_path, monkeypatch):
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    ledger.lock_dir.mkdir(parents=True)
    ledger._lock_path("33333333-3333-4333-8333-333333333333").write_text(
        "winner", encoding="utf-8"
    )
    monkeypatch.setattr(ledger, "is_consumed", lambda message_id: False)
    assert ledger.consume(_ledger_record()) is False


def test_ledger_two_processes_race_is_exclusive(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from scripts.flight.verify_user_authorization import PushAuthorityLedger\n"
        "record = {\n"
        "    'messageId': '33333333-3333-4333-8333-333333333333',\n"
        "    'createdAt': '2026-01-01T00:00:01.000Z',\n"
        "    'textSha256': '0' * 64,\n"
        "    'fullSha': 'a' * 40,\n"
        "    'anchorMessageId': 'message:synthetic-anchor-0001',\n"
        "}\n"
        "ledger = PushAuthorityLedger(Path(sys.argv[1]))\n"
        "print('CONSUMED' if ledger.consume(record) else 'ALREADY')\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(ledger_path)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=120)[0].strip() for process in processes]
    assert sorted(outputs) == ["ALREADY", "CONSUMED"]
    lines = [
        line
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} rc={completed.returncode}: {completed.stderr}"
        )
    return completed


def make_git_repo(tmp_path: Path, name: str = "work") -> tuple[Path, Path]:
    root = tmp_path / name
    root.mkdir()
    bare = tmp_path / f"{name}_remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    _git(root, "init")
    _git(root, "config", "user.name", "synthetic")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "one")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "origin", "HEAD:refs/heads/main")
    _git(root, "fetch", "origin")
    return root, bare


def advance(root: Path, text: str = "two") -> str:
    (root / "file.txt").write_text(text + "\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", text)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def test_collect_context_builds_phrase_from_git(tmp_path):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, reason = vua.collect_push_context(root, tested_commit_sha=head)
    assert reason is None
    assert context is not None
    assert context.full_sha == head
    assert context.sha12 == head[:12]
    assert context.commit_count == 1
    assert context.expected.phrase == f"PUSH {bare.stem} origin/main {head[:12]} 1"


def test_collect_context_refuses_tested_sha_mismatch(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    context, reason = vua.collect_push_context(root, tested_commit_sha="0" * 40)
    assert context is None
    assert reason == "tested-sha-mismatch"


def test_collect_context_refuses_nothing_to_push(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    context, reason = vua.collect_push_context(root, tested_commit_sha=None)
    assert context is None
    assert reason == "nothing-to-push"


def test_collect_context_refuses_when_remote_not_ancestor(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    advance(root, "two")
    _git(root, "push", "origin", "HEAD:refs/heads/main")
    _git(root, "fetch", "origin")
    _git(root, "reset", "--hard", "HEAD~1")
    (root / "file.txt").write_text("three\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "three")
    context, reason = vua.collect_push_context(root, tested_commit_sha=None)
    assert context is None
    assert reason == "not-ancestor"


def test_collect_refuses_pushurl_mismatch(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    advance(root)
    other = tmp_path / "other.git"
    _git(tmp_path, "init", "--bare", str(other))
    _git(root, "config", "remote.origin.pushurl", str(other))
    context, reason = vua.collect_push_context(root, tested_commit_sha=None)
    assert context is None
    assert reason == "pushurl-mismatch"


def test_collect_refuses_multiple_pushurls(tmp_path):
    root, bare = make_git_repo(tmp_path)
    advance(root)
    _git(root, "config", "remote.origin.pushurl", str(bare))
    _git(root, "config", "--add", "remote.origin.pushurl", str(tmp_path / "other.git"))
    context, reason = vua.collect_push_context(root, tested_commit_sha=None)
    assert context is None
    assert reason == "pushurl-count"


def test_ambiguous_sha12_is_refused_with_fake_runner(tmp_path):
    def fake(args):
        if list(args[:2]) == ["rev-parse", "--verify"]:
            return 128, "", "ambiguous argument"
        raise AssertionError(f"inesperado: {args}")

    assert vua._resolve_unique_commit(fake, "0123456789ab", "a" * 40) == (
        "ambiguous-sha12"
    )


def test_resolve_unique_commit_requires_exact_full_sha(tmp_path):
    def fake(args):
        return 0, "b" * 40 + "\n", ""

    assert vua._resolve_unique_commit(fake, "0123456789ab", "a" * 40) == (
        "ambiguous-sha12"
    )


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/example/demo_repo.git", "demo_repo"),
        ("git@github.com:example/demo_repo.git", "demo_repo"),
        ("/tmp/bare/remote.git", "remote"),
        ("C:/tmp/bare/remote.git", "remote"),
        ("C:\\tmp\\bare\\remote.git", "remote"),
        ("file:///C:/tmp/bare/remote.git", "remote"),
    ],
)
def test_repo_from_url(url, expected):
    assert vua._repo_from_url(url) == expected


def test_prompt_link_keeps_mcp_prefix_and_encodes_phrase():
    link = vua.build_prompt_link(
        environment_id="env-synthetic",
        thread_id="mcp:22222222-2222-4222-8222-222222222222",
        phrase=PHRASE,
    )
    assert link.startswith(
        "t3code://threads/env-synthetic/mcp:22222222-2222-4222-8222-222222222222?prompt="
    )
    assert " " not in link
    assert "%20" in link


def test_wrapper_executes_push_to_temporary_bare_remote(tmp_path):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, reason = vua.collect_push_context(root, tested_commit_sha=head)
    assert reason is None
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_ALLOWED
    assert result.pushed is True
    remote_sha = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    assert remote_sha == head
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    second = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert second.exit_code == vua.EXIT_REJECTED
    assert second.decision.reason == "consumed"


def test_push_does_not_follow_tags(tmp_path):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    _git(root, "tag", "-a", "synthetic-tag", "-m", "tag", head)
    _git(root, "config", "push.followTags", "true")
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_ALLOWED
    assert _git(tmp_path, "ls-remote", "--tags", str(bare)).stdout.strip() == ""


def test_wrapper_dry_run_does_not_push_or_consume(tmp_path):
    root, bare = make_git_repo(tmp_path)
    base = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
        dry_run=True,
    )
    assert result.exit_code == vua.EXIT_ALLOWED
    assert result.pushed is False
    assert _git(bare, "rev-parse", "refs/heads/main").stdout.strip() == base
    assert not ledger.path.exists()


def test_wrapper_rejects_message_in_another_thread(tmp_path):
    root, bare = make_git_repo(tmp_path)
    base = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[
            {
                "message_id": SYNTH_THREAD,
                "thread_id": SYNTH_THREAD_MCP,
                "text": context.expected.phrase,
            }
        ],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_REJECTED
    assert result.decision.reason == "no-message-after-anchor"
    assert _git(bare, "rev-parse", "refs/heads/main").stdout.strip() == base
    assert not ledger.path.exists()


def test_push_command_uses_explicit_refspec(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    real = vua._default_git_runner(root)
    calls: list[list[str]] = []

    def recording(args):
        calls.append(list(args))
        return real(args)

    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
        git_runner=recording,
    )
    assert result.exit_code == vua.EXIT_ALLOWED
    pushes = [call for call in calls if "push" in call]
    assert len(pushes) == 1
    assert "-c" in pushes[0]
    assert "push.followTags=false" in pushes[0]
    assert f"{head}:refs/heads/main" in pushes[0]
    assert f"--force-with-lease=refs/heads/main:{context.remote_sha}" in pushes[0]
    for forbidden in (
        "HEAD:refs/heads/main",
        "--all",
        "--force",
        "-f",
        "--tags",
        "--mirror",
    ):
        assert forbidden not in pushes[0]


def test_wrapper_pushes_tested_sha_when_head_advances(tmp_path):
    root, bare = make_git_repo(tmp_path)
    base = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    tested = advance(root)
    context, reason = vua.collect_push_context(root, tested_commit_sha=tested)
    assert reason is None
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    advanced = advance(root, "three")
    assert advanced != tested
    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
    )
    assert result.exit_code == vua.EXIT_PUSH_FAILED
    assert result.decision.reason == "head-moved"
    remote_sha = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    assert remote_sha == base
    assert remote_sha != advanced
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


def test_ls_remote_mismatch_fails_closed(tmp_path):
    root, _bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    real = vua._default_git_runner(root)
    ls_remote_calls = {"count": 0}

    def mismatching(args):
        if args and args[0] == "ls-remote":
            ls_remote_calls["count"] += 1
            if ls_remote_calls["count"] == 1:
                return 0, context.remote_sha + "\trefs/heads/main\n", ""
            return 0, "b" * 40 + "\trefs/heads/main\n", ""
        return real(args)

    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
        git_runner=mismatching,
    )
    assert result.exit_code == vua.EXIT_PUSH_FAILED
    assert result.decision.reason == "ls-remote-mismatch"


def test_push_rejects_when_remote_moves_after_verification(tmp_path):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init")
    _git(other, "config", "user.name", "synthetic")
    _git(other, "config", "user.email", "synthetic@example.invalid")
    (other / "other.txt").write_text("other\n", encoding="utf-8")
    _git(other, "add", ".")
    _git(other, "commit", "-m", "other")
    other_sha = _git(other, "rev-parse", "HEAD").stdout.strip()
    _git(other, "remote", "add", "origin", str(bare))
    _git(other, "push", "--force", "origin", "HEAD:refs/heads/main")
    real = vua._default_git_runner(root)
    calls: list[list[str]] = []

    def recording(args):
        calls.append(list(args))
        return real(args)

    result = vua.execute_authorized_push(
        context,
        anchor_message_id=ANCHOR_ID,
        db_path=db,
        ledger=ledger,
        git_runner=recording,
    )
    assert result.exit_code == vua.EXIT_PUSH_FAILED
    assert result.decision.reason == "remote-moved"
    assert not [call for call in calls if "push" in call]
    remote_sha = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    assert remote_sha == other_sha
    assert remote_sha != head
    lines = [
        line
        for line in ledger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


def test_collect_refuses_ambiguous_sha12_via_seam(tmp_path, monkeypatch):
    root, _bare = make_git_repo(tmp_path)
    advance(root)
    monkeypatch.setattr(
        vua,
        "_resolve_unique_commit",
        lambda run, sha12, full_sha: "ambiguous-sha12",
    )
    context, reason = vua.collect_push_context(root, tested_commit_sha=None)
    assert context is None
    assert reason == "ambiguous-sha12"


# --------------------------------------------------------------------------
# CLI: rc 10/11/12/20 y frase ya rellenada
# --------------------------------------------------------------------------


def test_cli_returns_10_when_not_authorized(tmp_path, capsys):
    root, _bare = make_git_repo(tmp_path)
    head = advance(root)
    db = build_db(tmp_path / "db")
    rc = vua.main(
        [
            "--project-root",
            str(root),
            "--db",
            str(db),
            "--anchor-message-id",
            ANCHOR_ID,
            "--tested-commit-sha",
            head,
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_REJECTED
    assert "NO AUTORIZADO" in captured.out


def test_cli_returns_11_on_infra(tmp_path, capsys):
    root, _bare = make_git_repo(tmp_path)
    head = advance(root)
    rc = vua.main(
        [
            "--project-root",
            str(root),
            "--db",
            str(tmp_path / "missing.sqlite"),
            "--anchor-message-id",
            ANCHOR_ID,
            "--tested-commit-sha",
            head,
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_INFRA
    assert "INFRAESTRUCTURA" in captured.err


def test_cli_returns_12_on_usage(tmp_path, capsys):
    rc = vua.main(
        [
            "--print-phrase",
            "--project-root",
            str(tmp_path),
            "--db",
            str(tmp_path / "unused.sqlite"),
            "--anchor-message-id",
            ANCHOR_ID,
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_USAGE
    assert "USO" in captured.err


def test_cli_returns_20_on_push_failure(tmp_path, capsys):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    context, _reason = vua.collect_push_context(root, tested_commit_sha=head)
    db = build_db(
        tmp_path / "db",
        rows=[{"message_id": SYNTH_THREAD, "text": context.expected.phrase}],
    )
    lock = bare / "refs" / "heads" / "main.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("locked", encoding="utf-8")
    ledger_path = tmp_path / "ledger.jsonl"
    rc = vua.main(
        [
            "--project-root",
            str(root),
            "--db",
            str(db),
            "--anchor-message-id",
            ANCHOR_ID,
            "--tested-commit-sha",
            head,
            "--ledger",
            str(ledger_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_PUSH_FAILED
    assert "push-failed" in captured.out
    assert "CONSUMIDA" in captured.out
    assert ledger_path.exists()


def test_cli_print_phrase_is_already_filled(tmp_path, capsys):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    db = build_db(tmp_path / "db")
    rc = vua.main(
        [
            "--print-phrase",
            "--project-root",
            str(root),
            "--db",
            str(db),
            "--anchor-message-id",
            ANCHOR_ID,
            "--environment-id",
            "env-synthetic",
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_ALLOWED
    expected_phrase = f"PUSH {bare.stem} origin/main {head[:12]} 1"
    assert expected_phrase in captured.out
    assert "<repo>" not in captured.out
    assert "<sha12>" not in captured.out
    assert f"t3code://threads/env-synthetic/{SYNTH_THREAD}?prompt=" in captured.out
    assert not (tmp_path / "ledger.jsonl").exists()


def test_cli_collect_rejection_prints_phrase_and_repeat(tmp_path, capsys):
    root, bare = make_git_repo(tmp_path)
    head = advance(root)
    other = tmp_path / "other.git"
    _git(tmp_path, "init", "--bare", str(other))
    _git(root, "config", "remote.origin.pushurl", str(other))
    rc = vua.main(
        [
            "--project-root",
            str(root),
            "--db",
            str(tmp_path / "unused.sqlite"),
            "--anchor-message-id",
            ANCHOR_ID,
            "--tested-commit-sha",
            head,
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == vua.EXIT_REJECTED
    assert "Como repetir" in captured.out
    assert "Frase canonica" in captured.out
    expected_phrase = f"PUSH {bare.stem} origin/main {head[:12]} 1"
    assert expected_phrase in captured.out


# --------------------------------------------------------------------------
# Barrera OPT-IN contra el almacen REAL de T3 (no cuenta como evidencia de
# cierre). No imprime ni guarda textos, messageId ni threadId reales.
# --------------------------------------------------------------------------

REAL_STORE_OPT_IN = "IM55_REAL_STORE"
REAL_STORE_THREAD_ENV = "IM55_REAL_THREAD"
REAL_STORE_PATH_ENV = "T3_STATEV2_DB"


def _real_store_path():
    if os.environ.get(REAL_STORE_OPT_IN) != "1":
        return None
    if not os.environ.get(REAL_STORE_THREAD_ENV):
        return None
    raw = os.environ.get(REAL_STORE_PATH_ENV)
    path = Path(raw) if raw else Path(r"C:\Users\fdl\.t3\userdata\statev2.sqlite")
    return path if path.is_file() else None


REAL_STORE = _real_store_path()
REAL_THREAD = os.environ.get(REAL_STORE_THREAD_ENV)


@pytest.mark.skipif(
    REAL_STORE is None,
    reason=(
        "opt-in: define IM55_REAL_STORE=1 e IM55_REAL_THREAD=<threadId> con el "
        "almacen real de T3 disponible"
    ),
)
def test_real_store_given_thread_positive_and_negative(monkeypatch, tmp_path):
    connection = vua.open_store_ro(REAL_STORE)
    try:
        assert vua.check_schema(connection) is None
        rows = list(
            vua._iter_thread_messages(
                connection, REAL_THREAD, "0000-00-00T00:00:00.000Z", ""
            )
        )
        records = [vua._row_to_record(row) for row in rows]
        assert records
        monkeypatch.setattr(vua, "matches_phrase", lambda a, b: a == b)
        agents = 0
        for index, record in enumerate(records[1:], start=1):
            if record.created_by == "user":
                continue
            agents += 1
            expected = vua.ExpectedAuthorization(
                phrase=record.normalized_text or "x",
                sha12="0" * 12,
                commit_count=1,
            )
            decision = vua.find_authorization(
                connection,
                anchor_message_id=records[index - 1].message_id,
                expected=expected,
                is_consumed=lambda _message_id: False,
            )
            assert decision.allowed is False
        assert agents > 0
        positives = 0
        chosen = None
        chosen_expected = None
        chosen_anchor = None
        for index, record in enumerate(records[1:], start=1):
            if record.created_by != "user":
                continue
            if record.creation_source not in ("web", "mobile"):
                continue
            expected = vua.ExpectedAuthorization(
                phrase=record.normalized_text or "x",
                sha12="0" * 12,
                commit_count=1,
            )
            decision = vua.find_authorization(
                connection,
                anchor_message_id=records[index - 1].message_id,
                expected=expected,
                is_consumed=lambda _message_id: False,
            )
            if decision.allowed:
                positives += 1
                chosen = decision
                chosen_expected = expected
                chosen_anchor = records[index - 1]
        assert positives > 0
        assert chosen is not None
        assert chosen_anchor is not None
        assert chosen_expected is not None
        again = vua.revalidate(
            connection,
            message_id=str(chosen.message_id),
            thread_id=str(chosen.thread_id),
            created_at=str(chosen.created_at),
            text_sha256=str(chosen.text_sha256),
            anchor_message_id=chosen_anchor.message_id,
            expected=chosen_expected,
        )
        assert again.allowed is True
    finally:
        connection.close()
    ledger = vua.PushAuthorityLedger(tmp_path / "ledger.jsonl")
    record = {
        "messageId": "synthetic-real-chain",
        "createdAt": "2026-01-01T00:00:00.000Z",
        "textSha256": "0" * 64,
        "fullSha": "a" * 40,
        "anchorMessageId": "synthetic-anchor",
    }
    assert ledger.consume(record) is True
    assert ledger.is_consumed("synthetic-real-chain") is True
