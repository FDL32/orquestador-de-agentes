#!/usr/bin/env python3
"""Tests productivos para WOT-2026-215b.

Before: cada caso crea un vuelo y un transcript sinteticos bajo ``tmp_path``.
During: ejecuta el hook como proceso real o llama a los CLIs nuevos.
After: verifica decisiones, telemetria, aislamiento de salidas y controles
negativos sin leer transcripts reales ni el estado real de T3.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".agent" / "hooks" / "native_stop_hook.py"
MODE_CLI = ROOT / "scripts" / "flight" / "stop_consult_mode.py"
PAUSE_CLI = ROOT / "scripts" / "flight" / "stop_consult_pause.py"
ROSTER_CHECK = ROOT / "scripts" / "check_roster_matches_acting_thread.py"
FIXTURE = Path(__file__).parent / "fixtures" / "stop_consult_turns.jsonl"
sys.path.insert(0, str(ROOT / ".agent" / "hooks"))
import native_stop_hook  # noqa: E402, I001

CONSULT_REASON = (
    "BARRERA DE PARADA (WOT-2026-215b): no dejas nada que te responda. Haz una: "
    "(1) ejecuta ya el siguiente paso de tu cola dejando un respondedor "
    "(delegate_task async, schedule_task o tarea en segundo plano); (2) consulta "
    "a tu supervisora con t3_thread_send a <threadId de active_roles.supervisor> "
    "con CONSULTA_SEGUIR_PARAR: <ultima accion> | <cola>, y lanza un temporizador "
    "en segundo plano de 600 s."
)


def _run_hook(payload: str, cwd: Path, hook: Path = HOOK):
    """Before: payload JSON o texto; During: ejecuta el hook; After: devuelve rc, JSON y stderr."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(hook)],
        input=payload.encode("utf-8"),
        cwd=cwd,
        capture_output=True,
    )
    stdout = proc.stdout.decode("utf-8").strip()
    return (
        proc.returncode,
        json.loads(stdout) if stdout else {},
        proc.stderr.decode("utf-8"),
    )


def _roster() -> dict:
    """Before: none; During: creates a minimal active roster; After: returns it."""
    return {
        "active_roles": {
            "orquestador": {
                "session_code": "CO-123",
                "estado": "ACTIVO",
                "threadId": "mcp:orq-thread",
                "version": 1,
                "predecessor_threadId": "mcp:sup-thread",
            },
            "supervisor": {
                "threadId": "mcp:sup-thread",
                "version": 7,
            },
        }
    }


def _make_flight(tmp_path: Path, mode: str = "block", *, token: str | None = None):
    """Before: tmp_path is empty; During: creates repo markers, flight and roster; After: (root, flight)."""
    root = tmp_path / "repo"
    flight = root / ".agent" / "runtime" / "flight" / "flight-1"
    (root / ".claude").mkdir(parents=True)
    flight.mkdir(parents=True)
    (flight / "flight_roster.json").write_text(
        json.dumps(_roster()), encoding="utf-8", newline="\n"
    )
    state = {
        "mode": mode,
        "canary_token": token,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "set_by": "test",
    }
    (flight / "stop_consult_mode.json").write_text(
        json.dumps(state), encoding="utf-8", newline="\n"
    )
    return root, flight


def _turn_rows(*, delegate: bool = False, schedule: bool = False):
    """Before: optional accredited tool; During: builds synthetic JSONL rows; After: rows share one promptId."""
    rows = [
        {
            "type": "user",
            "promptId": "p-1",
            "timestamp": "2026-11-26T10:00:00.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Eres CO-123, ejecuta el siguiente paso."}
                ],
            },
        },
        {
            "type": "assistant",
            "promptId": "p-1",
            "timestamp": "2026-11-26T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Anuncio el paso siguiente y cierro."}
                ],
            },
        },
    ]
    if delegate or schedule:
        tool_name = "delegate_task" if delegate else "schedule_task"
        tool_id = "tool-1"
        rows.extend(
            [
                {
                    "type": "assistant",
                    "promptId": "p-1",
                    "timestamp": "2026-11-26T10:00:02.000Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": tool_name,
                                "input": {"mode": "async"} if delegate else {},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "promptId": "p-1",
                    "timestamp": "2026-11-26T10:00:03.000Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "is_error": False,
                            }
                        ],
                    },
                },
            ]
        )
    return rows


def _write_turn(flight: Path, rows=None):
    """Before: flight exists; During: writes the sanitized turn fixture; After: returns transcript path."""
    transcript = flight / "turn.jsonl"
    if rows is None:
        rows = [
            json.loads(line)
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        ]
    transcript.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return transcript


def _payload(root: Path, transcript: Path | None = None, **extra):
    """Before: root and optional transcript; During: builds Stop payload; After: returns it."""
    payload = {
        "cwd": str(root),
        "session_id": "session-1",
        "prompt_id": "p-1",
        "transcript_path": str(transcript) if transcript else None,
        "stop_hook_active": False,
        "last_assistant_message": "Cierro porque no hay mas trabajo.",
        "background_tasks": [],
        "session_crons": [],
    }
    payload.update(extra)
    return payload


def _observations(flight: Path) -> list[dict]:
    """Before: flight may have observation JSONL; During: parses it; After: returns records."""
    target = flight / "stop_consult_observations.jsonl"
    if not target.exists():
        return []
    return [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize(
    "prior_blocks, mode, kind, expected",
    [
        (0, "block", "plain", "block"),
        (1, "block", "plain", "block"),
        (2, "block", "plain", "block"),
        (3, "block", "plain", "block"),
        (4, "block", "plain", "block"),
        (5, "block", "plain", "tope"),
        (6, "block", "plain", "tope"),
        (0, "observe", "plain", "observe_habria_bloqueado"),
        (0, "canary", "plain", "observe_habria_bloqueado"),
        (0, "canary", "token", "block"),
        (0, "block", "delegate", "continue"),
        (0, "block", "schedule", "continue"),
        (0, "block", "background", "continue"),
        (0, "block", "reentry", "reentrada"),
        (0, "block", "no_transcript", "sin_transcript"),
    ],
)
def test_a12_controls_and_mutants(tmp_path, prior_blocks, mode, kind, expected):  # noqa: C901
    """Before: 15 A12 controls; During: exercises limits and escapes; After: decision and row agree."""
    token = "CANARY-123" if mode == "canary" else None
    root, flight = _make_flight(tmp_path, mode, token=token)
    transcript = _write_turn(flight)
    now = datetime.now(timezone.utc)
    for _index in range(prior_blocks):
        row = {
            "ts": (now - timedelta(minutes=1)).isoformat(),
            "session_id": "session-1",
            "prompt_id": "old",
            "es_orquestadora": True,
            "modo": "block",
            "respondedor": None,
            "pausa": False,
            "decision": "block",
            "motivo": "candidato",
            "has_transcript_path": True,
            "payload_keys": [],
        }
        target = flight / "stop_consult_observations.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row) + "\n")
    rows = None
    payload_extra = {}
    if kind == "delegate":
        rows = _turn_rows(delegate=True)
    elif kind == "schedule":
        rows = _turn_rows(schedule=True)
    elif kind == "background":
        payload_extra["background_tasks"] = [{"id": "timer-1"}]
    elif kind == "token":
        rows = _turn_rows()
        rows[0]["message"]["content"][0]["text"] += " CANARY-123"
    elif kind == "reentry":
        payload_extra["stop_hook_active"] = True
    elif kind == "no_transcript":
        transcript = None
    if rows is not None:
        transcript = _write_turn(flight, rows)
    result = native_stop_hook._decide(_payload(root, transcript, **payload_extra))
    if expected == "block":
        assert result["decision"] == "block"
    else:
        assert result == {"continue": True} or result.get("continue") is True
    row = _observations(flight)[-1]
    if expected in {"tope", "observe_habria_bloqueado", "reentrada", "sin_transcript"}:
        assert row["motivo"] == expected


def test_turno_real_uses_sanitized_fixture_and_blocks(tmp_path):
    """Before: fixture realista; During: runs block mode; After: exactly one block is emitted."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight)
    rc, result, _ = _run_hook(json.dumps(_payload(root, transcript)), root)
    assert rc == 0
    assert result["decision"] == "block"
    assert _observations(flight)[-1]["decision"] == "block"


def test_turno_real_delegate_async_sin_error_continue(tmp_path):
    """Before: same turn with delegate_task async; During: process hook; After: accredited continuation passes."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight, _turn_rows(delegate=True))
    result = _run_hook(json.dumps(_payload(root, transcript)), root)[1]
    assert result == {"continue": True}
    assert _observations(flight)[-1]["respondedor"] == "delegate_async"


def test_delegate_error_is_not_accredited(tmp_path):
    """Before: delegate result is_error=true; During: pairs the real transcript; After: it still blocks."""
    root, flight = _make_flight(tmp_path, "block")
    rows = _turn_rows(delegate=True)
    rows[-1]["message"]["content"][0]["is_error"] = True
    transcript = _write_turn(flight, rows)
    result = native_stop_hook._decide(_payload(root, transcript))
    assert result["decision"] == "block"


def test_created_by_user(tmp_path, monkeypatch):
    """Before: SQLite synthetic store says createdBy=user; During: runs A16; After: turn is exempted."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight)
    db = tmp_path / "statev2.sqlite"
    _make_store(db, "user")
    monkeypatch.setenv("T3_STATE_DB", str(db))
    result = native_stop_hook._decide(_payload(root, transcript))
    assert result == {"continue": True}
    assert _observations(flight)[-1]["motivo"] == "turno_de_usuario"


def test_created_by_user_agent_blocks(tmp_path, monkeypatch):
    """Before: store candidate is agent; During: A16 does not exempt; After: block remains."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight)
    db = tmp_path / "statev2.sqlite"
    _make_store(db, "agent")
    monkeypatch.setenv("T3_STATE_DB", str(db))
    result = native_stop_hook._decide(_payload(root, transcript))
    assert result["decision"] == "block"
    assert _observations(flight)[-1]["motivo"] == "candidato"


def test_created_by_user_ilegible_store_no_medido_origen(tmp_path, monkeypatch):
    """Before: store is not SQLite; During: A16 fails open; After: decision keeps a no_medido_origen note."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight)
    db = tmp_path / "statev2.sqlite"
    db.write_text("not sqlite", encoding="utf-8")
    monkeypatch.setenv("T3_STATE_DB", str(db))
    result = native_stop_hook._decide(_payload(root, transcript))
    assert result["decision"] == "block"
    assert _observations(flight)[-1]["nota"] == "no_medido_origen"


def _make_store(path: Path, created_by: str, *, duplicate: bool = False):
    """Before: path is unused; During: creates the measured SQLite schema and message; After: file is queryable read-only."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE orchestration_v2_projection_messages (
          message_id TEXT, thread_id TEXT, run_id TEXT, node_id TEXT,
          role TEXT, created_at TEXT, updated_at TEXT, streaming INTEGER,
          payload_json TEXT
        );
        CREATE TABLE orchestration_v2_projection_threads (
          thread_id TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT
        );
        """
    )
    message = {
        "createdBy": created_by,
        "creationSource": "web",
        "text": "Eres CO-123, ejecuta el siguiente paso.",
    }
    rows = 2 if duplicate else 1
    for index in range(rows):
        connection.execute(
            "INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"message-{index}",
                "orq-thread",
                "run-1",
                "node-1",
                "user",
                f"2026-11-26T10:00:0{index}.000Z",
                f"2026-11-26T10:00:0{index}.000Z",
                0,
                json.dumps(message),
            ),
        )
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, ?)",
        ("orq-thread", "2026-11-26T09:00:00.000Z", "2026-11-26T10:00:00.000Z", None),
    )
    connection.commit()
    connection.close()


def test_telemetry_fields(tmp_path):
    """Before: ordinary candidate; During: records one row; After: privacy-safe fields are complete."""
    root, flight = _make_flight(tmp_path, "observe")
    transcript = _write_turn(flight)
    payload = _payload(root, transcript, private_message="must-not-be-recorded")
    native_stop_hook._decide(payload)
    row = _observations(flight)[-1]
    assert set(
        (
            "ts",
            "session_id",
            "prompt_id",
            "es_orquestadora",
            "modo",
            "respondedor",
            "pausa",
            "decision",
            "motivo",
            "has_transcript_path",
            "payload_keys",
        )
    ) <= set(row)
    assert row["payload_keys"] == sorted(payload)
    assert "must-not-be-recorded" not in json.dumps(row)


def test_vuelo_ambiguo(tmp_path):
    """Before: two flights; During: invokes Stop; After: no-op, exact warning and no row."""
    root, first = _make_flight(tmp_path, "block")
    second = root / ".agent" / "runtime" / "flight" / "flight-2"
    second.mkdir()
    (second / "flight_roster.json").write_text(json.dumps(_roster()), encoding="utf-8")
    (second / "stop_consult_mode.json").write_text(
        json.dumps({"mode": "block"}), encoding="utf-8"
    )
    transcript = _write_turn(first)
    rc, result, stderr = _run_hook(json.dumps(_payload(root, transcript)), root)
    assert rc == 0
    assert result == {"continue": True}
    assert "native_stop_hook: vuelo_ambiguo; consulta de parada omitida" in stderr
    assert not list(root.rglob("stop_consult_observations.jsonl"))


def test_stop_hook_active(tmp_path):
    """Before: active reentry flag; During: calls consult branch; After: no block and reentry telemetry."""
    root, flight = _make_flight(tmp_path, "block")
    transcript = _write_turn(flight)
    result = native_stop_hook._decide(_payload(root, transcript, stop_hook_active=True))
    assert result == {"continue": True}
    assert _observations(flight)[-1]["motivo"] == "reentrada"


def test_reason_literal():
    """Before: source exposes the contract constant; During: compares emitted text; After: literal is exact."""
    assert native_stop_hook._CONSULT_REASON == CONSULT_REASON


def test_fail_open_process_cases(tmp_path):
    """Before: malformed stdin variants; During: process hook with a flight; After: rc 0 and continue."""
    root, flight = _make_flight(tmp_path, "block")
    cases = ["", "not-json", json.dumps({"cwd": str(root), "stop_hook_active": False})]
    for raw in cases:
        rc, result, _ = _run_hook(raw, root)
        assert rc == 0
        assert result == {"continue": True}
    assert len(_observations(flight)) == 3
    assert all(row["decision"] == "no_medido" for row in _observations(flight))


def test_mode_cli_four_modes_and_invalid(tmp_path):
    """Before: explicit flight dir; During: uses on/off/status; After: four modes and invalid rejection are measured."""
    root, flight = _make_flight(tmp_path, "off")
    for mode in ("off", "observe", "block"):
        args = [
            sys.executable,
            str(MODE_CLI),
            "on",
            "--flight-dir",
            str(flight),
            "--mode",
            mode,
        ]
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True)
        assert proc.returncode == 0
        assert (
            json.loads((flight / "stop_consult_mode.json").read_text())["mode"] == mode
        )
    proc = subprocess.run(
        [
            sys.executable,
            str(MODE_CLI),
            "on",
            "--flight-dir",
            str(flight),
            "--mode",
            "canary",
            "--canary-token",
            "T",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert (
        json.loads((flight / "stop_consult_mode.json").read_text())["mode"] == "canary"
    )
    before = (flight / "stop_consult_mode.json").read_text()
    proc = subprocess.run(
        [
            sys.executable,
            str(MODE_CLI),
            "on",
            "--flight-dir",
            str(flight),
            "--mode",
            "bogus",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert (flight / "stop_consult_mode.json").read_text() == before


def test_mode_status_report_keys(tmp_path):
    """Before: report contains recent counters; During: invokes status --report; After: exact key set is stable."""
    root, flight = _make_flight(tmp_path, "observe")
    target = flight / "stop_consult_observations.jsonl"
    target.write_text(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "decision": "no_medido",
                "motivo": "escape_segundo_cierre",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(MODE_CLI),
            "status",
            "--report",
            "--flight-dir",
            str(flight),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert set(report) == {"modo", "no_medido", "topes", "escapes", "ventana_h", "rc"}
    assert report["ventana_h"] == 24
    assert report["rc"] == 0


def test_pause_only_supervisor_and_ledger(tmp_path):
    """Before: copied roster/registry; During: sets pause for supervisor and rejects stranger; After: atomic pause plus valid ledger."""
    root, flight = _make_flight(tmp_path, "block")
    (flight / "session_registry.json").write_text(
        json.dumps({"sessions": []}), encoding="utf-8"
    )
    roster = flight / "flight_roster.json"
    good = subprocess.run(
        [
            sys.executable,
            str(PAUSE_CLI),
            "--set",
            "--minutos",
            "10",
            "--consulta",
            "espera",
            "--acting-thread",
            "mcp:sup-thread",
            "--flight-dir",
            str(flight),
            "--roster-path",
            str(roster),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0, good.stderr + good.stdout
    pause = json.loads((flight / "stop_consult_pause.json").read_text())
    assert pause["epoca"] == "7"
    ledger = flight / "comms_ledger.jsonl"
    validator = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "flight" / "validate_ledger.py"),
            "--ledger",
            str(ledger),
        ],
        capture_output=True,
        text=True,
    )
    assert validator.returncode == 0
    tampered = json.loads(roster.read_text())
    tampered["active_roles"]["supervisor"]["threadId"] = "mcp:other"
    roster.write_text(json.dumps(tampered), encoding="utf-8")
    bad = subprocess.run(
        [
            sys.executable,
            str(PAUSE_CLI),
            "--set",
            "--minutos",
            "10",
            "--consulta",
            "espera",
            "--acting-thread",
            "mcp:sup-thread",
            "--flight-dir",
            str(flight),
            "--roster-path",
            str(roster),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0


def test_pause_old_epoch_does_not_exempt(tmp_path):
    """Before: pause has a future expiry but stale epoch; During: validates all authority fields; After: block remains."""
    root, flight = _make_flight(tmp_path, "block")
    now = datetime.now(timezone.utc)
    (flight / "stop_consult_pause.json").write_text(
        json.dumps(
            {
                "hasta": (now + timedelta(minutes=10)).isoformat(),
                "epoca": "6",
                "supervisor_threadId": "mcp:sup-thread",
                "set_at": now.isoformat(),
                "minutos": 10,
                "consulta": "espera",
                "acting_thread": "mcp:sup-thread",
            }
        ),
        encoding="utf-8",
    )
    transcript = _write_turn(flight)
    result = native_stop_hook._decide(_payload(root, transcript))
    assert result["decision"] == "block"


def test_off_is_byte_identical_to_base(tmp_path):
    """Before: paired roots and base hook from git; During: runs both; After: rc/stdout/stderr match."""
    current = tmp_path / "current"
    base = tmp_path / "base"
    for root in (current, base):
        (root / ".claude").mkdir(parents=True)
        (root / ".agent" / "hooks").mkdir(parents=True)
        (root / "scripts" / "flight").mkdir(parents=True)
        (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    source = subprocess.run(
        [
            "git",
            "show",
            "46cdcdb697026c9417efa6c4bbc331c2937406ac:.agent/hooks/native_stop_hook.py",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    (base / ".agent" / "hooks" / "native_stop_hook.py").write_bytes(source)
    shutil.copy2(
        ROOT / "scripts" / "flight" / "roster_role_key.py",
        base / "scripts" / "flight" / "roster_role_key.py",
    )
    payloads = [
        {
            "cwd": str(current),
            "stop_hook_active": False,
            "last_assistant_message": "plain",
        },
        {
            "cwd": str(current),
            "stop_hook_active": True,
            "last_assistant_message": "plain",
        },
        {
            "cwd": str(current),
            "stop_hook_active": False,
            "last_assistant_message": "Sigo esperando.",
        },
    ]
    for payload in payloads:
        current_payload = dict(payload)
        base_payload = dict(payload)
        base_payload["cwd"] = str(base)
        assert _run_hook(json.dumps(current_payload), current) == _run_hook(
            json.dumps(base_payload),
            base,
            base / ".agent" / "hooks" / "native_stop_hook.py",
        )
