"""Mutation-to-prove del gate `role_models.BUILDER != role_models.REVISOR`.

WOT-2026-098b. El gate (Fase 2 del work_plan) muerde SOLO cuando ambos valores son
`model_id`s reales e IGUALES: un `null` y un NOMBRE DE BACKEND nunca cuentan como
colision (regla de la propuesta v6, Seccion 8.3). Cada test nombra la mutacion que
mata; el par (exit 1 con colision / exit 0 sin ella) ES el mutation-verify: si se
revierte la rama de colision del gate, `test_cli_collision_exits_one` cae.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_role_models_distinct as crmd  # noqa: E402


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_GATE = _MOTOR_ROOT / "scripts" / "check_role_models_distinct.py"


def _backend() -> dict:
    return {
        "executable": "opencode",
        "args": ["run"],
        "discovery": {"method": "path_only"},
    }


def _config(role_models: dict | None) -> dict:
    cfg = {
        "schema_version": "1.4",
        "backends": {"opencode": _backend(), "nan_api": _backend()},
        "role_assignments": {"BUILDER": "opencode"},
    }
    if role_models is not None:
        cfg["role_models"] = role_models
    return cfg


def _write_project(tmp_path: Path, config: dict) -> Path:
    cfg_dir = tmp_path / ".agent" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "agents.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------- pure comparator
def test_collision_when_same_real_model_id() -> None:
    """MUTACION: si la rama de colision no existiera, este assert (True) cae."""
    _b, _r, collision = crmd.compare_role_models(
        _config(
            {"BUILDER": "nan/deepseek-v4-flash", "REVISOR": "nan/deepseek-v4-flash"}
        )
    )
    assert collision is True


def test_distinct_real_model_ids_do_not_collide() -> None:
    _b, _r, collision = crmd.compare_role_models(
        _config({"BUILDER": "nan/deepseek-v4-flash", "REVISOR": "nan/glm5.3-flash"})
    )
    assert collision is False


def test_null_revisor_never_collides() -> None:
    """MUTACION: tratar `null` como comparable haria colisionar aqui (falso rojo)."""
    _b, _r, collision = crmd.compare_role_models(
        _config({"BUILDER": "nan/deepseek-v4-flash", "REVISOR": None})
    )
    assert collision is False


def test_missing_revisor_never_collides() -> None:
    _b, _r, collision = crmd.compare_role_models(
        _config({"BUILDER": "nan/deepseek-v4-flash"})
    )
    assert collision is False


def test_backend_name_is_not_a_comparable_model_id() -> None:
    """Dos nombres de BACKEND iguales NO son una colision de modelos (v6).

    MUTACION: una igualdad naive `builder == revisor` marcaria colision aqui; el
    gate DEBE tipificar y descartar los nombres de backend.
    """
    _b, _r, collision = crmd.compare_role_models(
        _config({"BUILDER": "opencode", "REVISOR": "opencode"})
    )
    assert collision is False


def test_empty_string_is_not_a_comparable_model_id() -> None:
    _b, _r, collision = crmd.compare_role_models(
        _config({"BUILDER": "", "REVISOR": ""})
    )
    assert collision is False


# ------------------------------------------------------------------- CLI barrier
def test_cli_collision_exits_one(tmp_path: Path) -> None:
    """PAR de exit-codes (mutacion alcanzable): colision -> 1."""
    project = _write_project(
        tmp_path,
        _config({"BUILDER": "nan/x", "REVISOR": "nan/x"}),
    )
    assert crmd.main(["--project-root", str(project)]) == 1


def test_cli_distinct_exits_zero(tmp_path: Path) -> None:
    """PAR de exit-codes: modelos distintos -> 0."""
    project = _write_project(
        tmp_path,
        _config({"BUILDER": "nan/x", "REVISOR": "nan/y"}),
    )
    assert crmd.main(["--project-root", str(project)]) == 0


def test_cli_real_exit_code_via_subprocess(tmp_path: Path) -> None:
    """El rc REAL del proceso (nunca el de un pipe): colision -> 1."""
    project = _write_project(
        tmp_path,
        _config({"BUILDER": "nan/x", "REVISOR": "nan/x"}),
    )
    proc = subprocess.run(
        [sys.executable, str(_GATE), "--project-root", str(project)],
        capture_output=True,
        text=True,
        cwd=str(_MOTOR_ROOT),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "colisionan" in (proc.stdout + proc.stderr).lower() or (
        "BUILDER" in proc.stdout
    )


def test_unreadable_config_fails_closed(tmp_path: Path) -> None:
    """Sin agents.json el gate NO sale verde por defecto -> exit 2."""
    assert crmd.main(["--project-root", str(tmp_path)]) == 2


def test_corrupt_config_fails_closed(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "agents.json").write_text("{ no es json", encoding="utf-8")
    assert crmd.main(["--project-root", str(tmp_path)]) == 2


# ------------------------------------------------------------- live contract
def test_real_agents_json_has_distinct_builder_and_revisor() -> None:
    """Contrato VIVO: el agents.json REAL del motor cumple el gate y declara revisor.

    Ancla DoD (a)+(b) sobre el fichero real, no sobre un fixture.
    """
    config = crmd.load_agents_config(_MOTOR_ROOT)
    assert "revisor" in config["role_mapping"], "falta role_mapping.revisor"
    role_models = config["role_models"]
    assert role_models["REVISOR"], "role_models.REVISOR debe ser un model_id real"
    assert role_models["MANAGER"] is None, "role_models.MANAGER debe ser null explicito"
    _b, _r, collision = crmd.compare_role_models(config)
    assert collision is False, (
        "el gate COLISIONA sobre el agents.json real: BUILDER y REVISOR "
        "comparten model_id"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
