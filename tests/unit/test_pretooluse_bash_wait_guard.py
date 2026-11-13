"""Production-path tests for the Bash foreground-wait guard."""

from __future__ import annotations

import builtins
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


def _direct_run(hook, payload, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    result = hook.main([])
    return result, capsys.readouterr()


def test_detecta_lanzamiento_desacoplado(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_positive")
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    commands = [
        "echo work &",
        "(echo work) &",
        "nohup echo work",
        "setsid echo work",
        "echo work; disown",
        "start /b echo work",
        "Start-Process echo",
        "start-process echo",
        "Start-process echo",
    ]
    for command in commands:
        _, output = _direct_run(
            hook,
            {"tool_name": "Bash", "tool_input": {"command": command}},
            monkeypatch,
            capsys,
        )
        assert output.out
    rows = (tmp_path / "tool_usage.jsonl").read_text().splitlines()
    assert len(rows) == len(commands)


def test_negativos_sin_aviso(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_negative")
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    commands = [
        "echo normal",
        "(echo grouped)",
        "echo '&'",
        'echo "nohup"',
        "echo one && echo two",
        "cmd |& tee output",
        "cmd 2>&1",
        "cmd >&1",
        "cmd &>output",
        "cmd &>>output",
        "echo $((1 & 2))",
        "echo $(((1) & 2))",
        "echo $(( 1 & (2+3) ))",
    ]
    for command in commands:
        result, output = _direct_run(
            hook,
            {"tool_name": "Bash", "tool_input": {"command": command}},
            monkeypatch,
            capsys,
        )
        assert result == 0
        assert output.out == ""
    assert not (tmp_path / "tool_usage.jsonl").exists()


def test_aviso_no_bloquea_exit_cero(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_exit")
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    result, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.err == ""
    assert output.out


def test_aviso_esquema_hook_specific_output(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_schema")
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    _, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "setsid echo work"}},
        monkeypatch,
        capsys,
    )
    payload = json.loads(output.out)
    assert set(payload) == {"hookSpecificOutput"}
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert (
        "no habra notificacion al terminar; usa run_in_background o Monitor"
        in specific["additionalContext"]
    )
    assert "permissionDecision" not in payload


def test_aviso_fail_open_excepcion(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_fail_open")
    live_sinks = []
    live_sink = Path(hook.TELEMETRY_FILE)
    live_sinks.append(
        (
            live_sink,
            live_sink.exists(),
            live_sink.stat().st_size if live_sink.exists() else 0,
        )
    )
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    monkeypatch.setattr(
        hook,
        "_detect_detached_launch",
        lambda command: (_ for _ in ()).throw(RuntimeError()),
    )
    result, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.out == ""

    hook = _load(_HOOK, "pretooluse_detached_fail_open_telemetry")
    live_sink = Path(hook.TELEMETRY_FILE)
    live_sinks.append(
        (
            live_sink,
            live_sink.exists(),
            live_sink.stat().st_size if live_sink.exists() else 0,
        )
    )
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    monkeypatch.setattr(
        hook,
        "_record_detached_launch",
        lambda data, signal: (_ for _ in ()).throw(OSError()),
    )
    result, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.out

    hook = _load(_HOOK, "pretooluse_detached_fail_open_print")
    live_sink = Path(hook.TELEMETRY_FILE)
    live_sinks.append(
        (
            live_sink,
            live_sink.exists(),
            live_sink.stat().st_size if live_sink.exists() else 0,
        )
    )
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    monkeypatch.setattr(
        builtins, "print", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError())
    )
    result, _ = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert result == 0
    telemetry = tmp_path / "tool_usage.jsonl"
    assert len(telemetry.read_text().splitlines()) == 1
    for live_sink, existed, size in live_sinks:
        assert live_sink.exists() is existed
        if existed:
            assert live_sink.stat().st_size == size


def test_aviso_unico_por_llamada(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_once")
    monkeypatch.setattr(hook, "TELEMETRY_FILE", tmp_path / "tool_usage.jsonl")
    _, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work &"}},
        monkeypatch,
        capsys,
    )
    assert len(output.out.splitlines()) == 1
    assert len((tmp_path / "tool_usage.jsonl").read_text().splitlines()) == 1


def test_telemetria_una_fila(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_telemetry")
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)
    command = "nohup secret-command --token abc"
    _direct_run(
        hook,
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        },
        monkeypatch,
        capsys,
    )
    row = json.loads(sink.read_text().splitlines()[0])
    assert set(row) == {
        "timestamp",
        "topic",
        "signal",
        "source",
        "tool",
        "context",
        "session_id",
        "call_count",
    }
    assert row["topic"] == "tool_usage"
    assert row["source"] == "pretooluse_bash_wait_guard"
    assert row["tool"] == "Bash"
    assert row["signal"] == "nohup"
    assert row["context"] == "detached_launch nohup"
    assert row["session_id"] == "session-1"
    assert command not in row["signal"]
    assert isinstance(row["call_count"], int)


def test_telemetria_ignorada_por_contract_full_read(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_contract")
    checker = _load(
        _ROOT / "scripts" / "check_contract_full_read.py", "contract_checker"
    )
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)
    _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert checker.load_read_events(tmp_path) == []


def test_telemetria_ruta_compartida():
    hook = _load(_HOOK, "pretooluse_detached_path")
    post = _load(_ROOT / ".agent" / "hooks" / "post_tool_hook.py", "post_tool_path")
    assert hook.TELEMETRY_FILE == post.TELEMETRY_FILE
    assert Path(".agent/runtime/telemetry/tool_usage.jsonl") == hook.TELEMETRY_FILE


def test_fondo_sin_aviso_ni_fila(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_background")
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)
    result, output = _direct_run(
        hook,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "nohup echo work &", "run_in_background": True},
        },
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.out == ""
    assert not sink.exists()


def test_comando_normal_sin_aviso(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_detached_tool_window")
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)
    for payload in (
        {"tool_name": "Bash", "tool_input": {"command": "echo normal"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "nohup echo work"}},
    ):
        result, output = _direct_run(hook, payload, monkeypatch, capsys)
        assert result == 0
        assert output.out == ""
    assert not sink.exists()


def test_session_id_ausente_usa_unknown(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_session_id_default")
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)

    result, output = _direct_run(
        hook,
        {"tool_name": "Bash", "tool_input": {"command": "nohup echo work"}},
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.out
    first = json.loads(sink.read_text().splitlines()[0])
    assert first["session_id"] == "unknown"

    result, output = _direct_run(
        hook,
        {
            "session_id": "session-9",
            "tool_name": "Bash",
            "tool_input": {"command": "nohup echo work"},
        },
        monkeypatch,
        capsys,
    )
    assert result == 0
    assert output.out
    rows = [json.loads(line) for line in sink.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[1]["session_id"] == "session-9"


def test_deteccion_no_corre_en_rutas_de_bloqueo(tmp_path, monkeypatch, capsys):
    hook = _load(_HOOK, "pretooluse_blocking_paths_before_detection")
    sink = tmp_path / "tool_usage.jsonl"
    monkeypatch.setattr(hook, "TELEMETRY_FILE", sink)

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "while true; do sleep 200; sleep 200; done &"
                    },
                }
            )
        ),
    )
    with pytest.raises(SystemExit) as exc:
        hook.main([])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
    assert not sink.exists()

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "nohup echo work",
                        "timeout": 301000,
                    },
                }
            )
        ),
    )
    with pytest.raises(SystemExit) as exc:
        hook.main([])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
    assert not sink.exists()
