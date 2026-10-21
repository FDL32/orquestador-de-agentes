"""Tests for `scripts/cloud_session_ledger.py` (cloud handoff ledger)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "cloud_session_ledger.py"
    spec = importlib.util.spec_from_file_location("cloud_session_ledger", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(module, ledger, **overrides):
    values = {
        "task_id": "task-1",
        "session_id": "session_abc",
        "url": "https://claude.ai/code/session_abc",
        "commit": "abc123",
        "branch": "cloud/task-1",
        "model": "sonnet",
        "auth_method": "oauth",
        "bundle_sha": "deadbeef" * 8,
    }
    values.update(overrides)
    return module.record(ledger, **values)


def test_record_is_idempotent_by_task_and_bundle_sha(tmp_path):
    ledger = tmp_path / "cloud_sessions.jsonl"
    module = _load_module()

    assert _record(module, ledger) == 0
    assert _record(module, ledger) == 0

    records = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    recorded = [r for r in records if r.get("event") == "recorded"]
    assert len(recorded) == 1
    assert recorded[0]["status"] == "RUNNING"


def test_record_without_session_id_is_pending(tmp_path):
    ledger = tmp_path / "cloud_sessions.jsonl"
    module = _load_module()

    assert _record(module, ledger, session_id="") == 0
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "LAUNCHED_PENDING_ID"


def test_update_and_list(tmp_path, capsys):
    ledger = tmp_path / "cloud_sessions.jsonl"
    module = _load_module()

    assert _record(module, ledger) == 0
    assert (
        module.update(
            ledger,
            task_id="task-1",
            status="AWAITING_REVIEW",
            result_ref="branch",
            note="",
        )
        == 0
    )
    capsys.readouterr()  # descarta los [OK] de record/update
    assert module.list_sessions(ledger, ttl_minutes=120) == 0

    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["task_id"] == "task-1"
    assert rows[0]["status"] == "AWAITING_REVIEW"
    assert rows[0]["session_id"] == "session_abc"


def test_update_rejects_invalid_status(tmp_path, capsys):
    ledger = tmp_path / "cloud_sessions.jsonl"
    module = _load_module()

    assert (
        module.update(ledger, task_id="task-1", status="DONE", result_ref="", note="")
        == 2
    )
    assert "status invalido" in capsys.readouterr().err


def test_sweep_marks_orphan_on_ttl(tmp_path):
    ledger = tmp_path / "cloud_sessions.jsonl"
    module = _load_module()

    module._append(
        ledger,
        {
            "ts": "2020-01-01T00:00:00+00:00",
            "event": "recorded",
            "task_id": "old-task",
            "session_id": "session_old",
            "status": "RUNNING",
            "bundle_sha": "x" * 64,
        },
    )
    assert module.sweep(ledger, ttl_minutes=1) == 0

    records = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["task_id"] == "old-task"
    assert records[-1]["status"] == "ORPHANED"
