"""Tests for the read-only hilo-failed detector and its closeout wiring."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.session_closeout as session_closeout
from scripts.closeout_steps import gates
from scripts.flight import hilo_failed_detector
from scripts.session_closeout import StepResult


ACTIVE = ("ACTIVA", "FALLIDA", "SUPERVISORA", "ENTREGADO")
TERMINAL = (
    "ASENTADA",
    "SETTLED",
    "CASCADA",
    "RELEVADA",
    "COMPLETADA",
    "SUPERSEDED",
    "CERRADA",
    "HISTORICO",
    "DESACTIVADA",
    "DESCARTADA",
)


def _make_store(path: Path, runs: list[tuple[str, str, int]]) -> None:
    """Create only the measured projection tables used by the detector."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE orchestration_v2_projection_runs (
            thread_id TEXT NOT NULL, status TEXT NOT NULL, ordinal INTEGER NOT NULL
        );
        CREATE TABLE orchestration_v2_projection_threads (
            thread_id TEXT PRIMARY KEY, deleted_at TEXT
        );
        CREATE TABLE orchestration_v2_projection_subagents (
            child_thread_id TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO orchestration_v2_projection_runs VALUES (?, ?, ?)", runs
    )
    connection.executemany(
        "INSERT INTO orchestration_v2_projection_threads(thread_id, deleted_at) VALUES (?, NULL)",
        [(thread_id,) for thread_id, _, _ in runs],
    )
    connection.commit()
    connection.close()


def _flight(tmp_path: Path, sessions: list[dict], runs: list[tuple[str, str, int]]):
    flight_dir = tmp_path / "flight"
    ops_dir = tmp_path / "ops"
    flight_dir.mkdir()
    ops_dir.mkdir()
    real_shape = [
        {
            "code": session["code"],
            "status": session["status"],
            "threadId": session["threadId"],
            "slot": session.get("slot", "builder"),
            "role": session.get("role", "builder"),
            "started": session.get("started", "2026-11-16T00:00:00Z"),
            "reporta_a": session.get("reporta_a", "CO-108"),
            "launched_by": session.get("launched_by", "test"),
        }
        for session in sessions
    ]
    (flight_dir / "session_registry.json").write_text(
        json.dumps({"sessions": real_shape}), encoding="utf-8"
    )
    store = tmp_path / "statev2.sqlite"
    _make_store(store, runs)
    return flight_dir, store, ops_dir


def _stub_env(tmp_path: Path) -> dict[str, str]:
    stub = tmp_path / "sitecustomize.py"
    stub.write_text(
        "from scripts.flight import comms_alert\n"
        "comms_alert.notify = lambda *args, **kwargs: (print('NOTIFIER_STUB'), 0)[1]\n",
        encoding="ascii",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + str(Path.cwd())
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_detector(flight_dir: Path, store: Path, ops_dir: str, env: dict[str, str]):
    return subprocess.run(
        [
            sys.executable,
            "scripts/flight/hilo_failed_detector.py",
            "--flight-dir",
            str(flight_dir),
            "--store",
            str(store),
            "--ops-dir",
            ops_dir,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_detector_emite_solo_no_terminales(tmp_path):
    sessions = [
        {
            "code": code,
            "threadId": f"mcp:{code}",
            "status": f"{status} en vuelo",
        }
        for code, status in zip(
            ("TR-23", "IM-157", "IM-158", "TR-64"), ACTIVE, strict=True
        )
    ]
    sessions += [
        {"code": f"TERM-{i}", "threadId": f"mcp:term-{i}", "status": status}
        for i, status in enumerate(TERMINAL)
    ]
    sessions.append({"code": "LIBRE-1", "threadId": "mcp:libre", "status": "CANCELADA"})
    runs = [
        (f"mcp:{code}", "failed", 1)
        for code, _ in zip(("TR-23", "IM-157", "IM-158", "TR-64"), ACTIVE, strict=True)
    ]
    runs += [(f"mcp:term-{i}", "failed", 1) for i in range(len(TERMINAL))]
    runs.append(("mcp:libre", "cancelled", 1))
    flight_dir, store, ops_dir = _flight(tmp_path, sessions, runs)
    result = _run_detector(flight_dir, store, str(ops_dir), _stub_env(tmp_path))
    assert result.returncode == 1
    assert [
        line for line in result.stdout.splitlines() if line.startswith("hilo-failed-")
    ] == [
        "hilo-failed-IM-157",
        "hilo-failed-IM-158",
        "hilo-failed-TR-23",
        "hilo-failed-TR-64",
    ]
    assert "hilo-failed-TERM-" not in result.stdout


def test_detector_lee_prefijos_y_terminales_de_las_fixtures(tmp_path):
    fixture_lines = []
    for name in ("latido_predecesor.md", "latido_sucesor.md"):
        path = Path("tests/fixtures/render_latido") / name
        fixture_lines.append(
            next(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if "El status del registry" in line
            )
        )
    assert all(prefix in line for line in fixture_lines for prefix in ACTIVE)
    assert all(status in fixture_lines[0] for status in TERMINAL)

    sessions = [
        {"code": f"TERM-{i}", "threadId": f"mcp:term-{i}", "status": status}
        for i, status in enumerate(TERMINAL)
    ]
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        sessions,
        [(f"mcp:term-{i}", "failed", 1) for i in range(len(TERMINAL))],
    )
    result = _run_detector(flight_dir, store, str(ops_dir), _stub_env(tmp_path))
    assert result.returncode == 0
    assert "hilo-failed-" not in result.stdout


def test_registry_real_usa_code_key_when_available():
    path = Path(
        "C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_workspace/.agent/runtime/flight/vuelo-20261026b/session_registry.json"
    )
    if not path.is_file():
        pytest.skip("real flight registry is not available")
    document = json.loads(path.read_text(encoding="utf-8"))
    sessions = document["sessions"]
    assert sessions
    assert all("code" in session for session in sessions)
    assert all("session_code" not in session for session in sessions)


def test_detector_accepts_punctuation_after_active_prefix(tmp_path):
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        [
            {
                "code": "IM-27",
                "threadId": "mcp:im-27",
                "status": "ENTREGADO, SIN INTEGRAR (... )",
            }
        ],
        [("mcp:im-27", "failed", 1)],
    )
    result = _run_detector(flight_dir, store, str(ops_dir), _stub_env(tmp_path))
    assert result.returncode == 1
    assert "hilo-failed-IM-27" in result.stdout


def test_detector_event_failure_is_fail_closed(tmp_path, monkeypatch, capsys):
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        [{"code": "TR-1", "threadId": "mcp:tr-1", "status": "ACTIVA"}],
        [("mcp:tr-1", "failed", 1)],
    )
    monkeypatch.setattr(
        hilo_failed_detector.comms_alert, "event", lambda *args, **kwargs: 2
    )
    result = hilo_failed_detector.detect(flight_dir, store, str(ops_dir), {})
    assert result == 2
    assert "alert-unavailable" in capsys.readouterr().err


def test_detector_deduplicates_on_same_ops_dir(tmp_path):
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        [{"code": "TR-1", "threadId": "mcp:tr-1", "status": "ACTIVA"}],
        [("mcp:tr-1", "failed", 1)],
    )
    env = _stub_env(tmp_path)
    first = _run_detector(flight_dir, store, str(ops_dir), env)
    second = _run_detector(flight_dir, store, str(ops_dir), env)
    assert first.returncode == 1
    assert second.returncode == 1
    assert "limitado" in second.stdout


@pytest.mark.parametrize(
    ("returncode", "status", "blocking"),
    [(0, "PASS", True), (1, "FAIL", True), (2, "FAIL", True), (3, "SKIP", False)],
)
def test_hilo_failed_gate_maps_exit_codes(returncode, status, blocking):
    def run_script(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], returncode, "out", "err")

    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        False,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stderr,
        step_result_cls=StepResult,
    )
    assert (result.status, result.blocking) == (status, blocking)


def test_hilo_failed_gate_dry_run_skips_without_execution():
    called = []

    def run_script(*args, **kwargs):
        called.append(True)
        return subprocess.CompletedProcess(args[0], 0, "", "")

    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        True,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stderr,
        step_result_cls=StepResult,
    )
    assert result.status == "SKIP"
    assert result.blocking is False
    assert called == []


def test_hilo_failed_gate_without_context_passes_no_flight_argument(monkeypatch):
    captured = []

    def run_script(script_name, args, project_root, timeout):
        captured.append(args)
        return subprocess.CompletedProcess(
            script_name, 3, "", "flight-dir sin declarar"
        )

    monkeypatch.delenv("FLIGHT_OPS_DIR", raising=False)
    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        False,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stderr,
        step_result_cls=StepResult,
    )
    assert result.status == "SKIP"
    assert result.blocking is False
    assert captured == [[]]
    assert "N/A" in result.detail
    assert "sin contexto de vuelo" in result.detail


def test_hilo_failed_gate_context_without_ops_is_actionable(tmp_path, monkeypatch):
    captured = []
    registry = tmp_path / "flight" / "session_registry.json"
    registry.parent.mkdir()

    def run_script(script_name, args, project_root, timeout):
        captured.append(args)
        return subprocess.CompletedProcess(script_name, 2, "", "ops-dir sin resolver")

    monkeypatch.delenv("FLIGHT_OPS_DIR", raising=False)
    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        False,
        registry_path=str(registry),
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stderr,
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True
    assert captured == [["--flight-dir", str(registry.parent)]]
    assert "orden:" in result.detail
    assert "exporta FLIGHT_OPS_DIR=<ops-dir>" in result.detail


@pytest.mark.parametrize(
    ("case_id", "registry_content", "store_missing", "expected"),
    [
        ("registry-missing", None, True, "registry-missing"),
        ("registry-empty", "", True, "registry-empty"),
        ("registry-truncated", "{", True, "registry-truncated"),
        (
            "registry-invalid-type",
            json.dumps({"sessions": {}}),
            True,
            "registry-invalid-type",
        ),
        (
            "store-missing",
            json.dumps({"sessions": []}),
            True,
            "store-missing",
        ),
    ],
)
def test_detector_fail_closed_fuente_ilegible(
    tmp_path, case_id, registry_content, store_missing, expected
):
    flight_dir = tmp_path / "flight"
    flight_dir.mkdir()
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    if registry_content is not None:
        (flight_dir / "session_registry.json").write_text(
            registry_content, encoding="utf-8"
        )
    store = tmp_path / "missing.sqlite"
    if not store_missing:
        _make_store(store, [])
    result = _run_detector(flight_dir, store, str(ops_dir), _stub_env(tmp_path))
    assert result.returncode == 2, case_id
    assert expected in result.stderr


@pytest.mark.parametrize(
    ("case_id", "ops_arg", "expected"),
    [
        ("ops-dir-absent", None, "ops-dir sin resolver"),
        ("ops-dir-explicit-invalid", "relative-ops", "ruta absoluta"),
        (
            "ops-dir-explicit-missing",
            "__MISSING_ABS__",
            "no existe",
        ),
    ],
)
def test_detector_fail_closed_ops_dir_cases(tmp_path, case_id, ops_arg, expected):
    flight_dir, store, _ops_dir = _flight(
        tmp_path,
        [{"code": "TR-1", "threadId": "mcp:tr-1", "status": "ACTIVA"}],
        [("mcp:tr-1", "completed", 1)],
    )
    env = _stub_env(tmp_path)
    env.pop("FLIGHT_OPS_DIR", None)
    command = [
        sys.executable,
        "scripts/flight/hilo_failed_detector.py",
        "--flight-dir",
        str(flight_dir),
        "--store",
        str(store),
    ]
    if ops_arg == "__MISSING_ABS__":
        ops_arg = str(tmp_path / "missing-ops")
    if ops_arg is not None:
        command.extend(["--ops-dir", ops_arg])
    result = subprocess.run(
        command, capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 2, case_id
    assert expected in result.stderr


def test_camino_que_corra_solo_invoca_el_detector(tmp_path, monkeypatch):
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        [{"code": "TR-1", "threadId": "mcp:tr-1", "status": "ACTIVA"}],
        [("mcp:tr-1", "completed", 1)],
    )
    env = _stub_env(tmp_path)
    env.update(
        {
            "FLIGHT_DIR": str(flight_dir),
            "T3_STATE_DB": str(store),
            "FLIGHT_OPS_DIR": str(ops_dir),
        }
    )
    monkeypatch.setenv("FLIGHT_DIR", str(flight_dir))
    monkeypatch.setenv("T3_STATE_DB", str(store))
    monkeypatch.setenv("FLIGHT_OPS_DIR", str(ops_dir))
    monkeypatch.setenv("PYTHONPATH", env["PYTHONPATH"])
    calls = []

    def run_script(script_name, args, project_root, timeout=120):
        calls.append((script_name, args, timeout))
        command = [sys.executable, str(project_root / "scripts" / script_name), *args]
        return subprocess.run(
            command, capture_output=True, text=True, env=env, check=False
        )

    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        False,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stderr,
        step_result_cls=StepResult,
    )
    assert result.status == "PASS"
    assert result.name == "hilo_failed_detector"
    assert calls and calls[0][0] == "flight/hilo_failed_detector.py"
    assert "hilo_failed_detector" in [result.name]

    captured = []
    monkeypatch.setattr(
        session_closeout, "_resolve_session_window", lambda root: (None, "test")
    )
    monkeypatch.setattr(
        session_closeout, "_resolve_tickets", lambda root, explicit: ([], "test")
    )
    monkeypatch.setattr(
        session_closeout, "_check_bus_vacio", lambda *args, **kwargs: "PASS"
    )
    monkeypatch.setattr(
        session_closeout,
        "_generate_report",
        lambda report, root: captured.append(report) or (tmp_path / "report.md"),
    )

    def pass_step(*args, **kwargs):
        return StepResult(name="stub", status="PASS", detail="stub", blocking=False)

    wrapper_args = {}

    def fake_hilo_wrapper(*args, **kwargs):
        wrapper_args.update(kwargs)
        return result

    monkeypatch.setattr(
        session_closeout, "_step_hilo_failed_detector", fake_hilo_wrapper
    )

    for name in dir(session_closeout):
        if name.startswith("_step_") and name not in {
            "_step_hilo_failed_detector",
            "_step_hilo_failed_detector_impl",
        }:
            value = getattr(session_closeout, name)
            if callable(value):
                monkeypatch.setattr(session_closeout, name, pass_step)
    assert (
        session_closeout.run_closeout(
            Path.cwd(),
            skip_slow=True,
            explicit_tickets=[],
            registry_path=str(flight_dir / "session_registry.json"),
            roster_path=str(flight_dir / "flight_roster.json"),
        )
        == 0
    )
    assert captured
    assert "hilo_failed_detector" in [step.name for step in captured[0].steps]
    assert wrapper_args["registry_path"] == str(flight_dir / "session_registry.json")
    assert wrapper_args["roster_path"] == str(flight_dir / "flight_roster.json")


def test_camino_que_corra_solo_propaga_salida_real_del_detector(tmp_path):
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        [{"code": "TR-1", "threadId": "mcp:tr-1", "status": "ACTIVA"}],
        [("mcp:tr-1", "failed", 1)],
    )
    env = _stub_env(tmp_path)
    env.update(
        {
            "FLIGHT_DIR": str(flight_dir),
            "T3_STATE_DB": str(store),
            "FLIGHT_OPS_DIR": str(ops_dir),
        }
    )

    def run_script(script_name, args, project_root, timeout=120):
        command = [sys.executable, str(project_root / "scripts" / script_name), *args]
        return subprocess.run(
            command, capture_output=True, text=True, env=env, check=False
        )

    result = gates.step_hilo_failed_detector(
        Path.cwd(),
        False,
        run_script_fn=run_script,
        process_diagnostic_fn=lambda completed: completed.stdout or completed.stderr,
        step_result_cls=StepResult,
    )
    assert result.status == "FAIL"
    assert result.blocking is True
    assert "hilo-failed-TR-1" in result.detail


def test_detector_no_dispara_sobre_historicos(tmp_path):
    sessions = [
        {"code": "HIST-1", "threadId": "mcp:hist", "status": "HISTORICO"},
        {
            "code": "FREE-1",
            "threadId": "mcp:free",
            "status": "PARADA SIN BUILDER",
        },
    ]
    flight_dir, store, ops_dir = _flight(
        tmp_path,
        sessions,
        [
            ("mcp:hist", "interrupted", 1),
            ("mcp:free", "failed", 1),
            ("mcp:child", "failed", 1),
        ],
    )
    result = _run_detector(flight_dir, store, str(ops_dir), _stub_env(tmp_path))
    assert result.returncode == 0
    assert "hilo-failed-" not in result.stdout
