"""Cierra G1 y G2 de la barrera de memoria (WOT-2026-089e), medidos por
mutation-verify el 2026-10-02: dos mutaciones SOBREVIVIAN porque ningun test las
fijaba.

- G1: el cierre mide el MOTOR ademas del destino. Si `_step_memory_health` dejara
  de pasar `--motor-root`, el paso seguiria verde y la barrera dejaria de mirar
  el repo donde el L1 llego a 97 % de ruido sin que nadie lo viera.
- G2: un fallo del propio medidor (no arranca, se cuelga) es WARN, nunca FAIL ni
  una excepcion que tumbe el cierre.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import session_closeout  # noqa: E402
from scripts.closeout_steps.memory_health import step_memory_health  # noqa: E402


_CLEAN = '{"destino": {"triggers": [], "l1": {"parsed": 1, "noise": 0}, "l2": {"rules": 1, "max_rules": 30}}}'


def _capture_args(stdout: str = _CLEAN):
    calls: list[list[str]] = []

    def _fake(script_name, args, project_root, timeout=120):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout, stderr=""
        )

    return calls, _fake


def test_closeout_step_passes_the_resolved_motor_root(tmp_path: Path) -> None:
    """G1: con un motor resoluble, el medidor recibe `--motor-root <motor>`."""
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    motor.mkdir()
    destino.mkdir()
    calls, fake = _capture_args()

    with (
        patch("runtime.motor_link.resolve_motor_root", return_value=motor),
        patch("scripts.session_closeout._run_script", side_effect=fake),
    ):
        result = session_closeout._step_memory_health(destino)

    assert result.status == "PASS", result.detail
    assert len(calls) == 1
    args = calls[0]
    assert "--motor-root" in args, args
    assert args[args.index("--motor-root") + 1] == str(motor)


def test_closeout_step_omits_motor_root_when_unresolvable(tmp_path: Path) -> None:
    """Control: sin motor resoluble solo se mide el destino (no se inventa ruta)."""
    calls, fake = _capture_args()

    with (
        patch("runtime.motor_link.resolve_motor_root", return_value=None),
        patch("scripts.session_closeout._run_script", side_effect=fake),
    ):
        result = session_closeout._step_memory_health(tmp_path)

    assert result.status == "PASS", result.detail
    assert "--motor-root" not in calls[0]


def _run_step_raising(exc: Exception, tmp_path: Path):
    def _boom(script_name, args, project_root, timeout=120):
        raise exc

    return step_memory_health(
        tmp_path,
        None,
        run_script_fn=_boom,
        step_result_cls=session_closeout.StepResult,
    )


def test_measurer_timeout_is_a_nonblocking_warn(tmp_path: Path) -> None:
    """G2: `TimeoutExpired` -> WARN, no excepcion, no bloqueante."""
    result = _run_step_raising(subprocess.TimeoutExpired("x", 120), tmp_path)

    assert result.status == "WARN", result.detail
    assert not result.blocking
    assert "could not run" in result.detail


def test_measurer_missing_script_is_a_nonblocking_warn(tmp_path: Path) -> None:
    """G2: `FileNotFoundError` -> WARN, no excepcion, no bloqueante."""
    result = _run_step_raising(FileNotFoundError("check_memory_health.py"), tmp_path)

    assert result.status == "WARN", result.detail
    assert not result.blocking
