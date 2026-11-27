"""Pruebas del lector de mensajes de usuario WOT-2026-161b."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "flight" / "user_msgs.py"
SPEC = importlib.util.spec_from_file_location("user_msgs", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("no se pudo cargar user_msgs.py")
user_msgs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(user_msgs)

THREAD_ID = "mcp:thread-161b"


def _create_store(path: Path) -> None:
    """Before: `path` identifies a temporary SQLite store.

    During: creates the measured projection schema and one user plus one non-user row.
    After: the store is readable through verify_user_authorization's public helpers.
    """
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE orchestration_v2_projection_messages (
                message_id TEXT,
                thread_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                streaming INTEGER,
                payload_json TEXT
            );
            CREATE TABLE orchestration_v2_projection_threads (
                thread_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                deleted_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, ?)",
            (THREAD_ID, "2026-11-27T10:00:00.000Z", "2026-11-27T10:00:00.000Z", None),
        )
        connection.executemany(
            "INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "11111111-2222-3333-4444-555555555555",
                    THREAD_ID,
                    "2026-11-27T10:01:00.001Z",
                    "2026-11-27T10:01:00.001Z",
                    0,
                    json.dumps(
                        {
                            "createdBy": "user",
                            "creationSource": "web",
                            "text": "orden de usuario",
                        }
                    ),
                ),
                (
                    "22222222-2222-2222-2222-222222222222",
                    THREAD_ID,
                    "2026-11-27T10:02:00.001Z",
                    "2026-11-27T10:02:00.001Z",
                    0,
                    json.dumps(
                        {
                            "createdBy": "assistant",
                            "creationSource": "web",
                            "text": "respuesta",
                        }
                    ),
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_rc0_reads_user_messages_from_real_projection_schema(
    tmp_path: Path, capsys
) -> None:
    """Before: a real-shaped temporary store contains one user message.

    During: reads only the selected thread and filters created_by == user.
    After: returns rc 0, prints the user row, and reports user msgs: 1.
    """
    database = tmp_path / "statev2.sqlite"
    _create_store(database)

    rc = user_msgs.main([THREAD_ID, "2026-11-27T10:00:00.000Z", "--db", str(database)])

    output = capsys.readouterr()
    assert rc == 0
    assert "orden de usuario" in output.out
    assert "user msgs: 1" in output.out
    assert output.err == ""


def test_rc2_names_unreadable_store(tmp_path: Path, capsys) -> None:
    """Before: the requested database path does not exist.

    During: invokes the read-only store-opening path.
    After: returns rc 2 with the named opening cause on stderr.
    """
    rc = user_msgs.main([THREAD_ID, "--db", str(tmp_path / "missing.sqlite")])

    output = capsys.readouterr()
    assert rc == 2
    assert "no se pudo abrir o leer el almacen" in output.err
    assert "store-missing" in output.err
