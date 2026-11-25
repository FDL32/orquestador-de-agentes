#!/usr/bin/env python3
"""WOT-2026-192b: tests for startup context measurement by role.

Covers invariant clauses D1-D7 (and aliases M1-M7).
Hermetic: fixtures are generated in tmp_path, never touching ~/.claude, ~/.codex, or live db.
Pure ASCII encoding only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from scripts.flight import measure_startup_context as msc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_claude_fixture(
    path: Path,
    records: list[dict],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _make_codex_fixture(
    path: Path,
    records: list[dict],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _make_opencode_db(
    path: Path,
    sessions: list[dict],
    messages: list[dict],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            directory TEXT,
            title TEXT,
            time_created TEXT,
            parent_id TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE message (
            session_id TEXT,
            time_created TEXT,
            data TEXT
        )
        """
    )
    for s in sessions:
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
            (
                s["id"],
                s.get("directory", ""),
                s.get("title", ""),
                str(s.get("time_created", "")),
                s.get("parent_id"),
            ),
        )
    for m in messages:
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?)",
            (
                m["session_id"],
                str(m.get("time_created", "")),
                json.dumps(m["data"])
                if isinstance(m["data"], dict)
                else str(m["data"]),
            ),
        )
    conn.commit()
    conn.close()
    return path


def test_d1_solo_lectura(tmp_path: Path):
    """D1: El medidor sobre fixtures en tmp no modifica nada ni altera hashes."""
    claude_f = _make_claude_fixture(
        tmp_path / "claude" / "proj-implantador-1" / "session1.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T12:00:00Z",
                "message": {
                    "id": "msg_c1",
                    "usage": {
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 200,
                    },
                },
            }
        ],
    )
    codex_f = _make_codex_fixture(
        tmp_path / "codex" / "rollout1.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "codex_1",
                    "cwd": "C:/repo/flight-orquestadora-3-main",
                    "timestamp": "2026-10-30T12:01:00Z",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 1500,
                            "cached_input_tokens": 300,
                            "cache_write_input_tokens": 50,
                        }
                    },
                },
            },
        ],
    )
    db_f = _make_opencode_db(
        tmp_path / "opencode.db",
        sessions=[
            {
                "id": "oc_1",
                "directory": "C:/repo/agent-triaje-alpha",
                "time_created": "2026-10-30T12:02:00Z",
            }
        ],
        messages=[
            {
                "session_id": "oc_1",
                "time_created": "2026-10-30T12:02:05Z",
                "data": {
                    "role": "assistant",
                    "tokens": {
                        "input": 1200,
                        "cache": {"read": 150, "write": 80},
                    },
                },
            }
        ],
    )

    h_claude_before = _sha256(claude_f)
    h_codex_before = _sha256(codex_f)
    h_db_before = _sha256(db_f)

    rc = msc.main(
        [
            "--claude-jsonl",
            str(claude_f),
            "--codex-jsonl",
            str(codex_f),
            "--opencode-db",
            str(db_f),
        ]
    )
    assert rc == 0

    assert _sha256(claude_f) == h_claude_before
    assert _sha256(codex_f) == h_codex_before
    assert _sha256(db_f) == h_db_before

    status = subprocess.check_output(
        ["git", "status", "--porcelain"], text=True, encoding="utf-8"
    )
    untracked_lines = [
        line for line in status.splitlines() if not line.startswith("??")
    ]
    assert len(untracked_lines) == 0


def test_d2_fixtures_3_formatos(tmp_path: Path, capsys: pytest.CaptureFixture):
    """D2: Parsea fixtures de los 3 formatos (claude, codex, opencode) pasados por flags."""
    claude_f = _make_claude_fixture(
        tmp_path / "c.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/work/task-implantador-a",
                "message": {
                    "id": "c1",
                    "usage": {
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 200,
                    },
                },
            }
        ],
    )
    codex_f = _make_codex_fixture(
        tmp_path / "cx.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "cx1",
                    "cwd": "/work/flight-orquestadora-1",
                    "timestamp": "2026-10-30T10:05:00Z",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 2000,
                            "cached_input_tokens": 400,
                            "cache_write_input_tokens": 150,
                        }
                    },
                },
            },
        ],
    )
    db_f = _make_opencode_db(
        tmp_path / "oc.db",
        sessions=[
            {
                "id": "oc1",
                "directory": "/work/flight-triaje-b",
                "time_created": "2026-10-30T10:10:00Z",
            }
        ],
        messages=[
            {
                "session_id": "oc1",
                "time_created": "2026-10-30T10:10:01Z",
                "data": {
                    "role": "assistant",
                    "tokens": {
                        "input": 1200,
                        "cache": {"read": 50, "write": 25},
                    },
                },
            }
        ],
    )

    rc = msc.main(
        [
            "--claude-jsonl",
            str(claude_f),
            "--codex-jsonl",
            str(codex_f),
            "--opencode-db",
            str(db_f),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "| IM |" in out
    assert "| CO |" in out
    assert "| TRclaude |" in out


def test_d3_tabla_por_rol(tmp_path: Path, capsys: pytest.CaptureFixture):
    """D3: La tabla trae por cada rol mediana, ventana (fecha min-max) y N exactos."""
    claude1 = _make_claude_fixture(
        tmp_path / "c1.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T08:00:00Z",
                "cwd": "/work/implantador-1",
                "message": {
                    "id": "c1",
                    "usage": {
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 50,
                        "cache_read_input_tokens": 50,
                    },
                },
            }
        ],
    )
    claude2 = _make_claude_fixture(
        tmp_path / "c2.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T12:00:00Z",
                "cwd": "/work/implantador-2",
                "message": {
                    "id": "c2",
                    "usage": {
                        "input_tokens": 3000,
                        "cache_creation_input_tokens": 50,
                        "cache_read_input_tokens": 50,
                    },
                },
            }
        ],
    )
    codex1 = _make_codex_fixture(
        tmp_path / "cx1.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "cx1",
                    "cwd": "/work/orquestadora-2",
                    "timestamp": "2026-10-30T09:00:00Z",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 5000,
                            "cached_input_tokens": 100,
                            "cache_write_input_tokens": 200,
                        }
                    },
                },
            },
        ],
    )

    rc = msc.main(
        [
            "--claude-jsonl",
            str(claude1),
            "--claude-jsonl",
            str(claude2),
            "--codex-jsonl",
            str(codex1),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Rol" in out
    assert "Mediana" in out
    assert "Ventana" in out
    assert "N" in out
    # Verificacion estricta de fila completa:
    # IM: mediana total=2100, input=2000, creation=50, read=50, ventana exact min-max, N=2
    assert (
        "| IM | 2100 | 2000 | 50 | 50 | 2026-10-30T08:00:00Z .. 2026-10-30T12:00:00Z | 2 |"
        in out
    )
    # CO: mediana total=5300, input=5000, creation=200, read=100, ventana exact min-max, N=1
    assert (
        "| CO | 5300 | 5000 | 200 | 100 | 2026-10-30T09:00:00Z .. 2026-10-30T09:00:00Z | 1 |"
        in out
    )


def test_d4_cache_separado(tmp_path: Path, capsys: pytest.CaptureFixture):
    """D4: Columnas separadas para cache_creation (100) y cache_read (200)."""
    claude_f = _make_claude_fixture(
        tmp_path / "c_cache.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/work/implantador-spec",
                "message": {
                    "id": "c_cache",
                    "usage": {
                        "input_tokens": 500,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 200,
                    },
                },
            }
        ],
    )
    rc = msc.main(["--claude-jsonl", str(claude_f)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "| Cache Creation | Cache Read |" in out
    assert "| 100 | 200 |" in out


def test_d5_rol_regex(tmp_path: Path, capsys: pytest.CaptureFixture):
    """D5: Clasificacion por regex sobre worktree (-orquestadora-\\d, -implantador-, -triaje-)."""
    f1 = _make_claude_fixture(
        tmp_path / "co.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/repos/vuelo-orquestadora-3-alpha",
                "message": {
                    "id": "1",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        ],
    )
    f2 = _make_claude_fixture(
        tmp_path / "im.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/repos/vuelo-implantador-1-beta",
                "message": {
                    "id": "2",
                    "usage": {
                        "input_tokens": 20,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        ],
    )
    f3 = _make_claude_fixture(
        tmp_path / "tr.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/repos/vuelo-triaje-gamma",
                "message": {
                    "id": "3",
                    "usage": {
                        "input_tokens": 30,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        ],
    )
    f4 = _make_claude_fixture(
        tmp_path / "unk.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-10-30T10:00:00Z",
                "cwd": "/repos/custom-agent-folder",
                "message": {
                    "id": "4",
                    "usage": {
                        "input_tokens": 40,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        ],
    )

    rc = msc.main(
        [
            "--claude-jsonl",
            str(f1),
            "--claude-jsonl",
            str(f2),
            "--claude-jsonl",
            str(f3),
            "--claude-jsonl",
            str(f4),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "| CO |" in out
    assert "| IM |" in out
    assert "| TRclaude |" in out
    assert "| DESCONOCIDO |" in out


def test_d6_warn_rc0(tmp_path: Path, capsys: pytest.CaptureFixture):
    """D6: WARN en salida y rc=0 si sesion sin usage o linea corrupta; rc!=0 solo si unreadable."""
    corrupt_claude = tmp_path / "corrupt.jsonl"
    corrupt_claude.write_text(
        '{"type": "user", "text": "hello"}\n'
        "{bad-json-line\n"
        '{"type": "assistant", "timestamp": "2026-10-30T10:00:00Z", "cwd": "/work/implantador-1", "message": {"id": "ok", "usage": {"input_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}\n',
        encoding="utf-8",
    )
    no_usage_codex = tmp_path / "no_usage.jsonl"
    no_usage_codex.write_text(
        '{"type": "session_meta", "payload": {"id": "cx_none", "cwd": "/work/orquestadora-1", "timestamp": "2026-10-30T10:00:00Z"}}\n',
        encoding="utf-8",
    )

    rc = msc.main(
        [
            "--claude-jsonl",
            str(corrupt_claude),
            "--codex-jsonl",
            str(no_usage_codex),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "WARN" in combined

    # Fail-closed (rc=2) if totally unreadable / nonexistent file
    rc_err = msc.main(["--claude-jsonl", str(tmp_path / "nonexistent.jsonl")])
    assert rc_err == 2


def test_d7_calidad():
    """D7: Gate de calidad y presencia de modulo msc."""
    assert hasattr(msc, "main")
    assert hasattr(msc, "classify_role")
    assert hasattr(msc, "measure_startup")


def test_timestamp_tz_awareness():
    """Verifica que parse_timestamp normalice siempre a timezone UTC (evita TypeError en min/max)."""
    ts_naive = msc.parse_timestamp("2026-10-30T10:00:00")
    ts_aware = msc.parse_timestamp("2026-10-30T12:00:00Z")
    assert ts_naive.tzinfo is not None
    assert ts_aware.tzinfo is not None
    earliest = min(ts_naive, ts_aware)
    latest = max(ts_naive, ts_aware)
    assert earliest <= latest


def test_empty_tokens_triggers_warn_and_excludes_from_table(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """Verifica que mensajes codex con tokens vacios emitan WARN y no cuenten en la tabla."""
    cx = _make_codex_fixture(
        tmp_path / "cx_empty.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "cx_empty",
                    "cwd": "/work/orquestadora-1",
                    "timestamp": "2026-10-30T10:00:00Z",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {}},
                },
            },
        ],
    )
    rc = msc.main(["--codex-jsonl", str(cx)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    # La sesion vacia no debe generar fila en la tabla para CO
    assert "| CO |" not in captured.out


def test_opencode_empty_tokens_triggers_warn_and_excludes_from_table(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """Verifica que mensajes opencode con tokens={} o vacios emitan WARN y se excluyan."""
    db_f = _make_opencode_db(
        tmp_path / "oc_empty.db",
        sessions=[
            {
                "id": "oc_empty_1",
                "directory": "/work/flight-triaje-b",
                "time_created": "2026-10-30T10:10:00Z",
            }
        ],
        messages=[
            {
                "session_id": "oc_empty_1",
                "time_created": "2026-10-30T10:10:01Z",
                "data": {
                    "role": "assistant",
                    "tokens": {},
                },
            }
        ],
    )
    rc = msc.main(["--opencode-db", str(db_f)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "| TRclaude |" not in captured.out


# Aliases according to S6 matrix
test_m1_solo_lectura = test_d1_solo_lectura
test_m2_tres_formatos = test_d2_fixtures_3_formatos
test_m3_tabla_por_rol = test_d3_tabla_por_rol
test_m4_cache_separado = test_d4_cache_separado
test_m5_rol_regex = test_d5_rol_regex
test_m6_warn_rc0 = test_d6_warn_rc0
test_m7_calidad = test_d7_calidad
