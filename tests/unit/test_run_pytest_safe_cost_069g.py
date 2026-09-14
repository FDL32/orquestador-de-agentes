"""WOT-2026-069g -- telemetria de coste y interprete del motor.

Cubre lo adjudicado por el bucle 1->3 lentes (PROP-SUITE-2026-09-14, seccion ADJUDICACION):

- I1: el registro de `run_history.jsonl` nombra `started_at` e
  `interpreter_kind` (whitelist deliberada en `append_run_history`, no un
  None heredado: la premisa v1 del dossier era FALSA y las 3 lentes lo
  cazaron -- `duration_s` ya se grababa). La ETA se deriva por mediana de
  `duration_s` de corridas comparables (level + args_mode), funcion pura.
- I2: el caso motor de `resolve_test_interpreter` prefiere el `.venv` del
  propio repo CUANDO el probe de pytest pasa; si no, cae a `sys.executable`
  CON el WARN de WOT-2026-041h intacto (rechazo ruidoso, nunca silencio).

No cubre (fuera de contrato, admitido por consenso de lentes): paralelizar
`--level all` (deuda `WOT-2026-069h` con protocolo de adopcion serial-vs-paralelo).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_pytest_safe as rps


# Sello de contrato: estos tests son ROJOS antes de tocar produccion (D2 del
# contrato T-069G-001; registro de rc en execution_log.md).


@pytest.fixture
def hist_file(tmp_path, monkeypatch):
    path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(rps, "RUN_HISTORY_JSONL", path)
    return path


def _summary(**overrides):
    base = {
        "started_at": "2026-09-14T21:43:12+00:00",
        "finished_at": "2026-09-14T22:48:04+00:00",
        "level": "all",
        "args_mode": "default_discovery",
        "status": "finished",
        "exit_code": 0,
        "passed": 6542,
        "skipped": 50,
        "failed_count": 0,
        "errors": 0,
        "duration_s": 3885.74,
        "top_slowest": [],
        "tested_commit_sha": "f3a36da0b22e9ecd4160756633018e48a3064eee",
        "interpreter_kind": "venv",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# I1 -- registro y ETA
# ---------------------------------------------------------------------------


def test_i1_registro_nombre_started_e_interpreter(hist_file):
    rps.append_run_history(_summary())
    row = hist_file.read_text(encoding="utf-8").strip()
    assert '"started_at": "2026-09-14T21:43:12+00:00"' in row
    assert '"interpreter_kind": "venv"' in row
    assert '"duration_s": 3885.74' in row  # control anti-sobre-correccion


def test_i1_eta_mediana_corridas_comparables(tmp_path):
    hist = tmp_path / "run_history.jsonl"
    rows = [
        # comparables: level=all default_discovery finished con duration
        '{"level": "all", "args_mode": "default_discovery", "status": "finished", '
        '"duration_s": 60.0}',
        '{"level": "all", "args_mode": "default_discovery", "status": "finished", '
        '"duration_s": 120.0}',
        '{"level": "all", "args_mode": "default_discovery", "status": "finished", '
        '"duration_s": 300.0}',
        # NO comparables: otro level / row sin duracion / crash
        '{"level": "unit", "args_mode": "default_discovery", "status": "finished", '
        '"duration_s": 1.0}',
        '{"level": "all", "args_mode": "default_discovery", "status": "crashed"}',
        '{"level": "all", "args_mode": "explicit"}',
    ]
    hist.write_text("\n".join(rows) + "\n", encoding="utf-8")
    note = rps.suite_eta_note(hist, level="all", args_mode="default_discovery")
    assert "ETA estimada ~2.0 min" in note  # mediana (120s), no media (300 arrastra)
    assert "3 corrida" in note  # denominador: n corridas comparables


def test_i1_eta_sin_historico_dice_sin_historico(tmp_path):
    hist = tmp_path / "run_history.jsonl"
    hist.write_text('{"level": "unit", "duration_s": 2.0}\n', encoding="utf-8")
    note = rps.suite_eta_note(hist, level="all", args_mode="default_discovery")
    assert "sin historico comparable" in note


def test_i1_eta_fall_open_file_inexistente(tmp_path):
    note = rps.suite_eta_note(
        tmp_path / "no-existe.jsonl", level="all", args_mode="default_discovery"
    )
    assert "sin historico comparable" in note


# ---------------------------------------------------------------------------
# I2 -- interprete del motor
# ---------------------------------------------------------------------------


@pytest.fixture
def motor_layout(tmp_path, monkeypatch):
    motor = tmp_path / "motor"
    motor.mkdir()
    monkeypatch.setattr(rps, "_PROJECT_ROOT", motor)
    monkeypatch.setattr(rps, "_PROJECT_ROOT_BOOTSTRAP", motor)
    venv = tmp_path / "venv-py"
    return motor, venv


def test_i2_motor_prefiere_su_venv_cuando_probe_pasa(motor_layout, monkeypatch):
    motor, venv = motor_layout
    monkeypatch.setattr(
        rps, "_venv_python", lambda root: venv if root == motor else None
    )
    monkeypatch.setattr(rps, "probe_pytest", lambda interp: interp == str(venv))
    monkeypatch.setattr(sys, "executable", "system-python")
    assert rps.resolve_test_interpreter() == str(venv)


def test_i2_motor_rechaza_venv_sin_pytest_y_avisa_ruinosamente(
    motor_layout, monkeypatch, capsys
):
    motor, venv = motor_layout
    monkeypatch.setattr(
        rps, "_venv_python", lambda root: venv if root == motor else None
    )
    monkeypatch.setattr(rps, "probe_pytest", lambda interp: False)
    monkeypatch.setattr(sys, "executable", str(Path(sys.executable).resolve()))
    picked = rps.resolve_test_interpreter()
    assert Path(picked).resolve() == Path(sys.executable).resolve()
    # WOT-2026-041h intacto: el rechazo del candidato NUNCA es silencio.
    assert "[WARN]" in capsys.readouterr().err


def test_i2_motor_sin_venv_comportamiento_legado(motor_layout, monkeypatch, capsys):
    _motor, _venv = motor_layout
    monkeypatch.setattr(rps, "_venv_python", lambda root: None)
    monkeypatch.setattr(rps, "probe_pytest", lambda interp: False)
    monkeypatch.setattr(sys, "executable", "system-python")
    assert rps.resolve_test_interpreter() == "system-python"
    # sin .venv no hay candidato que rechazar -> ni WARN ni crash (legado)
    assert "[WARN]" not in capsys.readouterr().err


def test_i2_clasificador_kind_de_interprete(motor_layout):
    motor, _venv = motor_layout
    fake_venv = motor / ".venv" / "Scripts" / "python.exe"
    fake_venv.parent.mkdir(parents=True)
    fake_venv.touch()
    assert rps.classify_interpreter_kind(str(fake_venv), motor) == "venv-local"
    assert rps.classify_interpreter_kind(sys.executable, motor) != "venv-local"
