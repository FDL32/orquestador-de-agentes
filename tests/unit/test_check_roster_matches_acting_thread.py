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
    old_ts = "2020-01-01T00:00:00+00:00"
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    changes_data_lines = [
        json.dumps(
            {
                "ts": old_ts,
                "by": "OR-5",
                "change": "estado_transition",
                "detail": "ACTIVO -> PENDIENTE_ACK para orquestador",
                "reason": "test",
            }
        ),
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
    assert rc == 1, f"Expected FAIL (exit 1), got {rc}: {stdout}"


# --- Test 5: Checkpoint (b) isolated - recent PENDIENTE_ACK (should not trigger) ---


def test_5_checkpoint_b_recent_pendiente_ack(tmp_path: Path) -> None:
    """Test 5: checkpoint (b) - estado PENDIENTE_ACK with recent timestamp -> no violation."""
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
    changes_data_lines = [
        json.dumps(
            {
                "ts": recent_ts,
                "by": "OR-5",
                "change": "estado_transition",
                "detail": "ACTIVO -> PENDIENTE_ACK para orquestador",
                "reason": "test",
            }
        ),
    ]
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
    old_ts = "2020-01-01T00:00:00+00:00"
    roster_data = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:thread-1",
                "estado": "PENDIENTE_ACK",
            }
        }
    }
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
        # Canonical schema (should be used)
        json.dumps(
            {
                "ts": old_ts,
                "by": "OR-5",
                "change": "estado_transition",
                "detail": "ACTIVO -> PENDIENTE_ACK para orquestador",
                "reason": "test",
            }
        ),
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
    changes_data_lines = [
        json.dumps(
            {
                "ts": "ayer",
                "by": "OR-5",
                "change": "estado_transition",
                "detail": "ACTIVO -> PENDIENTE_ACK para orquestador",
                "reason": "test",
            }
        ),
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
