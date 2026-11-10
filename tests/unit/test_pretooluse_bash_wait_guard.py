"""Production-path tests for the Bash foreground-wait guard."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / ".agent" / "hooks" / "pretooluse_bash_wait_guard.py"
_ENTRY = _ROOT / ".agent" / "hooks" / "claude_guard_entry.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(payload: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=_ROOT,
    )


def test_timeout_sobre_umbral_bloquea():
    result = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": 301000}}
    )
    assert result.returncode == 2
    assert result.stderr
    # Un timeout presente con tipo no numerico (o booleano) falla cerrado en vez
    # de ignorarse: fail-open de tipo era un hueco medido por las lentes.
    as_text = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": "301000"}}
    )
    as_bool = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": True}}
    )
    assert as_text.returncode == 2 and as_text.stderr
    assert as_bool.returncode == 2 and as_bool.stderr


def test_bucle_sleep_corto_espera_total_bloquea():
    result = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "while true; do sleep 200; sleep 200; done"},
        }
    )
    assert result.returncode == 2
    # GNU sleep suma todos sus operandos: sleep 2m 9m son 660 s por iteracion.
    multi_operand = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "until ready; do sleep 2m 9m; done"},
        }
    )
    assert multi_operand.returncode == 2


def test_payload_ilegible_falla_cerrado_rc2():
    broken = subprocess.run(
        [sys.executable, str(_HOOK)], input=b"{", capture_output=True, cwd=_ROOT
    )
    missing = _run({"tool_name": "Bash", "tool_input": {}})
    assert broken.returncode == 2 and broken.stderr
    assert missing.returncode == 2 and missing.stderr


def test_settings_registra_hook_bash_canonico():
    settings = json.loads(
        (_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    entry = _load(_ENTRY, "claude_guard_entry_settings")
    groups = settings["hooks"]["PreToolUse"]
    bash = [group for group in groups if "Bash" in group["matcher"]]
    write = [group for group in groups if group["matcher"] == "Write|Edit|MultiEdit"]
    assert len(bash) == 1
    assert bash[0]["hooks"] == [
        {
            "type": "command",
            "command": entry.canonical_command_for("pretooluse_bash_wait_guard.py"),
        }
    ]
    assert len(write) == 1
    assert write[0]["hooks"][0]["command"] == entry.canonical_hook_command()


def test_umbral_exacto_300000_pasa_300001_bloquea():
    allowed = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": 300000}}
    )
    blocked = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": 300001}}
    )
    assert allowed.returncode == 0
    assert blocked.returncode == 2


def test_background_y_espera_corta_pasan():
    background = _run(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "sleep 1",
                "timeout": 600000,
                "run_in_background": True,
            },
        }
    )
    short = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "sleep 200"},
        }
    )
    assert background.returncode == 0
    assert short.returncode == 0


def test_bloqueo_escribe_motivo_en_stderr():
    result = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo ok", "timeout": 300001}}
    )
    assert result.returncode == 2
    assert b"run_in_background" in result.stderr or b"Monitor" in result.stderr


def test_payload_invalido_usa_pytest_raises(monkeypatch):
    hook = _load(_HOOK, "pretooluse_bash_wait_guard_direct")
    payload = io.TextIOWrapper(io.BytesIO(b"{invalid"))
    monkeypatch.setattr(sys, "stdin", payload)
    with pytest.raises(SystemExit) as exc:
        hook.main([])
    assert exc.value.code == 2


def test_tope_sleep_300_no_600():
    result = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "until ready; do sleep 200; sleep 200; done"},
        }
    )
    assert result.returncode == 2
