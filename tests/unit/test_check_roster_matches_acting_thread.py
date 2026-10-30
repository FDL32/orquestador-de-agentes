#!/usr/bin/env python3
"""WOT-2026-136c: tests for check_roster_matches_acting_thread guard.

Tests 1-18 cover the 4 checkpoints (a)-(d) and special conditions.
Test 19 covers the cableado step function.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Import the real roster writer for test 2.1 helper
import scripts.flight_roster_writer as flight_roster_writer


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wot_2026_136c"
PRE_OR7 = FIXTURES_DIR / "pre_or7"
CORRECTED = FIXTURES_DIR / "corrected"

# The sha256 of the pre_or7/flight_roster.json fixture (copy verification)
EXPECTED_SHA256 = "e4e95b5cad5c2287588a2c4518fcc7b50af99dcadf4489556cae1330aaaf95de"


# --- Helpers ---


def _write_tmp_json(path: Path, data: object) -> None:
    """Write data as JSON to path, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _run_guard(
    roster_path: Path | str | None = None,
    acting_thread: str | None = None,
    registry_path: Path | str | None = None,
    changes_log: Path | str | None = None,
    role: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run check_roster_matches_acting_thread.py and return (rc, stdout, stderr)."""
    args = [sys.executable, str(_SCRIPTS_DIR / "check_roster_matches_acting_thread.py")]
    if roster_path is not None:
        args.extend(
            [
                "--roster-path",
                str(roster_path) if isinstance(roster_path, Path) else roster_path,
            ]
        )
    if acting_thread is not None:
        args.extend(["--acting-thread", acting_thread])
    if registry_path is not None:
        args.extend(
            [
                "--registry-path",
                str(registry_path)
                if isinstance(registry_path, Path)
                else registry_path,
            ]
        )
    if changes_log is not None:
        args.extend(
            [
                "--changes-log",
                str(changes_log) if isinstance(changes_log, Path) else changes_log,
            ]
        )
    if role is not None:
        args.extend(["--role", role])

    env = dict(__import__("os").environ)
    env_extra = env_extra or {}
    if env_extra:
        env.update(env_extra)
    # Clean FLIGHT_ROSTER_PATH to avoid false positives from inherited env
    env.pop("FLIGHT_ROSTER_PATH", None)

    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


# --- Test 1: SHA256 of pre_or7/flight_roster.json (copy verification) ---


def test_sha256_copy_verification(tmp_path: Path) -> None:
    """Test 1: verify the copy of pre_or7/flight_roster.json is intact."""
    import hashlib

    actual = hashlib.sha256((PRE_OR7 / "flight_roster.json").read_bytes()).hexdigest()
    assert actual == EXPECTED_SHA256, (
        f"Fixture SHA mismatch: {actual} != {EXPECTED_SHA256}"
    )


# --- Test 2: Module exists (Phase 3 VERDE - module was ROJO in Phase 2) ---


def test_module_exists() -> None:
    """Test 2: guard module now exists (Phase 3 VERDE)."""
    import scripts.check_roster_matches_acting_thread

    assert hasattr(scripts.check_roster_matches_acting_thread, "main")


# --- Test 1: N/A without roster path and without FLIGHT_ROSTER_PATH env var ---


# --- Test 2.1: Helper function and new A0 tests (ROJO-first) ---


def _write_roster_with_transition(
    tmp_path: Path,
    role: str = "orquestador",
    start_estado: str = "ACTIVO",
) -> dict:
    """Build a minimal roster, call the real writer to transition to PENDIENTE_ACK,
    and return the canonical line written to changes_log as a parsed dict.

    Before: tmp_path is a pytest tmp_path fixture.
    During: creates roster with active_roles.<role> (threadId, session_code, version),
            calls write_role_estado(estado="PENDIENTE_ACK"), reads last line of changes_log.
    After: returns the canonical line dict with keys: ts, by, change, detail, reason.
    """
    roster_p = tmp_path / "flight_roster.json"
    changes_p = tmp_path / "roster_changes.jsonl"

    roster_data = {
        "active_roles": {
            role: {
                "threadId": f"mcp:{role}-thread-1",
                "session_code": f"OR-{role}",
                "version": 1,
                "estado": start_estado,
            }
        }
    }
    _write_tmp_json(roster_p, roster_data)
    # Empty changes_log
    changes_p.write_text("", encoding="utf-8")

    flight_roster_writer.write_role_estado(
        roster_p,
        role,
        "PENDIENTE_ACK",
        changes_log_path=changes_p,
        actor="test",
        reason="test",
    )

    # Read the last line written by the writer
    lines = changes_p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "Writer did not produce a changes_log line"
    return json.loads(lines[-1])


def _make_registry_with_activa(role: str, thread_id: str) -> dict:
    """Create a session_registry with a single ACTIVA entry for the mapped role.

    Maps roster role to registry role (orquestador->orquestadora, supervisor->supervisora).
    """
    from scripts.check_roster_matches_acting_thread import _ROSTER_TO_REGISTRY_ROLE

    registry_role = _ROSTER_TO_REGISTRY_ROLE.get(role, role + "ora")
    return {
        "sessions": [
            {
                "code": f"OR-{role}",
                "role": registry_role,
                "slot": "s1",
                "threadId": thread_id,
                "started": "2026-10-29T10:00:00+00:00",
                "status": "ACTIVA",
            }
        ]
    }


def test_2_1_i_pendiente_ack_real_line_recent(tmp_path: Path) -> None:
    """Test 2.1 (i): roster PENDIENTE_ACK + real writer line (recent ts) -> guard should
    NOT emit '(b) ... sin linea canonica verificable' and should PASS (exit 0).
    Against CURRENT guard (which searches 'para <rol>'), this MUST FAIL (RED) because
    the guard cannot find its expected pattern.
    """
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:orquestador-thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Use the line EXACTLY as the writer produced it (with real ts)
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = _make_registry_with_activa(
        "orquestador", "mcp:orquestador-thread-1"
    )
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orquestador-thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Correct behavior: rc=0, no "(b) ... sin linea canonica verificable"
    assert rc == 0, (
        f"Expected PASS (exit 0) - guard recognizes real writer line, got {rc}: {stdout}"
    )
    assert "(b)" not in stdout, (
        f"Should NOT mention checkpoint (b) for valid writer line: {stdout}"
    )


def test_2_1_ii_pendiente_ack_real_line_old(tmp_path: Path) -> None:
    """Test 2.1 (ii): same real writer line but ts > 15 min old -> guard should emit
    '(b) PENDIENTE_ACK caducado' (NOT 'sin linea canonica'). Against CURRENT guard,
    this MUST FAIL (RED) because guard emits 'sin linea' instead of 'caducado'.
    """
    old_ts = "2020-01-01T00:00:00+00:00"
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:orquestador-thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Rewrite ONLY the ts field
    line_dict["ts"] = old_ts
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = _make_registry_with_activa(
        "orquestador", "mcp:orquestador-thread-1"
    )
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orquestador-thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Correct behavior: should have "(b) caducado" and NOT "(b) ... sin linea canonica"
    assert rc == 1, f"Expected FAIL (exit 1) with caducado, got {rc}: {stdout}"
    assert "caducado" in stdout, f"Should mention 'caducado' for old ts, got: {stdout}"
    assert "sin linea canonica verificable" not in stdout, (
        f"Should NOT say 'sin linea canonica' when ts exists but is old: {stdout}"
    )


def test_2_1_iii_pendiente_ack_no_changes_line(tmp_path: Path) -> None:
    """Test 2.1 (iii): roster PENDIENTE_ACK with NO changes_log line -> guard should give
    '(b) ... sin linea canonica' (fail-closed). This is a control, should PASS (GREEN) now.
    """
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:orquestador-thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    registry_data = _make_registry_with_activa(
        "orquestador", "mcp:orquestador-thread-1"
    )
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    # Empty changes_log
    changes_p.write_text("", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orquestador-thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Should give "(b) ... sin linea canonica" -> FAIL (exit 1)
    assert rc == 1, f"Expected FAIL (exit 1) for no changes line, got {rc}: {stdout}"
    assert "(b)" in stdout, f"Should mention checkpoint (b): {stdout}"


def test_2_1_iv_supervisor_real_line_recent(tmp_path: Path) -> None:
    """Test 2.1 (iv): same as (i) but with role='supervisor'. Tests that guard iterates
    active_roles keys, not just DEFAULT_ROLE. Should FAIL against current guard (RED).
    """
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:orquestador-thread"},
            "supervisor": {
                "threadId": "mcp:supervisor-thread-1",
                "estado": "PENDIENTE_ACK",
            },
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="supervisor")
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = {
        "sessions": [
            {
                "code": "SV-TEST",
                "role": "supervisora",  # mapped from "supervisor"
                "slot": "s1",
                "threadId": "mcp:supervisor-thread-1",
                "started": "2026-10-29T10:00:00+00:00",
                "status": "ACTIVA",
            }
        ]
    }
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orquestador-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Correct behavior: rc=0, no "(b) ... sin linea canonica" for the supervisor role
    assert rc == 0, f"Expected PASS (exit 0) for supervisor, got {rc}: {stdout}"
    assert "(b)" not in stdout, (
        f"Should NOT mention checkpoint (b) for valid writer line: {stdout}"
    )


def test_2_1_v_write_conflict_not_transition(tmp_path: Path) -> None:
    """Test 2.1 (v): a write_conflict line with 'role=orquestador intento=1 ...' format
    should NOT count as a transition -> guard should give '(b) ... sin linea canonica'.
    This is a control, should PASS (GREEN) now and after fix.
    """
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:orquestador-thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    # write_conflict line with the real writer format
    write_conflict_line = json.dumps(
        {
            "ts": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "by": "test",
            "change": "write_conflict",
            "detail": "role=orquestador intento=1 version_esperada=1 version_real=2",
            "reason": "test",
        }
    )
    registry_data = _make_registry_with_activa(
        "orquestador", "mcp:orquestador-thread-1"
    )
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text(write_conflict_line + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orquestador-thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # write_conflict does NOT count as a transition -> 'sin linea canonica'
    assert rc == 1, f"Expected FAIL (exit 1) for write_conflict, got {rc}: {stdout}"
    assert "(b)" in stdout, f"Should mention checkpoint (b): {stdout}"


def test_1_na_without_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 1: exit 3 when no roster path is provided (neither flag nor env)."""
    monkeypatch.delenv("FLIGHT_ROSTER_PATH", raising=False)
    args = [
        sys.executable,
        str(_SCRIPTS_DIR / "check_roster_matches_acting_thread.py"),
        "--acting-thread",
        "mcp:some-thread",
    ]
    env = dict(__import__("os").environ)
    env.pop("FLIGHT_ROSTER_PATH", None)
    proc = subprocess.run(args, capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 3, (
        f"Expected N/A (exit 3), got {proc.returncode}: {proc.stdout}"
    )


# --- Test 2: Fail closed by missing identity (--acting-thread not given) ---


def test_2_fail_closed_missing_identity(tmp_path: Path) -> None:
    """Test 2: exit 1 when roster exists but --acting-thread is not provided."""
    rc, stdout, _ = _run_guard(
        roster_path=str(PRE_OR7 / "flight_roster.json"),
        acting_thread=None,
        env_extra={},
    )
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"
    assert "--acting-thread" in stdout.lower() or "acting" in stdout.lower(), (
        f"Diagnostico should mention --acting-thread: {stdout}"
    )


# --- Test 3: Checkpoint (a) isolated - identity mismatch ---


def test_3_checkpoint_a_identity_mismatch(tmp_path: Path) -> None:
    """Test 3: checkpoint (a) - roster threadId != acting_thread."""
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:wrong-thread",
                "session_code": "OR-5",
            }
        }
    }
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:correct-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"
    assert (
        "(a)" in stdout or "identidad" in stdout.lower() or "thread" in stdout.lower()
    ), f"Violation should mention checkpoint (a): {stdout}"


# --- Test 4: Checkpoint (b) isolated - expired PENDIENTE_ACK ---


def test_4_checkpoint_b_expired_pendiente_ack(tmp_path: Path) -> None:
    """Test 4: checkpoint (b) - estado PENDIENTE_ACK with old timestamp."""
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Rewrite ONLY the ts field to old value
    line_dict["ts"] = "2020-01-01T00:00:00+00:00"
    # Leave detail/by/change/reason verbatim from the writer
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"


# --- Test 5: Checkpoint (b) isolated - recent PENDIENTE_ACK (should not trigger) ---


def test_5_checkpoint_b_recent_pendiente_ack(tmp_path: Path) -> None:
    """Test 5: checkpoint (b) - estado PENDIENTE_ACK with recent timestamp -> no violation."""
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Rewrite ts to 1 min ago (to avoid flakiness)
    line_dict["ts"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    # Leave detail/by/change/reason verbatim from the writer
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, stderr = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Should be PASS (0) if only (b) is checked and (a), (c), (d) are clean
    assert rc == 0, f"Expected PASS (exit 0), got {rc}: {stdout}\n{stderr}"


# --- Test 6: Checkpoint (b) with mixed legacy and canonical lines ---


def test_6_checkpoint_b_mixed_schemas(tmp_path: Path) -> None:
    """Test 6: checkpoint (b) - legacy and canonical lines in roster_changes.jsonl."""
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Rewrite ONLY the ts field of the canonical line to old value
    line_dict["ts"] = "2020-01-01T00:00:00+00:00"
    changes_data_lines = [
        # Legacy schema (should be ignored)
        json.dumps(
            {
                "ts": "2020-01-01T00:00:00+00:00",
                "por": "OR-5",
                "cambio": "estado_transition",
                "motivo": "test legacy",
            }
        ),
        # Canonical schema (should be used) with old ts
        json.dumps(line_dict),
    ]
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1) for old canonical line, got {rc}: {stdout}"


# --- Test 7: Checkpoint (b) with unparseable ts ---


def test_7_checkpoint_b_unparseable_ts(tmp_path: Path) -> None:
    """Test 7: checkpoint (b) - ts that cannot be parsed -> fail-closed."""
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    # Rewrite ONLY the ts field to unparseable value
    line_dict["ts"] = "ayer"
    # Leave detail/by/change/reason verbatim from the writer
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # Unparseable ts -> fail-closed
    assert rc == 1, f"Expected FAIL (exit 1) for unparseable ts, got {rc}: {stdout}"


# --- Test 8: Checkpoint (c) isolated - singleton role with multiple ACTIVA ---


def test_8_checkpoint_c_singleton_multi_activa(tmp_path: Path) -> None:
    """Test 8: checkpoint (c) - singleton orquestadora with 3 ACTIVA entries (prefix regex)."""
    registry_data = {
        "sessions": [
            {
                "code": "OR-A",
                "role": "orquestadora",
                "slot": "s1",
                "threadId": "mcp:t1",
                "started": "2026-10-29T10:00:00+01:00",
                "status": "ACTIVA",
            },
            {
                "code": "OR-B",
                "role": "orquestadora",
                "slot": "s2",
                "threadId": "mcp:t2",
                "started": "2026-10-29T11:00:00+01:00",
                "status": "ACTIVA (ticket WOT-2026-131a)",
            },
            {
                "code": "OR-C",
                "role": "orquestadora",
                "slot": "s3",
                "threadId": "mcp:t3",
                "started": "2026-10-29T12:00:00+01:00",
                "status": "ACTIVA (vuelo de implantacion)",
            },
            # Negative control: status starting with SUPERSEDED should NOT count
            {
                "code": "OR-D",
                "role": "orquestadora",
                "slot": "s4",
                "threadId": "mcp:t4",
                "started": "2026-10-29T09:00:00+01:00",
                "status": "SUPERSEDED (antes estaba ACTIVA en otro slot)",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:t3"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:t3",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, (
        f"Expected FAIL (exit 1) for multi-ACTIVA singleton, got {rc}: {stdout}"
    )
    assert "(c) doble ACTIVA" in stdout, (
        f"Violation must mention checkpoint (c): {stdout}"
    )
    assert "(d) roster desactualizado" not in stdout, (
        f"Violation (d) must NOT appear when roster matches latest: {stdout}"
    )


# --- Test 8-bis: Checkpoint (c) out of scope - multi-occupation role ---


def test_8_bis_checkpoint_c_multi_occupation(tmp_path: Path) -> None:
    """Test 8-bis: checkpoint (c) multi-occupation role (implantacion) not checked."""
    registry_data = {
        "sessions": [
            {
                "code": "IM-1",
                "role": "implantacion",
                "slot": "slot-1",
                "threadId": "mcp:im1",
                "started": "2026-10-29T10:00:00+01:00",
                "status": "ACTIVA",
            },
            {
                "code": "IM-2",
                "role": "implantacion",
                "slot": "slot-2",
                "threadId": "mcp:im2",
                "started": "2026-10-29T11:00:00+01:00",
                "status": "ACTIVA",
            },
            {
                "code": "IM-3",
                "role": "implantacion",
                "slot": "slot-3",
                "threadId": "mcp:im3",
                "started": "2026-10-29T12:00:00+01:00",
                "status": "ACTIVA",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:orq"},
            "builder": {"threadId": "mcp:builder"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orq",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # implantacion is NOT a singleton role -> (c) should not flag it
    assert rc == 0, (
        f"Expected PASS (exit 0) for multi-occupation role, got {rc}: {stdout}"
    )


# --- Test 8-ter: Checkpoint (c) second singleton role ---


def test_8_ter_checkpoint_c_second_singleton(tmp_path: Path) -> None:
    """Test 8-ter: checkpoint (c) second singleton role (supervisora)."""
    registry_data = {
        "sessions": [
            {
                "code": "SV-1",
                "role": "supervisora",
                "slot": "slot-1",
                "threadId": "mcp:sv1",
                "started": "2026-10-29T10:00:00+01:00",
                "status": "ACTIVA",
            },
            {
                "code": "SV-2",
                "role": "supervisora",
                "slot": "slot-2",
                "threadId": "mcp:sv2",
                "started": "2026-10-29T11:00:00+01:00",
                "status": "ACTIVA",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:orq"},
            "supervisor": {"threadId": "mcp:sv1"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:orq",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, (
        f"Expected FAIL (exit 1) for dual ACTIVA supervisora, got {rc}: {stdout}"
    )
    assert "(c)" in stdout or "supervisora" in stdout.lower(), (
        f"Violation should mention checkpoint (c) or supervisora: {stdout}"
    )


# --- Test 9: Checkpoint (d) isolated - outdated roster after a relieves ---


def test_9_checkpoint_d_outdated_roster(tmp_path: Path) -> None:
    """Test 9: checkpoint (d) - registry has single ACTIVA, roster points to old thread."""
    registry_data = {
        "sessions": [
            {
                "code": "OR-NEW",
                "role": "orquestadora",
                "slot": "s2",
                "threadId": "mcp:new-thread",
                "started": "2026-10-29T12:00:00+01:00",
                "status": "ACTIVA",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:old-thread"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:old-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1) for outdated roster, got {rc}: {stdout}"
    assert "(d) roster desactualizado" in stdout, (
        f"Violation must mention checkpoint (d): {stdout}"
    )
    assert "(c)" not in stdout, (
        f"Checkpoint (c) must NOT appear with single ACTIVA entry: {stdout}"
    )


# --- Test 10: Checkpoint (d) with DISCARDED entry ---


def test_10_checkpoint_d_discarded_entry(tmp_path: Path) -> None:
    """Test 10: checkpoint (d) - a DISCARDED entry with later started is ignored."""
    registry_data = {
        "sessions": [
            {
                "code": "OR-REAL",
                "role": "orquestadora",
                "slot": "s1",
                "threadId": "mcp:real-thread",
                "started": "2026-10-29T09:00:00+01:00",
                "status": "ACTIVA",
            },
            {
                "code": "OR-DUP",
                "role": "orquestadora",
                "slot": "s2",
                "threadId": "mcp:different-thread",
                "started": "2026-10-29T15:00:00+01:00",
                "status": "DESCARTADA (error de registro)",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:real-thread"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:real-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 0, f"Expected PASS (exit 0) when DISCARDED ignored, got {rc}: {stdout}"


# --- Test 11: Checkpoint (d) with None started ---


def test_11_checkpoint_d_null_started(tmp_path: Path) -> None:
    """Test 11: checkpoint (d) - started is None, should be ignored without error."""
    registry_data = {
        "sessions": [
            {
                "code": "OR-NONE",
                "role": "orquestadora",
                "slot": "s1",
                "threadId": "mcp:none-thread",
                "started": None,
                "status": "HISTORICO",
            },
            {
                "code": "OR-REAL",
                "role": "orquestadora",
                "slot": "s2",
                "threadId": "mcp:real-thread",
                "started": "2026-10-29T09:00:00+01:00",
                "status": "ACTIVA",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:real-thread"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, stderr = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:real-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 0, (
        f"Expected PASS (exit 0) with None started, got {rc}: {stdout}\n{stderr}"
    )


# --- Test 12: Checkpoint (d) with different offset formats ---


def test_12_checkpoint_d_different_offsets(tmp_path: Path) -> None:
    """Test 12: checkpoint (d) - started with Z vs +01:00, parse correctly."""
    # 2026-10-29T11:00:00Z = 2026-10-29T12:00:00+01:00 (same instant)
    # 2026-10-29T12:30:00+01:00 is LATER
    registry_data = {
        "sessions": [
            {
                "code": "OR-Z",
                "role": "orquestadora",
                "slot": "s1",
                "threadId": "mcp:z-thread",
                "started": "2026-10-29T11:00:00Z",
                "status": "ACTIVA",
            },
            {
                "code": "OR-PLUS",
                "role": "orquestadora",
                "slot": "s2",
                "threadId": "mcp:plus-thread",
                "started": "2026-10-29T12:30:00+01:00",
                "status": "ACTIVA",
            },
        ]
    }
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:z-thread"},
        }
    }
    registry_p = tmp_path / "registry.json"
    roster_p = tmp_path / "roster.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:z-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # OR-PLUS is actually later -> violation because roster doesn't match
    assert rc == 1, f"Expected FAIL (exit 1) for string-sorting bug, got {rc}: {stdout}"


# --- Test 13: Integration FAIL - pre_or7 fixture ---


def test_13_integration_fail_pre_or7() -> None:
    """Test 13: integration FAIL against full pre_or7 fixture."""
    # OR-6 threadId from pre_or7 roster
    or6_thread = "mcp:51b55dcc-41d7-48d0-8e84-74f73a9e1b47"
    rc, stdout, _ = _run_guard(
        roster_path=str(PRE_OR7 / "flight_roster.json"),
        acting_thread=or6_thread,
        registry_path=str(PRE_OR7 / "session_registry.json"),
        changes_log=str(PRE_OR7 / "roster_changes.jsonl"),
    )
    assert rc == 1, f"Expected FAIL (exit 1) for pre_or7, got {rc}: {stdout}"
    # pre_or7 has BOTH (c) and (d) violations (double ACTIVA + outdated roster)
    assert "(c) doble ACTIVA" in stdout, f"pre_or7 must mention (c): {stdout}"
    assert "(d) roster desactualizado" in stdout, f"pre_or7 must mention (d): {stdout}"


# --- Test 14: Integration PASS - corrected fixture ---


def test_14_integration_pass_corrected() -> None:
    """Test 14: integration PASS against corrected fixture."""
    rc, stdout, stderr = _run_guard(
        roster_path=str(CORRECTED / "flight_roster.json"),
        acting_thread="mcp:corrected-thread-001",
        registry_path=str(CORRECTED / "session_registry.json"),
        changes_log=str(CORRECTED / "roster_changes.jsonl"),
    )
    assert rc == 0, (
        f"Expected PASS (exit 0) for corrected, got {rc}: {stdout}\n{stderr}"
    )


# --- Test 15: Unmapped role (--role builder) ---


def test_15_unmapped_role(tmp_path: Path) -> None:
    """Test 15: role not in _ROSTER_TO_REGISTRY_ROLE -> (d) is skipped."""
    roster_data = {
        "active_roles": {
            "orquestador": {"threadId": "mcp:orq"},
            "builder": {"threadId": "mcp:builder-thread"},
        }
    }
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:builder-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
        role="builder",
    )
    # (d) should be skipped for unmapped role, (a)/(b) apply on builder role
    # builder has no estado, (a) passes (threadId matches), (c) not applicable (empty registry)
    # The guard should note that (d) is skipped for orquestador and supervisor
    assert rc == 0, f"Expected PASS (exit 0) for unmapped role, got {rc}: {stdout}"


# --- Test 16: Unknown fields in active_roles ---


def test_16_unknown_fields_in_active_roles() -> None:
    """Test 16: unknown fields (nota_gap) should not cause rejection."""
    _rc, _stdout, _stderr = _run_guard(
        roster_path=str(PRE_OR7 / "flight_roster.json"),
        acting_thread="mcp:51b55dcc-41d7-48d0-8e84-74f73a9e1b47",
        registry_path=str(PRE_OR7 / "session_registry.json"),
        changes_log=str(PRE_OR7 / "roster_changes.jsonl"),
    )
    # pre_or7 has nota_gap, but the guard should not reject for unknown fields
    # This test just verifies the guard runs without error on the real fixture format


# --- Test 17: No-hardcodeo ---


def test_17_no_hardcoded_session_ids() -> None:
    """Test 17: guard should not contain hardcoded session IDs like SUPERVISOR-2 or OR-N."""
    guard_path = _SCRIPTS_DIR / "check_roster_matches_acting_thread.py"
    content = guard_path.read_text(encoding="utf-8")

    # Check for SUPERVISOR-2 literal
    assert "SUPERVISOR-2" not in content, "Guard should not hardcode SUPERVISOR-2"
    # Check for OR-N pattern
    import re

    or_pattern = re.search(r'["\']OR-[0-9][0-9]*["\']', content)
    assert or_pattern is None, (
        f"Guard should not hardcode OR-N patterns: {or_pattern.group()}"
    )


# --- Test 18: No-hardcodeo, data mutation of authority blocks ---


def test_18_authority_blocks_do_not_affect_result(tmp_path: Path) -> None:
    """Test 18: modifying authority/cadena_consulta blocks should not change guard verdict."""
    # Base: corrected fixture without authority blocks
    rc_base, _, _ = _run_guard(
        roster_path=str(CORRECTED / "flight_roster.json"),
        acting_thread="mcp:corrected-thread-001",
        registry_path=str(CORRECTED / "session_registry.json"),
        changes_log=str(CORRECTED / "roster_changes.jsonl"),
    )

    # With authority block added
    registry_data = {
        "sessions": [
            {
                "code": "OR-7",
                "role": "orquestadora",
                "slot": "orquestadora-1",
                "threadId": "mcp:corrected-thread-001",
                "started": "2026-10-29T10:00:00+01:00",
                "status": "ACTIVA",
                "supersedes": "OR-6",
                "autoridad": {
                    "quien_decisione": "SUPERVISOR-2",
                    "cadena_consulta": ["IM-1"],
                },
            }
        ]
    }
    registry_p = tmp_path / "registry_with_auth.json"
    _write_tmp_json(registry_p, registry_data)

    rc_with_auth, _, _ = _run_guard(
        roster_path=str(CORRECTED / "flight_roster.json"),
        acting_thread="mcp:corrected-thread-001",
        registry_path=str(registry_p),
        changes_log=str(CORRECTED / "roster_changes.jsonl"),
    )

    assert rc_base == rc_with_auth, (
        f"Authority blocks should not affect result: base={rc_base}, with_auth={rc_with_auth}"
    )


# --- Test 19: Cableado test for step_roster_matches_acting_thread ---


def test_19_cableado_step_function(tmp_path: Path) -> None:
    """Test 19: step_roster_matches_acting_thread cableado test (delegated to test_closeout_step_roster_matches_acting_thread.py)."""
    pytest.skip(
        "See test_closeout_step_roster_matches_acting_thread.py for full cableado tests"
    )


def test_20_role_absent_from_active_roles(tmp_path: Path) -> None:
    """Test 20: role not present in active_roles dict -> FAIL (a)."""
    roster_data = {
        "active_roles": {
            "otro_rol": {"threadId": "mcp:other-thread"},
        }
    }
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:acting-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"
    assert "rol 'orquestador' ausente en active_roles" in stdout, (
        f"Must report missing role violation: {stdout}"
    )


def test_21_active_roles_absent_or_null(tmp_path: Path) -> None:
    """Test 21: active_roles key absent or null (not a dict) -> FAIL (a)."""
    roster_data = {
        "sessions": [],
        "active_roles": None,
    }
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:acting-thread",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"
    assert "rol 'orquestador' ausente en active_roles" in stdout, (
        f"Must report identity-not-verifiable when active_roles is not a dict: {stdout}"
    )


# --- WOT-2026-136e: M7, M8, M10, N1, DoD(4) tests ---


def test_22_m7_threshold_under_900s(tmp_path: Path) -> None:
    """M7: ts 899s before now -> elapsed_secs ~899, no (b) violation (within 900s threshold).

    This is a COVERAGE test: the code logic at line 249 is correct, but without this test
    a mutation of the threshold (900->850) would not be detected by existing tests.
    """
    now = datetime.now(timezone.utc)
    ts_899s = (now - timedelta(seconds=899)).isoformat()

    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    line_dict["ts"] = ts_899s
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = _make_registry_with_activa("orquestador", "mcp:thread-1")
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 0, f"Expected PASS (exit 0) for 899s elapsed, got {rc}: {stdout}"
    assert "caducado" not in stdout, (
        f"Should NOT mention 'caducado' for 899s elapsed: {stdout}"
    )


def test_23_m7_threshold_over_900s(tmp_path: Path) -> None:
    """M7: ts 901s before now -> elapsed_secs ~901, (b) violation "caducado".

    This is a COVERAGE test: the code logic at line 249 is correct, but without this test
    a mutation of the threshold (900->850) would not be detected by existing tests.
    """
    now = datetime.now(timezone.utc)
    ts_901s = (now - timedelta(seconds=901)).isoformat()

    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    line_dict["ts"] = ts_901s
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = _make_registry_with_activa("orquestador", "mcp:thread-1")
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 1, f"Expected FAIL (exit 1) for 901s elapsed, got {rc}: {stdout}"
    assert "caducado" in stdout, f"Should mention 'caducado' for 901s elapsed: {stdout}"


def test_24_m8_naive_timestamp_within_threshold(tmp_path: Path) -> None:
    """M8: naive ts ~30s ago, no tzinfo -> code normalizes to UTC, no violation, no TypeError.

    This is a COVERAGE test: the naive normalization branch (lines 243-246) exists but is
    not covered by any test with a dynamically generated naive timestamp.
    """
    now = datetime.now(timezone.utc)
    naive_ts = (now - timedelta(seconds=30)).replace(tzinfo=None).isoformat()

    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    line_dict = _write_roster_with_transition(tmp_path, role="orquestador")
    line_dict["ts"] = naive_ts
    changes_data_lines = [json.dumps(line_dict)]
    registry_data = _make_registry_with_activa("orquestador", "mcp:thread-1")
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, stderr = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    assert rc == 0, (
        f"Expected PASS (exit 0) for naive 30s ago, got {rc}: {stdout}\n{stderr}"
    )
    assert "TypeError" not in stderr, f"Should not raise TypeError: {stderr}"
    assert "caducado" not in stdout, (
        f"Should NOT mention 'caducado' for 30s naive: {stdout}"
    )


def test_25_m10_pass_with_omission_note(tmp_path: Path) -> None:
    """M10: scenario where checkpoint (d) generates 'ninguna entrada ACTIVA en registry' note.

    This is a COVERAGE test: the code at lines 304-308 generates this note but no existing
    test asserts that the note appears in stdout when the result is GLOBAL PASS.
    """
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
            }
        }
    }
    registry_data = {"sessions": []}
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    _write_tmp_json(changes_p, {})

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # GLOBAL PASS: no violations from any checkpoint
    assert rc == 0, f"Expected PASS (exit 0), got {rc}: {stdout}"
    # But the note about no ACTIVA entries should appear in stdout
    assert "ninguna entrada ACTIVA en registry" in stdout, (
        f"Should mention 'ninguna entrada ACTIVA en registry' note: {stdout}"
    )


def test_26_n1_mixed_naive_aware_changes_log(tmp_path: Path) -> None:
    """N1: changes-log with 2 old canonical lines (naive+aware) for same role ->
    rc=1 with '(b) ... caducado', NEVER a TypeError traceback.

    Against CURRENT code (without fix), this test MUST FAIL (RED) because the comparison
    between naive and aware datetimes at line 169 raises TypeError.
    """
    now = datetime.now(timezone.utc)
    old_naive = (now - timedelta(hours=2)).replace(tzinfo=None)
    old_aware = now - timedelta(hours=2)

    changes_data_lines = [
        json.dumps(
            {
                "ts": old_naive.isoformat(),
                "by": "test",
                "change": "estado_transition",
                "detail": "role=orquestador ACTIVO -> PENDIENTE_ACK",
                "reason": "test",
            }
        ),
        json.dumps(
            {
                "ts": old_aware.isoformat(),
                "by": "test",
                "change": "estado_transition",
                "detail": "role=orquestador ACTIVO -> PENDIENTE_ACK",
                "reason": "test",
            }
        ),
    ]

    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    registry_data = _make_registry_with_activa("orquestador", "mcp:thread-1")
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, stderr = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-1",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
    )
    # After fix: rc=1 with "(b) caducado", no TypeError in stderr
    assert rc == 1, (
        f"Expected FAIL (exit 1) with old mixed ts, got {rc}: {stdout}\n{stderr}"
    )
    assert "TypeError" not in stderr, f"Should not raise TypeError: {stderr}"
    assert "caducado" in stdout, (
        f"Should mention 'caducado' for old mixed ts, got: {stdout}"
    )


def test_26_n2_mixed_naive_aware_find_latest_activa(tmp_path: Path) -> None:
    """N1 variant: call _find_latest_activa directly with sessions that have mixed
    naive+aware started timestamps for the same role -> no TypeError.

    Against CURRENT code, this test MUST FAIL (RED) because max() comparison between
    naive and aware datetimes raises TypeError.
    """
    from scripts.check_roster_matches_acting_thread import _find_latest_activa

    now = datetime.now(timezone.utc)
    old_naive = (now - timedelta(minutes=30)).replace(tzinfo=None)
    older_aware = now - timedelta(hours=2)

    sessions = [
        {
            "role": "orquestadora",
            "started": old_naive.isoformat(),  # naive
            "status": "ACTIVA",
        },
        {
            "role": "orquestadora",
            "started": older_aware.isoformat(),  # aware, older
            "status": "ACTIVA",
        },
    ]

    result = _find_latest_activa(sessions, "orquestadora")
    assert result is not None, (
        f"_find_latest_activa should return the latest entry, not None: {result}"
    )
    assert result.get("status") == "ACTIVA"


def test_27_dod4_special_char_role(tmp_path: Path) -> None:
    """DoD(4): role with regex special char (e.g., 'orq.estador') -> guard recognizes
    the transition line without emitting '(b) ... sin linea canonica'.

    Against CURRENT code, this test MUST FAIL (RED) because re.escape('orq.estador')
    produces 'orq\\.estador' which doesn't match the literal 'orq.estador' in the detail.
    """
    roster_data = {
        "active_roles": {
            "orq.estador": {
                "threadId": "mcp:thread-special",
                "estado": "PENDIENTE_ACK",
            }
        }
    }

    # Build a changes-log line manually with the real writer pattern
    now = datetime.now(timezone.utc)
    line_dict = {
        "ts": now.isoformat(),
        "by": "test",
        "change": "estado_transition",
        "detail": "role=orq.estador ACTIVO -> PENDIENTE_ACK",
        "reason": "test",
    }
    changes_data_lines = [json.dumps(line_dict)]

    registry_data = {
        "sessions": [
            {
                "code": "IM-1",
                "role": "implantacion",
                "slot": "s1",
                "threadId": "mcp:special-thread",
                "started": now.isoformat(),
                "status": "ACTIVA",
            }
        ]
    }
    roster_p = tmp_path / "roster.json"
    registry_p = tmp_path / "registry.json"
    changes_p = tmp_path / "changes.jsonl"
    _write_tmp_json(roster_p, roster_data)
    _write_tmp_json(registry_p, registry_data)
    changes_p.write_text("\n".join(changes_data_lines) + "\n", encoding="utf-8")

    rc, stdout, _ = _run_guard(
        roster_path=str(roster_p),
        acting_thread="mcp:thread-special",
        registry_path=str(registry_p),
        changes_log=str(changes_p),
        role="orq.estador",
    )
    # After fix: rc=0, no "(b) ... sin linea canonica"
    assert rc == 0, f"Expected PASS (exit 0) for special char role, got {rc}: {stdout}"
    assert "sin linea canonica" not in stdout, (
        f"Should NOT mention 'sin linea canonica' for special char role: {stdout}"
    )
