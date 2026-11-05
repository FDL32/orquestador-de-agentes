"""Focused controls for the versioned 153z coordinator rotator."""

import inspect
import json
import math
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest


MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
APPROVED = "12345678-1234-1234-1234-123456789012"


def _record_payload(*, expires: str, max_duration: int = 12) -> dict[str, object]:
    text = (
        "AUTORIZO relevos CO-33 -> CO-34, cuando llegue a 330k de contexto, "
        "hasta las 2026-01-01T08:00:00+01:00"
    )
    from scripts.flight.verify_user_authorization import sha256_text

    return {
        "successors": ["CO-33", "CO-34"],
        "trigger_context_tokens": 330_000,
        "expires_at": expires,
        "literal_text": text,
        "message_id": MESSAGE_ID,
        "created_at": "2026-01-01T06:51:21.000Z",
        "text_sha256": sha256_text(text),
        "max_duration_hours": max_duration,
    }


def _write_snapshot(tmp_path: Path, *, expires: str) -> Path:
    path = tmp_path / "autorizacion_cadena.json"
    path.write_text(
        json.dumps(_record_payload(expires=expires), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _phase_a_record(tmp_path: Path):
    from scripts.flight.rotate_coordinator import load_chain_record

    return load_chain_record(tmp_path / "autorizacion_cadena.json")


def test_approved_by_has_no_prose_or_default() -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        validate_approved_by,
    )

    assert validate_approved_by(APPROVED) == APPROVED
    with pytest.raises(RotationRejectedError, match="approved-by-message-id-form"):
        validate_approved_by("supervisora CO-9 (sin objecion)")


def test_files_include_snapshot_and_dedicated_chain_ledger() -> None:
    from scripts.flight.rotate_coordinator import FILES

    assert "autorizacion_cadena.json" in FILES
    assert "autorizacion_cadena.ledger.jsonl" in FILES


def test_snapshot_rejects_malformed_json(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        load_chain_record,
    )

    path = tmp_path / "autorizacion_cadena.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RotationRejectedError, match="chain-authorization-unreadable"):
        load_chain_record(path)


def test_policy_allows_first_step_and_derives_counter_from_log(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import enforce_chain_policy
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T08:00:00+01:00")
    )
    log = tmp_path / "roster_changes.jsonl"
    now = datetime(2026, 1, 1, 6, 51, 22, tzinfo=timezone.utc)
    assert (
        enforce_chain_policy(record, log_path=log, now=now, message_id=MESSAGE_ID) == 1
    )


def test_policy_rejects_expired_window(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        enforce_chain_policy,
    )
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T08:00:00+01:00")
    )
    with pytest.raises(RotationRejectedError, match="chain-expired"):
        enforce_chain_policy(
            record,
            log_path=tmp_path / "roster_changes.jsonl",
            now=datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
            message_id=MESSAGE_ID,
        )


def test_policy_rejects_separation_anomaly(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        enforce_chain_policy,
    )
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T08:00:00+01:00")
    )
    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T06:51:21+00:00",
                "change": "chain_rotation_consumed",
                "messageId": MESSAGE_ID,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError, match="chain-separation-anomaly"):
        enforce_chain_policy(
            record,
            log_path=log,
            now=datetime(2026, 1, 1, 6, 55, tzinfo=timezone.utc),
            message_id=MESSAGE_ID,
        )


def test_policy_rejects_safety_cap(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        MAX_CHAIN_STEPS,
        RotationRejectedError,
        enforce_chain_policy,
    )
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T08:00:00+01:00")
    )
    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        "".join(
            json.dumps(
                {
                    "ts": f"2025-12-31T{idx:02d}:00:00+00:00",
                    "change": "chain_rotation_consumed",
                    "messageId": MESSAGE_ID,
                }
            )
            + "\n"
            for idx in range(MAX_CHAIN_STEPS)
        ),
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError, match="chain-step-limit"):
        enforce_chain_policy(
            record,
            log_path=log,
            now=datetime(2026, 1, 1, 6, 55, tzinfo=timezone.utc),
            message_id=MESSAGE_ID,
        )


def test_policy_requires_zoned_clock(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        enforce_chain_policy,
    )
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T08:00:00+01:00")
    )
    with pytest.raises(RotationRejectedError, match="now-zone-required"):
        enforce_chain_policy(
            record,
            log_path=tmp_path / "roster_changes.jsonl",
            now=datetime(2026, 1, 1, 7),
            message_id=MESSAGE_ID,
        )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"guard_rc": 3}, "roster-guard-failed"),
        ({"window_open": False}, "rotation-window-closed"),
        ({"quota_hard_pct": 97}, "quota-hard-stop"),
        ({"ack_age_seconds": 901}, "ack-timeout"),
    ],
)
def test_rotation_preconditions_fail_closed(
    kwargs: dict[str, object], reason: str
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        validate_rotation_preconditions,
    )

    base = {
        "guard_rc": 0,
        "window_open": True,
        "quota_hard_pct": 96.9,
        "ack_age_seconds": None,
    }
    base.update(kwargs)
    with pytest.raises(RotationRejectedError, match=reason):
        validate_rotation_preconditions(**base)


def test_phase_b_requires_measured_ack(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    with pytest.raises(RotationRejectedError, match="ack-unmeasured"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=None,
        )


def test_phase_a_rejects_approved_by_that_is_not_the_revalidated_message(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    request = type(
        "Request",
        (),
        {
            "approved_by": APPROVED,
            "actor": "CO-39",
            "out_code": "CO-33",
            "in_code": "CO-40",
            "out_thread": "mcp:11111111-1111-1111-1111-111111111111",
            "in_thread": "mcp:22222222-2222-2222-2222-222222222222",
            "reason": "test",
        },
    )()
    with pytest.raises(RotationRejectedError, match="chain-revalidation-rejected"):
        rotate_phase_a(
            tmp_path,
            request,
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 7, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
        )


def test_tests_leave_no_rotation_lock_in_repository_root() -> None:
    assert not (Path.cwd() / ".rotate_coordinator.lock").exists()


def test_policy_rejects_corrupt_append_only_log(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        chain_consumption_count,
    )

    log = tmp_path / "roster_changes.jsonl"
    log.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(RotationRejectedError, match="rotation-log-corrupt"):
        chain_consumption_count(log, MESSAGE_ID)


def test_main_requires_approved_by_and_message_proof() -> None:
    from scripts.flight.rotate_coordinator import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_real_user_message_id_is_never_fixture_authority() -> None:
    """The fixture UUID is synthetic and never one of the known real IDs."""
    known_real_id = "-".join(("482988f8", "af81", "4c37", "8f73", "d7b393803a76"))
    assert MESSAGE_ID not in {known_real_id}


def test_script_bootstrap_and_rehearsal_from_external_cwd(tmp_path: Path) -> None:
    script = Path(__file__).parents[2] / "scripts/flight/rotate_coordinator.py"
    flight = tmp_path / "flight"
    flight.mkdir()
    _phase_a_files(flight)
    _write_snapshot(flight, expires="2026-01-01T08:00:00+01:00")
    (flight / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    for name in ("autorizacion_cadena.ledger.jsonl",):
        (flight / name).touch(exist_ok=True)
    (flight / "autorizacion_cadena.ledger.jsonl.locks").mkdir()
    cwd = tmp_path / "external-cwd"
    cwd.mkdir()
    args = [
        sys.executable,
        str(script),
        "--fl-dir",
        str(flight),
        "--out-code",
        "CO-33",
        "--out-thread",
        _request().out_thread,
        "--in-code",
        "CO-34",
        "--in-thread",
        _request().in_thread,
        "--slot",
        "coordinadora-34",
        "--package",
        "tmp/fixture.md",
        "--actor",
        "CO-40",
        "--approved-by",
        MESSAGE_ID,
        "--reason",
        "rehearsal fixture",
        "--message-id",
        MESSAGE_ID,
        "--anchor-message-id",
        "22222222-2222-4222-8222-222222222222",
        "--store-path",
        str(tmp_path / "missing.sqlite"),
        "--guard-rc",
        "0",
        "--window-state",
        "open",
        "--quota-hard-pct",
        "50",
        "--apply-phase",
        "A",
        "--rehearsal",
    ]
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "store-missing" in output
    assert "ModuleNotFoundError" not in output
    negative = subprocess.run(
        [sys.executable, str(script), "--not-an-argument"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    negative_output = negative.stdout + negative.stderr
    assert negative.returncode != 0
    assert "ModuleNotFoundError" not in negative_output


def _request():
    from scripts.flight.rotate_coordinator import RotationRequest

    return RotationRequest(
        out_code="CO-33",
        out_thread="mcp:33333333-3333-4333-8333-333333333333",
        in_code="CO-34",
        in_thread="mcp:44444444-4444-4444-8444-444444444444",
        slot="coordinadora-34",
        package="tmp/ARRANQUE_CO-34.md",
        actor="CO-39",
        approved_by=MESSAGE_ID,
        reason="fixture sintetico",
    )


def _phase_b_files(
    tmp_path: Path, *, pending: bool = True
) -> tuple[Path, bytes, bytes]:
    roster = tmp_path / "flight_roster.json"
    roster.write_text(
        json.dumps(
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": _request().in_thread,
                        "session_code": "CO-34",
                        "predecessor_threadId": _request().out_thread,
                        "approved_by": MESSAGE_ID,
                        "version": 1,
                        "status": "active",
                        "estado": "PENDIENTE_ACK" if pending else "ACTIVO",
                    },
                    "supervisor": {
                        "threadId": "mcp:55555555-5555-4555-8555-555555555555",
                        "session_code": "CO-32",
                        "version": 1,
                        "status": "active",
                    },
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "session_registry.json"
    registry.write_text(
        json.dumps(
            {
                "orquestador_activo": "CO-34",
                "sessions": [{"code": "CO-34", "status": "ACTIVA (PENDIENTE_ACK)"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T06:51:21+00:00",
                "change": "chain_rotation_consumed",
                "messageId": MESSAGE_ID,
                "step": 1,
                "outCode": "CO-33",
                "inCode": "CO-34",
                "detail": "CO-33 -> CO-34",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return roster, roster.read_bytes(), log.read_bytes()


def _phase_a_files(tmp_path: Path) -> None:
    request = _request()
    roster = {
        "active_roles": {
            "orquestador": {
                "threadId": request.out_thread,
                "session_code": request.out_code,
                "version": 1,
                "status": "active",
                "estado": "ACTIVO",
            },
            "supervisor": {
                "threadId": "mcp:55555555-5555-4555-8555-555555555555",
                "session_code": "CO-32",
                "version": 1,
                "status": "active",
            },
        },
        "cadena_contexto": [],
    }
    (tmp_path / "flight_roster.json").write_text(
        json.dumps(roster, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "session_registry.json").write_text(
        json.dumps(
            {
                "orquestador_activo": request.out_code,
                "sessions": [
                    {
                        "code": request.out_code,
                        "role": "orquestadora",
                        "status": "ACTIVA",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "roster_changes.jsonl").write_text("", encoding="utf-8")


def test_phase_b_successful_activation(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    roster, _, _ = _phase_b_files(tmp_path)
    rotate_phase_b(
        tmp_path,
        _request(),
        decision=Decision(True, "authorized", message_id=MESSAGE_ID),
        guard_rc=0,
        window_open=True,
        quota_hard_pct=50,
        ack_age_seconds=0,
    )
    assert (
        json.loads(roster.read_text(encoding="utf-8"))["active_roles"]["orquestador"][
            "estado"
        ]
        == "ACTIVO"
    )
    registry = json.loads(
        (tmp_path / "session_registry.json").read_text(encoding="utf-8")
    )
    assert registry["sessions"][0]["status"] == "ACTIVA (ACK recibido)"
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


@pytest.mark.parametrize("phase", ["a", "b"])
def test_existing_flight_lock_rejects_both_phases_without_mutation(
    tmp_path: Path, phase: str
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        rotate_phase_a,
        rotate_phase_b,
    )
    from scripts.flight.verify_user_authorization import Decision

    if phase == "a":
        _phase_a_files(tmp_path)
        _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
        (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")

        def call() -> None:
            rotate_phase_a(
                tmp_path,
                _request(),
                message_id=MESSAGE_ID,
                now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
                decision=Decision(True, "authorized", message_id=MESSAGE_ID),
                guard_rc=0,
                window_open=True,
                quota_hard_pct=50,
            )

    else:
        _phase_b_files(tmp_path)

        def call() -> None:
            rotate_phase_b(
                tmp_path,
                _request(),
                decision=Decision(True, "authorized", message_id=MESSAGE_ID),
                guard_rc=0,
                window_open=True,
                quota_hard_pct=50,
                ack_age_seconds=0,
            )

    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    lock = tmp_path / ".rotate_coordinator.lock"
    lock.write_bytes(b"another rotator")
    with pytest.raises(RotationRejectedError, match="rotation-concurrent"):
        call()
    after = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert after == before | {lock: b"another rotator"}
    assert lock.read_bytes() == b"another rotator"
    if phase == "a":
        assert (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text() == ""


def test_flight_lock_is_removed_after_validation_rejection(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    with pytest.raises(RotationRejectedError, match="roster-guard-failed"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=3,
            window_open=True,
            quota_hard_pct=50,
        )
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_stale_lock_removal_procedure_allows_next_rotation(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    lock = tmp_path / ".rotate_coordinator.lock"
    lock.write_bytes(b"stale rotator after operator check")
    lock.unlink()
    rotate_phase_a(
        tmp_path,
        _request(),
        message_id=MESSAGE_ID,
        now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
        decision=Decision(True, "authorized", message_id=MESSAGE_ID),
        guard_rc=0,
        window_open=True,
        quota_hard_pct=50,
        record=_phase_a_record(tmp_path),
    )
    assert not lock.exists()


def test_flight_lock_cleanup_tolerates_missing_lock(
    monkeypatch, tmp_path: Path
) -> None:
    from scripts.flight.rotate_coordinator import _flight_exclusion

    original_unlink = Path.unlink

    def unlink_as_already_missing(path: Path, *args, **kwargs):
        if path.name == ".rotate_coordinator.lock":
            raise FileNotFoundError(path)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_as_already_missing)
    with _flight_exclusion(tmp_path):
        pass


def test_two_phase_a_threads_leave_one_completed_rotation(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    original = flight_roster_writer.write_role_estado

    def pause_first(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(flight_roster_writer, "write_role_estado", pause_first)
    results: list[object] = []

    def run() -> None:
        try:
            results.append(
                rotate_phase_a(
                    tmp_path,
                    _request(),
                    message_id=MESSAGE_ID,
                    now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
                    decision=Decision(True, "authorized", message_id=MESSAGE_ID),
                    guard_rc=0,
                    window_open=True,
                    quota_hard_pct=50,
                    record=_phase_a_record(tmp_path),
                )
            )
        except Exception as exc:  # pragma: no cover - asserted below
            results.append(exc)

    first = threading.Thread(target=run)
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=run)
    second.start()
    second.join(5)
    release.set()
    first.join(5)
    assert len(results) == 2
    assert sum(isinstance(item, int) for item in results) == 1
    assert (
        sum(
            isinstance(item, Exception) and "rotation-concurrent" in str(item)
            for item in results
        )
        == 1
    )
    assert (
        json.loads((tmp_path / "session_registry.json").read_text())[
            "orquestador_activo"
        ]
        == "CO-34"
    )
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_a_accepts_record_equal_to_disk_and_consumes(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    step = rotate_phase_a(
        tmp_path,
        _request(),
        message_id=MESSAGE_ID,
        now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
        decision=Decision(True, "authorized", message_id=MESSAGE_ID),
        guard_rc=0,
        window_open=True,
        quota_hard_pct=50,
        record=_phase_a_record(tmp_path),
    )
    assert step == 1
    roster = json.loads((tmp_path / "flight_roster.json").read_text(encoding="utf-8"))
    assert roster["active_roles"]["orquestador"]["threadId"] == _request().in_thread
    assert roster["active_roles"]["orquestador"]["session_code"] == "CO-34"
    assert roster["active_roles"]["orquestador"]["estado"] == "PENDIENTE_ACK"
    assert roster["active_roles"]["supervisor"]["session_code"] == "CO-33"
    rows = [
        json.loads(line)
        for line in (tmp_path / "roster_changes.jsonl").read_text().splitlines()
    ]
    consumed = [row for row in rows if row.get("change") == "chain_rotation_consumed"]
    assert (
        consumed[-1]["literal_text"]
        == _record_payload(expires="2026-01-01T08:00:00+01:00")["literal_text"]
    )


def test_phase_a_rejects_record_swapped_after_revalidation_without_consuming(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        RotationRequest,
        rotate_phase_a,
    )
    from scripts.flight.verify_user_authorization import (
        ChainAuthorizationRecord,
        Decision,
        sha256_text,
    )

    _phase_a_files(tmp_path)
    record_a = _record_payload(expires="2026-01-01T08:00:00+01:00")
    text_a = (
        "AUTORIZO relevos CO-33 -> CO-50, cuando llegue a 330k de contexto, "
        "hasta las 2026-01-01T08:00:00+01:00"
    )
    record_a.update(
        successors=["CO-33", "CO-50"],
        literal_text=text_a,
        text_sha256=sha256_text(text_a),
    )
    record_a_obj = ChainAuthorizationRecord.from_mapping(record_a)
    record_b = dict(record_a)
    record_b["successors"] = ["CO-33", "CO-50", "CO-51"]
    text_b = text_a.replace("CO-33 -> CO-50", "CO-33 -> CO-50 -> CO-51")
    record_b["literal_text"] = text_b
    record_b["text_sha256"] = sha256_text(text_b)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "autorizacion_cadena.json").write_text(
        json.dumps(record_a, indent=2) + "\n", encoding="utf-8"
    )
    request = RotationRequest(
        "CO-33",
        _request().out_thread,
        "CO-50",
        _request().in_thread,
        _request().slot,
        _request().package,
        _request().actor,
        MESSAGE_ID,
        _request().reason,
    )
    (tmp_path / "autorizacion_cadena.json").write_text(
        json.dumps(record_b, indent=2) + "\n", encoding="utf-8"
    )
    before = _mutable_bytes(tmp_path)
    with pytest.raises(RotationRejectedError, match="chain-record-changed"):
        rotate_phase_a(
            tmp_path,
            request,
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=record_a_obj,
        )
    assert _mutable_bytes(tmp_path) == before
    assert (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text() == ""


def test_phase_a_rejects_record_message_id_mismatch_without_consuming(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        rotate_phase_a,
    )
    from scripts.flight.verify_user_authorization import (
        ChainAuthorizationRecord,
        Decision,
    )

    _phase_a_files(tmp_path)
    record = _record_payload(expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    mismatched = dict(record)
    mismatched["message_id"] = "22222222-2222-4222-8222-222222222222"
    record_obj = ChainAuthorizationRecord.from_mapping(mismatched)
    before = _mutable_bytes(tmp_path)
    with pytest.raises(RotationRejectedError, match="chain-record-message-mismatch"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=record_obj,
        )
    assert _mutable_bytes(tmp_path) == before
    assert (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text() == ""


@pytest.mark.parametrize("record_kw", [{}, {"record": None}])
def test_phase_a_rejects_missing_record_without_consuming(
    tmp_path: Path, record_kw: dict[str, object]
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    ledger = tmp_path / "autorizacion_cadena.ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    before = _mutable_bytes(tmp_path)
    with pytest.raises(RotationRejectedError, match="chain-record-required"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            **record_kw,
        )
    assert _mutable_bytes(tmp_path) == before
    assert ledger.read_text() == ""
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_b_rolls_back_roster_and_log_when_registry_is_corrupt(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    roster, roster_before, log_before = _phase_b_files(tmp_path)
    (tmp_path / "session_registry.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        RotationRejectedError, match="session-registry-sessions-invalid"
    ):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert roster.read_bytes() == roster_before
    assert (tmp_path / "roster_changes.jsonl").read_bytes() == log_before
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_b_denied_without_phase_a_or_revalidation(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    _phase_b_files(tmp_path, pending=False)
    with pytest.raises(RotationRejectedError, match="phase-a-required"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )


def test_phase_b_rejects_other_message_and_roster_identity(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    roster, before, _ = _phase_b_files(tmp_path)
    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        json.dumps(
            {
                "change": "chain_rotation_consumed",
                "messageId": "22222222-2222-4222-8222-222222222222",
                "inCode": "CO-34",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError, match="phase-a-missing"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert roster.read_bytes() == before
    with pytest.raises(RotationRejectedError, match="phase-a-missing"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    changed = json.loads(roster.read_text(encoding="utf-8"))
    changed["active_roles"]["orquestador"]["threadId"] = (
        "mcp:66666666-6666-4666-8666-666666666666"
    )
    roster.write_text(json.dumps(changed) + "\n", encoding="utf-8")
    log.write_text(
        json.dumps(
            {
                "change": "chain_rotation_consumed",
                "messageId": MESSAGE_ID,
                "inCode": "CO-34",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError, match="phase-a-identity-mismatch"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    with pytest.raises(RotationRejectedError, match="chain-revalidation-rejected"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(False, "rejected", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )


def test_phase_b_rejects_roster_authorization_mismatch(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    roster, _, log_before = _phase_b_files(tmp_path)
    state = json.loads(roster.read_text(encoding="utf-8"))
    state["active_roles"]["orquestador"]["approved_by"] = (
        "22222222-2222-4222-8222-222222222222"
    )
    roster.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    roster_before = roster.read_bytes()
    registry = tmp_path / "session_registry.json"
    registry_before = registry.read_bytes()
    with pytest.raises(RotationRejectedError, match="phase-a-authorization-mismatch"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert roster.read_bytes() == roster_before
    assert registry.read_bytes() == registry_before
    assert (tmp_path / "roster_changes.jsonl").read_bytes() == log_before


@pytest.mark.parametrize(
    "registry_change",
    [
        {"sessions": []},
        {
            "sessions": [
                {"code": "CO-34", "status": "ACTIVA (PENDIENTE_ACK)"},
                {"code": "CO-34", "status": "duplicada"},
            ]
        },
        {
            "orquestador_activo": "CO-33",
            "sessions": [{"code": "CO-34", "status": "ACTIVA (PENDIENTE_ACK)"}],
        },
    ],
)
def test_phase_b_rejects_registry_identity_without_mutation(
    tmp_path: Path, registry_change: dict[str, object]
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    roster, _, log_before = _phase_b_files(tmp_path)
    registry = tmp_path / "session_registry.json"
    registry.write_text(json.dumps(registry_change) + "\n", encoding="utf-8")
    roster_before = roster.read_bytes()
    registry_before = registry.read_bytes()
    with pytest.raises(
        RotationRejectedError, match="session-registry-identity-mismatch"
    ):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert roster.read_bytes() == roster_before
    assert registry.read_bytes() == registry_before
    assert (tmp_path / "roster_changes.jsonl").read_bytes() == log_before


def test_phase_a_success_and_rollback_restore_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    (tmp_path / "roster_changes.jsonl").write_text("", encoding="utf-8")
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    ledger_path = tmp_path / "autorizacion_cadena.ledger.jsonl"
    ledger_path.write_text("", encoding="utf-8")
    request = _request()
    kwargs = {
        "message_id": MESSAGE_ID,
        "now": datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
        "decision": Decision(True, "authorized", message_id=MESSAGE_ID),
        "guard_rc": 0,
        "window_open": True,
        "quota_hard_pct": 50,
        "record": _phase_a_record(tmp_path),
    }
    rotate_phase_a(tmp_path, request, **kwargs)
    assert json.loads(ledger_path.read_text(encoding="utf-8"))
    assert not (tmp_path / ".rotate_coordinator.lock").exists()

    _phase_a_files(tmp_path)
    (tmp_path / "roster_changes.jsonl").write_text("", encoding="utf-8")
    ledger_path.write_text("", encoding="utf-8")
    for lock in (tmp_path / "autorizacion_cadena.ledger.jsonl.locks").glob("*.lock"):
        lock.unlink()
    before = {
        path: path.read_bytes()
        for path in (
            tmp_path / "flight_roster.json",
            tmp_path / "session_registry.json",
            tmp_path / "roster_changes.jsonl",
            ledger_path,
        )
    }
    monkeypatch.setattr(
        "scripts.flight.rotate_coordinator._rotate_registry",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("sessions")),
    )
    with pytest.raises(KeyError):
        rotate_phase_a(tmp_path, request, **kwargs)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not list(
        (tmp_path / "autorizacion_cadena.ledger.jsonl.locks").glob("*.lock")
    )


def test_rotation_preconditions_reject_nonfinite_and_negative_values() -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        validate_rotation_preconditions,
    )

    for quota in (math.nan, -1, 101):
        with pytest.raises(RotationRejectedError, match="quota-hard-invalid"):
            validate_rotation_preconditions(
                guard_rc=0, window_open=True, quota_hard_pct=quota
            )
    for ack in (math.nan, -5):
        with pytest.raises(RotationRejectedError, match="ack-age-invalid"):
            validate_rotation_preconditions(
                guard_rc=0,
                window_open=True,
                quota_hard_pct=50,
                ack_age_seconds=ack,
            )


def test_phase_precondition_parameters_have_no_permissive_defaults() -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_a, rotate_phase_b

    for function in (rotate_phase_a, rotate_phase_b):
        for name in ("guard_rc", "window_open", "quota_hard_pct"):
            assert (
                inspect.signature(function).parameters[name].default
                is inspect.Parameter.empty
            )


def _mutable_bytes(path: Path) -> dict[Path, bytes]:
    return {
        path / name: (path / name).read_bytes()
        for name in (
            "flight_roster.json",
            "session_registry.json",
            "roster_changes.jsonl",
        )
    }


def test_phase_a_requires_pending_orchestrator_without_mutation(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        _install_incoming_orchestrator,
    )

    _phase_a_files(tmp_path)
    before = _mutable_bytes(tmp_path)
    with pytest.raises(RotationRejectedError, match="phase-a-orchestrator-not-pending"):
        _install_incoming_orchestrator(
            tmp_path / "flight_roster.json",
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            changes_log_path=tmp_path / "roster_changes.jsonl",
        )
    assert _mutable_bytes(tmp_path) == before


def test_phase_a_rejects_consumed_step_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import ChainAuthorityLedger, Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    before = _mutable_bytes(tmp_path)
    monkeypatch.setattr(ChainAuthorityLedger, "consume", lambda *args: False)
    with pytest.raises(RotationRejectedError, match="chain-step-consumed"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before


def test_phase_b_rejects_missing_or_wrong_structured_entrant(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    for in_code in (None, "CO-35"):
        _phase_b_files(tmp_path)
        row = {
            "change": "chain_rotation_consumed",
            "messageId": MESSAGE_ID,
        }
        if in_code is not None:
            row["inCode"] = in_code
        (tmp_path / "roster_changes.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )
        before = _mutable_bytes(tmp_path)
        reason = (
            "phase-a-entrant-missing" if in_code is None else "phase-a-entrant-mismatch"
        )
        with pytest.raises(RotationRejectedError, match=reason):
            rotate_phase_b(
                tmp_path,
                _request(),
                decision=Decision(True, "authorized", message_id=MESSAGE_ID),
                guard_rc=0,
                window_open=True,
                quota_hard_pct=50,
                ack_age_seconds=0,
            )
        assert _mutable_bytes(tmp_path) == before


def test_phase_a_rejects_existing_incoming_session_without_mutation(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    registry = json.loads((tmp_path / "session_registry.json").read_text())
    registry["sessions"].append({"code": "CO-34"})
    (tmp_path / "session_registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    before = _mutable_bytes(tmp_path)
    with pytest.raises(
        RotationRejectedError, match="incoming-session-already-registered"
    ):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("missing", "session-registry-unreadable"),
        ("[]", "session-registry-invalid"),
    ],
)
def test_registry_loader_rejects_invalid_shapes(
    tmp_path: Path, payload: str, reason: str
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, _load_registry

    path = tmp_path / "session_registry.json"
    if payload == "missing":
        path = tmp_path / "absent.json"
    else:
        path.write_text(payload, encoding="utf-8")
    with pytest.raises(RotationRejectedError, match=reason):
        _load_registry(path)


@pytest.mark.parametrize(
    ("sessions", "reason"),
    [
        ([1], "session-registry-session-invalid"),
        ("bad", "session-registry-sessions-invalid"),
    ],
)
def test_phase_a_registry_shape_rejected_before_save(
    tmp_path: Path, sessions: object, reason: str
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        _rotate_registry,
    )

    registry = tmp_path / "session_registry.json"
    registry.write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    before = registry.read_bytes()
    with pytest.raises(RotationRejectedError, match=reason):
        _rotate_registry(registry, _request(), "2026-01-01T06:52:00+00:00")
    assert registry.read_bytes() == before


def test_roster_form_rejections_preserve_files(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        _install_incoming_orchestrator,
    )

    for roster in (
        {},
        {"active_roles": {}},
        {
            "active_roles": {
                "orquestador": {"estado": "PENDIENTE_ACK", "version": "bad"}
            }
        },
    ):
        _phase_a_files(tmp_path)
        (tmp_path / "flight_roster.json").write_text(
            json.dumps(roster), encoding="utf-8"
        )
        before = _mutable_bytes(tmp_path)
        reason = (
            "roster-active-roles-invalid"
            if "active_roles" not in roster
            else "roster-.*-invalid"
            if "orquestador" not in roster["active_roles"]
            else "roster-orchestrator-version-invalid"
        )
        with pytest.raises(RotationRejectedError, match=reason):
            _install_incoming_orchestrator(
                tmp_path / "flight_roster.json",
                _request(),
                message_id=MESSAGE_ID,
                now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
                changes_log_path=tmp_path / "roster_changes.jsonl",
            )
        assert _mutable_bytes(tmp_path) == before


def test_invalid_guard_and_window_types_are_rejected() -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        validate_rotation_preconditions,
    )

    with pytest.raises(RotationRejectedError, match="roster-guard-invalid"):
        validate_rotation_preconditions(
            guard_rc="0", window_open=True, quota_hard_pct=50
        )
    with pytest.raises(RotationRejectedError, match="rotation-window-invalid"):
        validate_rotation_preconditions(
            guard_rc=0, window_open="open", quota_hard_pct=50
        )


@pytest.mark.parametrize(
    ("ts", "reason"),
    [
        ("not-a-time", "rotation-log-timestamp-invalid"),
        ("2026-01-01T06:52:00", "rotation-log-timestamp-zone-required"),
    ],
)
def test_invalid_log_timestamps_are_rejected(
    tmp_path: Path, ts: str, reason: str
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        _last_chain_timestamp,
    )

    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        json.dumps(
            {"change": "chain_rotation_consumed", "messageId": MESSAGE_ID, "ts": ts}
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError, match=reason):
        _last_chain_timestamp(log, MESSAGE_ID)


def test_non_string_log_timestamp_has_exact_invalid_reason(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        _last_chain_timestamp,
    )

    log = tmp_path / "roster_changes.jsonl"
    log.write_text(
        json.dumps(
            {"change": "chain_rotation_consumed", "messageId": MESSAGE_ID, "ts": 123}
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RotationRejectedError) as exc_info:
        _last_chain_timestamp(log, MESSAGE_ID)
    assert exc_info.value.args == ("rotation-log-timestamp-invalid",)


def test_invalid_registered_window_is_rejected(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        enforce_chain_policy,
    )
    from scripts.flight.verify_user_authorization import ChainAuthorizationRecord

    record = ChainAuthorizationRecord.from_mapping(
        _record_payload(expires="2026-01-01T06:51:21+00:00")
    )
    with pytest.raises(
        RotationRejectedError, match="chain-expiry-not-after-created-at"
    ):
        enforce_chain_policy(
            record,
            log_path=tmp_path / "log",
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            message_id=MESSAGE_ID,
        )


def test_structural_chain_records_are_rejected_with_stable_reason(
    tmp_path: Path,
) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        load_chain_record,
    )

    path = tmp_path / "record.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RotationRejectedError) as exc_info:
        load_chain_record(path)
    assert exc_info.value.args == ("chain-authorization-unreadable",)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RotationRejectedError, match="successors-invalid"):
        load_chain_record(path)


def test_malformed_chain_record_is_unreadable_with_exact_reason(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import (
        RotationRejectedError,
        load_chain_record,
    )

    path = tmp_path / "record.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RotationRejectedError) as exc_info:
        load_chain_record(path)
    assert exc_info.value.args == ("chain-authorization-unreadable",)


def test_rehearsal_missing_required_file_is_rejected(tmp_path: Path) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, _copy_rehearsal

    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(
        RotationRejectedError, match=r"rehearsal-missing-flight_roster\.json"
    ):
        _copy_rehearsal(tmp_path)


def test_main_rejects_missing_phase(monkeypatch, tmp_path: Path, capsys) -> None:
    import scripts.flight.rotate_coordinator as module
    from scripts.flight.verify_user_authorization import Decision

    monkeypatch.setattr(module, "load_chain_record", lambda path: object())
    monkeypatch.setattr(
        module,
        "revalidate_from_store",
        lambda *args, **kwargs: Decision(True, "authorized", message_id=MESSAGE_ID),
    )
    rc = module.main(
        [
            "--fl-dir",
            str(tmp_path),
            "--out-code",
            "CO-33",
            "--out-thread",
            _request().out_thread,
            "--in-code",
            "CO-34",
            "--in-thread",
            _request().in_thread,
            "--slot",
            "slot",
            "--package",
            "pkg",
            "--actor",
            "CO-40",
            "--approved-by",
            MESSAGE_ID,
            "--reason",
            "reason",
            "--message-id",
            MESSAGE_ID,
            "--anchor-message-id",
            MESSAGE_ID,
            "--store-path",
            str(tmp_path / "store"),
            "--guard-rc",
            "0",
            "--window-state",
            "open",
            "--quota-hard-pct",
            "50",
        ]
    )
    assert rc == 10
    assert "phase-required" in capsys.readouterr().out


def test_main_passes_revalidated_record_and_rejects_swap(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import scripts.flight.rotate_coordinator as module
    from scripts.flight.verify_user_authorization import Decision, sha256_text

    _phase_a_files(tmp_path)
    record_a = _record_payload(expires="2026-01-01T08:00:00+01:00")
    record_b = dict(record_a)
    record_b["successors"] = ["CO-33", "CO-50"]
    text_b = record_b["literal_text"].replace("CO-33 -> CO-34", "CO-33 -> CO-50")
    record_b["literal_text"] = text_b
    record_b["text_sha256"] = sha256_text(text_b)
    (tmp_path / "autorizacion_cadena.json").write_text(
        json.dumps(record_a, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    before = _mutable_bytes(tmp_path)

    def revalidate_and_swap(*args, **kwargs):
        (tmp_path / "autorizacion_cadena.json").write_text(
            json.dumps(record_b, indent=2) + "\n", encoding="utf-8"
        )
        return Decision(True, "authorized", message_id=MESSAGE_ID)

    monkeypatch.setattr(module, "revalidate_from_store", revalidate_and_swap)
    rc = module.main(
        [
            "--fl-dir",
            str(tmp_path),
            "--out-code",
            "CO-33",
            "--out-thread",
            _request().out_thread,
            "--in-code",
            "CO-34",
            "--in-thread",
            _request().in_thread,
            "--slot",
            "slot",
            "--package",
            "pkg",
            "--actor",
            "CO-40",
            "--approved-by",
            MESSAGE_ID,
            "--reason",
            "reason",
            "--message-id",
            MESSAGE_ID,
            "--anchor-message-id",
            MESSAGE_ID,
            "--store-path",
            str(tmp_path / "store"),
            "--guard-rc",
            "0",
            "--window-state",
            "open",
            "--quota-hard-pct",
            "50",
            "--apply-phase",
            "A",
        ]
    )
    assert rc == 10
    assert "chain-record-changed" in capsys.readouterr().out
    assert _mutable_bytes(tmp_path) == before
    assert (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text() == ""

    positive = tmp_path / "positive"
    positive.mkdir()
    _phase_a_files(positive)
    (positive / "autorizacion_cadena.json").write_text(
        json.dumps(record_a, indent=2) + "\n", encoding="utf-8"
    )
    (positive / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    seen: list[object] = []

    def phase_a_spy(*args, **kwargs):
        seen.append(kwargs["record"])
        return 1

    monkeypatch.setattr(
        module,
        "revalidate_from_store",
        lambda *a, **k: Decision(True, "authorized", message_id=MESSAGE_ID),
    )
    monkeypatch.setattr(module, "rotate_phase_a", phase_a_spy)
    assert (
        module.main(
            [
                "--fl-dir",
                str(positive),
                "--out-code",
                "CO-33",
                "--out-thread",
                _request().out_thread,
                "--in-code",
                "CO-34",
                "--in-thread",
                _request().in_thread,
                "--slot",
                "slot",
                "--package",
                "pkg",
                "--actor",
                "CO-40",
                "--approved-by",
                MESSAGE_ID,
                "--reason",
                "reason",
                "--message-id",
                MESSAGE_ID,
                "--anchor-message-id",
                MESSAGE_ID,
                "--store-path",
                str(positive / "store"),
                "--guard-rc",
                "0",
                "--window-state",
                "open",
                "--quota-hard-pct",
                "50",
                "--apply-phase",
                "A",
            ]
        )
        == 0
    )
    assert seen and seen[0].message_id == MESSAGE_ID


@pytest.mark.parametrize(
    ("out_code", "in_code", "successors", "authorized"),
    [
        ("CO-33", "CO-34", ["CO-33", "CO-34"], True),
        ("CO-33", "CO-99", ["CO-33", "CO-34"], False),
        ("CO-33", "CO-35", ["CO-33", "CO-34", "CO-35"], False),
        ("CO-35", "CO-34", ["CO-33", "CO-34", "CO-35"], False),
    ],
)
def test_phase_a_enforces_consecutive_authorized_pair(
    tmp_path: Path,
    out_code: str,
    in_code: str,
    successors: list[str],
    authorized: bool,
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    request = _request().__class__(
        **{**_request().__dict__, "out_code": out_code, "in_code": in_code}
    )
    _phase_a_files(tmp_path)
    payload = _record_payload(expires="2026-01-01T08:00:00+01:00")
    payload["successors"] = successors
    (tmp_path / "autorizacion_cadena.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    before = _mutable_bytes(tmp_path)
    call = dict(
        message_id=MESSAGE_ID,
        now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
        decision=Decision(True, "authorized", message_id=MESSAGE_ID),
        guard_rc=0,
        window_open=True,
        quota_hard_pct=50,
        record=_phase_a_record(tmp_path),
    )
    if authorized:
        assert rotate_phase_a(tmp_path, request, **call) == 1
        return
    with pytest.raises(RotationRejectedError, match="chain-pair-not-authorized"):
        rotate_phase_a(tmp_path, request, **call)
    assert _mutable_bytes(tmp_path) == before


def test_phase_a_false_consumption_preserves_foreign_write(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import ChainAuthorityLedger, Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")

    def foreign_consume(self, *args):
        with (tmp_path / "roster_changes.jsonl").open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write('{"change":"OTHER_RUN_MARKER"}\n')
        return False

    monkeypatch.setattr(ChainAuthorityLedger, "consume", foreign_consume)
    with pytest.raises(RotationRejectedError, match="chain-step-consumed"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert b"OTHER_RUN_MARKER" in (tmp_path / "roster_changes.jsonl").read_bytes()


def test_main_emits_urgent_separation_alert_to_stubbed_notifier(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import scripts.flight.rotate_coordinator as module
    from scripts.flight.verify_user_authorization import Decision

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(module, "load_chain_record", lambda path: object())
    monkeypatch.setattr(
        module,
        "revalidate_from_store",
        lambda *args, **kwargs: Decision(True, "authorized", message_id=MESSAGE_ID),
    )
    monkeypatch.setattr(
        module,
        "rotate_phase_a",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            module.RotationRejectedError("chain-separation-anomaly")
        ),
    )
    monkeypatch.setattr(module.comms_alert, "configure", lambda path: path)
    monkeypatch.setattr(
        module.comms_alert,
        "event",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    rc = module.main(
        [
            "--fl-dir",
            str(tmp_path),
            "--out-code",
            "CO-33",
            "--out-thread",
            _request().out_thread,
            "--in-code",
            "CO-34",
            "--in-thread",
            _request().in_thread,
            "--slot",
            "co-34",
            "--package",
            "fixture",
            "--actor",
            "CO-40",
            "--approved-by",
            MESSAGE_ID,
            "--reason",
            "fixture",
            "--message-id",
            MESSAGE_ID,
            "--anchor-message-id",
            MESSAGE_ID,
            "--store-path",
            str(tmp_path / "store.sqlite"),
            "--ops-dir",
            str(tmp_path / "ops"),
            "--guard-rc",
            "0",
            "--window-state",
            "open",
            "--quota-hard-pct",
            "50",
            "--apply-phase",
            "A",
        ]
    )
    assert rc == 10
    assert calls and calls[0][0][:2] == ("relevo-separacion", "URGENTE")
    assert "URGENTE relevo-separacion rc_aviso=0" in capsys.readouterr().out


@pytest.mark.parametrize(
    "mutation",
    [
        "roster-code",
        "roster-thread",
        "registry-active",
        "missing-session",
        "duplicate-session",
    ],
)
def test_phase_a_rejects_non_installed_outgoing_identity(
    tmp_path: Path, mutation: str
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    roster = json.loads((tmp_path / "flight_roster.json").read_text(encoding="utf-8"))
    registry = json.loads(
        (tmp_path / "session_registry.json").read_text(encoding="utf-8")
    )
    if mutation == "roster-code":
        roster["active_roles"]["orquestador"]["session_code"] = "CO-77"
    elif mutation == "roster-thread":
        roster["active_roles"]["orquestador"]["threadId"] = (
            "mcp:00000000-0000-0000-0000-000000000077"
        )
    elif mutation == "registry-active":
        registry["orquestador_activo"] = "CO-77"
    elif mutation == "missing-session":
        registry["sessions"] = []
    else:
        registry["sessions"].append(dict(registry["sessions"][0]))
    (tmp_path / "flight_roster.json").write_text(
        json.dumps(roster) + "\n", encoding="utf-8"
    )
    (tmp_path / "session_registry.json").write_text(
        json.dumps(registry) + "\n", encoding="utf-8"
    )
    before = _mutable_bytes(tmp_path)
    with pytest.raises(
        RotationRejectedError, match="phase-a-outgoing-identity-mismatch"
    ):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before
    assert not (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text()


def test_phase_a_rejects_unreadable_outgoing_roster_without_consuming(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    before = _mutable_bytes(tmp_path)
    monkeypatch.setattr(
        flight_roster_writer,
        "_read_roster",
        lambda path: (_ for _ in ()).throw(OSError("roster unreadable")),
    )
    with pytest.raises(
        RotationRejectedError, match="phase-a-outgoing-identity-mismatch"
    ):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before
    assert not (tmp_path / "autorizacion_cadena.ledger.jsonl").read_text()


@pytest.mark.parametrize("target", ["log", "roster"])
def test_phase_a_consume_raise_preserves_foreign_write(
    tmp_path: Path, monkeypatch, target: str
) -> None:
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import ChainAuthorityLedger, Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")

    def consume_with_foreign_write(self, *args):
        if target == "log":
            with (tmp_path / "roster_changes.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write('{"change":"OTHER_RUN_MARKER"}\n')
        else:
            roster = json.loads((tmp_path / "flight_roster.json").read_text())
            roster["OTHER_RUN_MARKER"] = True
            (tmp_path / "flight_roster.json").write_text(json.dumps(roster) + "\n")
        raise OSError("foreign write during consume")

    monkeypatch.setattr(ChainAuthorityLedger, "consume", consume_with_foreign_write)
    with pytest.raises(RotationRejectedError, match="rollback-conflict"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert (
        b"OTHER_RUN_MARKER"
        in (
            tmp_path
            / ("roster_changes.jsonl" if target == "log" else "flight_roster.json")
        ).read_bytes()
    )
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_a_writer_failure_preserves_unowned_changes(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    original = flight_roster_writer.write_role_estado

    before = _mutable_bytes(tmp_path)

    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("writer failed after own partial write")

    monkeypatch.setattr(flight_roster_writer, "write_role_estado", write_then_fail)
    with pytest.raises(OSError, match="own partial write"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_b_writer_failure_preserves_unowned_changes(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    _phase_b_files(tmp_path)
    original = flight_roster_writer.write_role_estado

    before = _mutable_bytes(tmp_path)

    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("phase B writer failed after own partial write")

    monkeypatch.setattr(flight_roster_writer, "write_role_estado", write_then_fail)
    with pytest.raises(OSError, match="own partial write"):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert _mutable_bytes(tmp_path) == before
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_b_external_write_is_conflict_and_lock_is_removed(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_b
    from scripts.flight.verify_user_authorization import Decision

    _phase_b_files(tmp_path)
    original = flight_roster_writer.write_role_estado

    def write_then_external(*args, **kwargs):
        original(*args, **kwargs)
        (tmp_path / "session_registry.json").write_bytes(b"OTHER_RUN_MARKER\n")
        raise OSError("phase B writer failed with external change")

    monkeypatch.setattr(flight_roster_writer, "write_role_estado", write_then_external)
    with pytest.raises(
        RotationRejectedError, match=r"rollback-conflict:session_registry\.json"
    ):
        rotate_phase_b(
            tmp_path,
            _request(),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            ack_age_seconds=0,
        )
    assert (tmp_path / "session_registry.json").read_bytes() == b"OTHER_RUN_MARKER\n"
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_a_log_failure_preserves_unowned_changes(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts.flight.rotate_coordinator import rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")

    before = _mutable_bytes(tmp_path)

    def append_then_fail(path, **kwargs):
        path.write_bytes(path.read_bytes() + b"partial write\n")
        raise OSError("log writer failed after own partial write")

    monkeypatch.setattr(
        "scripts.flight.rotate_coordinator._append_rotation_log", append_then_fail
    )
    with pytest.raises(OSError, match="own partial write"):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert _mutable_bytes(tmp_path) == before
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_phase_a_external_write_outside_owned_operation_is_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.flight_roster_writer as flight_roster_writer
    from scripts.flight.rotate_coordinator import RotationRejectedError, rotate_phase_a
    from scripts.flight.verify_user_authorization import Decision

    _phase_a_files(tmp_path)
    _write_snapshot(tmp_path, expires="2026-01-01T08:00:00+01:00")
    (tmp_path / "autorizacion_cadena.ledger.jsonl").write_text("", encoding="utf-8")
    original = flight_roster_writer.write_role_estado

    def write_then_external(*args, **kwargs):
        original(*args, **kwargs)
        (tmp_path / "session_registry.json").write_bytes(b"OTHER_RUN_MARKER\n")
        raise OSError("writer failed with external change")

    monkeypatch.setattr(flight_roster_writer, "write_role_estado", write_then_external)
    with pytest.raises(
        RotationRejectedError, match=r"rollback-conflict:session_registry\.json"
    ):
        rotate_phase_a(
            tmp_path,
            _request(),
            message_id=MESSAGE_ID,
            now=datetime(2026, 1, 1, 6, 52, tzinfo=timezone.utc),
            decision=Decision(True, "authorized", message_id=MESSAGE_ID),
            guard_rc=0,
            window_open=True,
            quota_hard_pct=50,
            record=_phase_a_record(tmp_path),
        )
    assert (tmp_path / "session_registry.json").read_bytes() == b"OTHER_RUN_MARKER\n"
    assert not (tmp_path / ".rotate_coordinator.lock").exists()


def test_process_recovery_keeps_consumed_ledger_step(tmp_path: Path) -> None:
    from scripts.flight.verify_user_authorization import ChainAuthorityLedger

    ledger_path = tmp_path / "autorizacion_cadena.ledger.jsonl"
    ledger = ChainAuthorityLedger(ledger_path)
    assert ledger.consume(MESSAGE_ID, 1, "CO-33", "CO-34")
    restore_names = (
        "flight_roster.json",
        "session_registry.json",
        "roster_changes.jsonl",
        "autorizacion_cadena.json",
    )
    for name in restore_names:
        path = tmp_path / name
        path.write_bytes(b"changed")
        path.write_bytes(b"restored-from-pre_rotate")
    assert not ledger.consume(MESSAGE_ID, 1, "CO-33", "CO-34")
