"""Tests for the real coordinator rotation copy.

The fixtures are intentionally small, local, and created in each test so the
rehearsal never reads the live flight directory.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "flight"
    / "rotate_coordinator_real.py"
)
MOTOR_ROOT = Path(__file__).resolve().parents[2]
FILES = ("flight_roster.json", "session_registry.json", "roster_changes.jsonl")


def _load_module():
    """Load the delivered module through importlib.

    Before: the delivered module exists at MODULE_PATH.
    During: creates an importlib module specification and executes it.
    After: returns the loaded module object.
    """
    spec = importlib.util.spec_from_file_location(
        "rotate_coordinator_real", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: object) -> None:
    """Write a canonical UTF-8 JSON fixture.

    Before: path is inside a temporary fixture directory.
    During: serializes data with the formatting required by the rotator.
    After: writes one final newline and no carriage returns.
    """
    path.write_bytes(
        (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )


def _make_fixtures(tmp_path: Path) -> Path:
    """Create minimal valid roster, registry, and change-log fixtures.

    Before: tmp_path is an isolated pytest temporary directory.
    During: builds distinct outgoing/incoming identities and matching registry data.
    After: returns a flight-directory path suitable for --fl-dir.
    """
    fl_dir = tmp_path / "fixtures"
    fl_dir.mkdir()
    out_thread = "mcp:faa4a4cd-6d32-4bb1-a936-ee99a5925c39"
    in_thread = "mcp:00000000-0000-0000-0000-00000000c011"
    supervisor_thread = "mcp:supervisor-thread"
    _write_json(
        fl_dir / "flight_roster.json",
        {
            "active_roles": {
                "orquestador": {
                    "threadId": out_thread,
                    "session_code": "CO-10",
                    "since": "2026-10-28T10:00:00+00:00",
                    "set_by": "fixture",
                    "predecessor_threadId": supervisor_thread,
                    "version": 1,
                    "status": "active",
                    "approved_by": "fixture",
                    "estado": "ACTIVO",
                },
                "supervisor": {
                    "threadId": supervisor_thread,
                    "session_code": "SUP-1",
                    "since": "2026-10-28T10:00:00+00:00",
                    "set_by": "fixture",
                    "predecessor_threadId": None,
                    "version": 1,
                    "status": "active",
                    "approved_by": "fixture",
                },
            },
            "cadena_contexto": [],
        },
    )
    _write_json(
        fl_dir / "session_registry.json",
        {
            "autoridad": {"owner": "fixture"},
            "orquestador_activo": "CO-10",
            "cadena_consulta": {
                "desde_orquestador": [],
                "latidos_en_cascada": "fixture",
            },
            "sessions": [
                {
                    "code": "CO-10",
                    "role": "orquestadora",
                    "slot": "coordinadora-10",
                    "threadId": out_thread,
                    "started": "2026-10-28T10:00:00+00:00",
                    "status": "ACTIVA",
                },
                {
                    "code": "SUP-1",
                    "role": "supervisora",
                    "slot": "supervisora-1",
                    "threadId": supervisor_thread,
                    "started": "2026-10-28T10:00:00+00:00",
                    "status": "ACTIVA",
                },
                {
                    "code": "CO-11",
                    "role": "orquestadora",
                    "slot": "coordinadora-11",
                    "threadId": in_thread,
                    "started": "2026-10-28T10:00:00+00:00",
                    "status": "PENDIENTE_ACK",
                },
            ],
        },
    )
    (fl_dir / "roster_changes.jsonl").write_text("", encoding="utf-8")
    return fl_dir


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the delivered module as a real subprocess.

    Before: args contains a complete CLI invocation after the module path.
    During: executes the module with the current test interpreter.
    After: returns captured stdout, stderr, and the literal process return code.
    """
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_rotate_coordinator_real_fases_iguales_al_original() -> None:
    """Verify that the copied module still exposes phase A before phase B."""
    module = _load_module()
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert source.index("def phase_a") < source.index("def phase_b")
    assert callable(module.phase_a)
    assert callable(module.phase_b)
    assert callable(module.guard)


def test_argumentos_rutas_motor_fl_backups(tmp_path: Path) -> None:
    """Verify route arguments, validation codes, and the positive rehearsal path."""
    fl_dir = _make_fixtures(tmp_path)
    backups_dir = tmp_path / "backups"
    valid = _run_cli(
        "--motor-root",
        str(MOTOR_ROOT),
        "--fl-dir",
        str(fl_dir),
        "--backups-dir",
        str(backups_dir),
        "--rehearsal",
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr

    missing = tmp_path / "NOEXISTE"
    invalid = _run_cli(
        "--motor-root",
        str(missing),
        "--fl-dir",
        str(fl_dir),
        "--backups-dir",
        str(backups_dir),
        "--rehearsal",
    )
    assert invalid.returncode == 3
    assert str(missing) in invalid.stdout + invalid.stderr

    no_fl = _run_cli(
        "--motor-root",
        str(MOTOR_ROOT),
        "--backups-dir",
        str(backups_dir),
        "--rehearsal",
    )
    assert no_fl.returncode == 2

    no_backups = _run_cli(
        "--motor-root",
        str(MOTOR_ROOT),
        "--fl-dir",
        str(fl_dir),
        "--rehearsal",
    )
    assert no_backups.returncode == 2

    inert_root = tmp_path / "existing-but-incomplete"
    inert_root.mkdir()
    inert = _run_cli(
        "--motor-root",
        str(inert_root),
        "--fl-dir",
        str(fl_dir),
        "--backups-dir",
        str(backups_dir),
        "--rehearsal",
    )
    assert inert.returncode not in (0, 2, 3)


def test_rehearsal_con_control_negativo(tmp_path: Path) -> None:
    """Verify the negative guard control and real-file immutability output."""
    fl_dir = _make_fixtures(tmp_path)
    result = _run_cli(
        "--motor-root",
        str(MOTOR_ROOT),
        "--fl-dir",
        str(fl_dir),
        "--backups-dir",
        str(tmp_path / "backups"),
        "--rehearsal",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "CONTROL NEGATIVO" in output and "rc 1" in output
    assert "FICHEROS REALES INTACTOS: True" in output


def test_literal_timestamp_falso_ausente() -> None:
    """Verify that the copied module contains no stale literal timestamp."""
    assert MODULE_PATH.read_text(encoding="utf-8").count("a las 13:59") == 0


def test_phase_b_writes_post_rotation_deadline(tmp_path: Path) -> None:
    """Phase B records the active timestamp and seven-minute deadline.

    Before: a valid phase-B fixture has an incoming registry session.
    During: execute phase_b with the existing roster writer.
    After: the incoming session contains parseable active and deadline fields.
    """
    module = _load_module()
    fl_dir = _make_fixtures(tmp_path)
    writer_path = MOTOR_ROOT / "scripts" / "flight_roster_writer.py"
    spec = importlib.util.spec_from_file_location("flight_roster_writer", writer_path)
    assert spec is not None and spec.loader is not None
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    module.W = writer
    args = type(
        "Args",
        (),
        {"in_code": "CO-11", "out_code": "CO-10", "reason": "test"},
    )()

    module.phase_b(fl_dir, args, "TEST")

    data = json.loads((fl_dir / "session_registry.json").read_text(encoding="utf-8"))
    incoming = next(item for item in data["sessions"] if item["code"] == "CO-11")
    active = module.datetime.datetime.fromisoformat(incoming["activo_ts"])
    deadline = module.datetime.datetime.fromisoformat(incoming["post_relevo_plazo"])
    assert deadline - active == module.datetime.timedelta(minutes=7)
