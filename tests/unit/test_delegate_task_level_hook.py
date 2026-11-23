from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".agent" / "hooks" / "guard_model_level.py"
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
UUID36 = "12345678-1234-4234-8234-123456789012"


def _tree(tmp_path: Path, *, levels: list[str], access: str = "cuenta_propia") -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".agent" / "config").mkdir(parents=True)
    (tmp_path / ".agent" / "hooks").mkdir()
    shutil.copy2(HOOK, tmp_path / ".agent" / "hooks" / "guard_model_level.py")
    config = {
        "ensemble_registry": {
            "roles": {"U4": {"nivel": "medio"}},
            "uso_maximo_por_tipo": {"medio": 7000},
            "backend_keys": {
                "BA05": {
                    "backend": "codex",
                    "model": "gpt-5.6-luna",
                    "status": "active",
                    "niveles": levels,
                    "acceso": access,
                }
            },
        }
    }
    (tmp_path / ".agent" / "config" / "agents.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps(SETTINGS), encoding="utf-8"
    )
    return tmp_path


def _shim_command() -> str:
    for group in SETTINGS["hooks"]["PreToolUse"]:
        if group.get("matcher") == "mcp__t3-code__delegate_task":
            return group["hooks"][0]["command"]
    raise AssertionError("delegate_task matcher missing")


def _run(payload: dict, cwd: Path):
    return subprocess.run(  # noqa: S602
        _shim_command(),
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=cwd,
        shell=True,
    )


def _payload(*, model="gpt-5.6-luna", request=None):
    tool_input = {"target": {"providerInstanceId": "codex_x", "model": model}}
    if request is not None:
        tool_input["peticion_usuario"] = request
    return {"tool_name": "mcp__t3-code__delegate_task", "tool_input": tool_input}


def test_hook_d3_ba05_passes_with_an_eligible_declared_level(tmp_path):
    tree = _tree(tmp_path, levels=["medio", "alto"])
    result = _run(_payload(), tree)
    assert result.returncode == 0, result.stderr


def test_hook_rejects_premium_without_request_and_accepts_uuid36_format(tmp_path):
    tree = _tree(tmp_path, levels=["premium"])
    rejected = _run(_payload(), tree)
    assert rejected.returncode == 2
    assert "nivel-no-autorizado" in rejected.stdout + rejected.stderr
    accepted = _run(_payload(request=UUID36), tree)
    assert accepted.returncode == 0, accepted.stderr


def test_hook_rejects_external_paid_even_with_request(tmp_path):
    tree = _tree(tmp_path, levels=["medio"], access="externo_pago")
    result = _run(_payload(request=UUID36), tree)
    assert result.returncode == 2
    assert "acceso-externo-pago" in result.stdout + result.stderr


def test_hook_missing_file_is_inactive_via_real_settings_shim(tmp_path):
    tree = _tree(tmp_path, levels=["medio"])
    (tree / ".agent" / "hooks" / "guard_model_level.py").unlink()
    result = _run(_payload(), tree)
    assert result.returncode == 2
    assert "HOOK INACTIVE" in result.stdout + result.stderr


def test_hook_load_failure_is_normalized_to_inactive_rc2(tmp_path):
    tree = _tree(tmp_path, levels=["medio"])
    (tree / ".agent" / "hooks" / "guard_model_level.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    result = _run(_payload(), tree)
    assert result.returncode == 2
    assert "HOOK INACTIVE" in result.stdout + result.stderr


def test_hook_mutated_matcher_is_inactive(tmp_path):
    tree = _tree(tmp_path, levels=["medio"])
    settings = json.loads((tree / ".claude" / "settings.json").read_text())
    for group in settings["hooks"]["PreToolUse"]:
        if group.get("matcher") == "mcp__t3-code__delegate_task":
            group["matcher"] = "mcp__other__delegate_task"
    (tree / ".claude" / "settings.json").write_text(json.dumps(settings))
    result = _run(_payload(), tree)
    assert result.returncode == 2
    assert "HOOK INACTIVE" in result.stdout + result.stderr
