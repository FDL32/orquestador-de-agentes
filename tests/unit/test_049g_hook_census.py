"""Tests WOT-2026-049g: censo de barreras por INVOCADORES."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_guard_wiring as cgw


def _make_motor(root: Path, config_yaml: str, extra_scripts: dict[str, str]) -> Path:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / ".pre-commit-config.yaml").write_text(config_yaml, encoding="utf-8")
    for name, content in extra_scripts.items():
        (root / "scripts" / name).write_text(content, encoding="utf-8")
    return root


CONFIG_UNREGISTERED = (
    "repos:\n"
    "  - repo: local\n"
    "    hooks:\n"
    "      - id: foo-hook\n"
    "        entry: python scripts/foo.py\n"
    "        language: system\n"
    "        pass_filenames: false\n"
    "        always_run: true\n"
    "        stages: [pre-commit]\n"
)


REAL_SETTINGS_COMMANDS = [
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'claude_guard_entry.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'claude_guard_entry.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('SECURITY HOOK INACTIVE: claude_guard_entry.py not found; write blocked (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'native_post_tool_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'native_post_tool_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('HOOK INACTIVE: native_post_tool_hook.py not found; hook failed (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'pre_compact_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'pre_compact_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('HOOK INACTIVE: pre_compact_hook.py not found; hook failed (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'scripts'/'encoding_post_write_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'scripts'/'encoding_post_write_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('HOOK INACTIVE: encoding_post_write_hook.py not found; hook failed (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'native_stop_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'native_stop_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('HOOK INACTIVE: native_stop_hook.py not found; hook failed (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'subagent_stop_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'subagent_stop_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else (sys.stderr.write('HOOK INACTIVE: subagent_stop_hook.py not found; hook failed (fail-closed).'),sys.exit(2))\"",
    "python -c \"import sys,json,subprocess; from pathlib import Path; r=next((p for p in [Path('.').resolve()]+list(Path('.').resolve().parents) if (p/'.claude').exists()),Path('.').resolve()); e=r/'.agent'/'hooks'/'session_start_hook.py'; l=r/'.agent'/'config'/'motor_destination_link.json'; e=e if e.exists() else ((Path(json.loads(l.read_text(encoding='utf-8-sig'))['motor_root'])/'.agent'/'hooks'/'session_start_hook.py') if l.exists() else e); sys.exit(subprocess.run([sys.executable,str(e)],input=sys.stdin.buffer.read(),cwd=str(r)).returncode) if e.exists() else print(json.dumps({'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':'Memoria del proyecto NO disponible en este arranque: session_start_hook.py no encontrado en este destino (ni via motor_destination_link.json). Sesion continua sin contexto automatico (fail-open deliberado, WOT-2026-058a). Carga manual: python scripts/memory_context.py --bootstrap si el script existe.'},'systemMessage':'SessionStart degradado: hook de memoria ausente en este destino; la sesion continua sin memoria automatica (fail-open deliberado, WOT-2026-058a).'}))\"",
]


def _write_settings(root: Path, commands: list[str]) -> None:
    settings = {
        "hooks": {
            f"Event{i}": [{"hooks": [{"type": "command", "command": command}]}]
            for i, command in enumerate(commands)
        }
    }
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8"
    )


def test_049g_settings_realistic_seven_commands_are_exactly_seven_hooks(
    tmp_path: Path,
) -> None:
    """D1 control: seven literal production commands yield seven real files."""
    for relative in (
        ".agent/hooks/claude_guard_entry.py",
        ".agent/hooks/native_post_tool_hook.py",
        ".agent/hooks/pre_compact_hook.py",
        ".agent/hooks/native_stop_hook.py",
        ".agent/hooks/subagent_stop_hook.py",
        ".agent/hooks/session_start_hook.py",
        "scripts/encoding_post_write_hook.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
    _write_settings(tmp_path, REAL_SETTINGS_COMMANDS)

    census = cgw.census_hooks(tmp_path)

    settings_hooks = {
        script
        for script, invokers in census.items()
        if any(i["source"] == ".claude/settings.json" for i in invokers)
    }
    assert len(settings_hooks) == 7
    assert "scripts/memory_context.py" not in settings_hooks
    assert "scripts/encoding_post_write_hook.py" in settings_hooks
    assert ".agent/hooks/session_start_hook.py" in settings_hooks


def test_049g_nested_settings_script_is_censed(tmp_path: Path) -> None:
    """D2 control: a nested scripts/tools path remains a full relative key."""
    nested = tmp_path / "scripts" / "tools" / "deep.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("# fixture\n", encoding="utf-8")
    _write_settings(tmp_path, ["python scripts/tools/deep.py"])

    assert "scripts/tools/deep.py" in cgw.census_hooks(tmp_path)


def test_049g_cli_project_root_forwards_destination_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """D3 control: the real CLI path includes the destination census."""
    motor = tmp_path / "motor"
    destination = tmp_path / "destination"
    motor.mkdir()
    _write_settings(destination, [REAL_SETTINGS_COMMANDS[0]])
    hook = destination / ".agent" / "hooks" / "claude_guard_entry.py"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("# fixture\n", encoding="utf-8")
    _write_settings(motor, [])

    captured: dict[str, object] = {}

    def report(root, policy, enforce=False, project_root=None):
        captured["census"] = cgw.census_hooks(root, project_root)
        return 0

    monkeypatch.setattr(cgw, "hook_census_report", report)
    assert (
        cgw.main(
            [
                "--motor-root",
                str(motor),
                "--hook-census",
                "--project-root",
                str(destination),
            ]
        )
        == 0
    )
    census = captured["census"]
    assert census[".agent/hooks/claude_guard_entry.py"] == [
        {"source": ".claude/settings.json", "stage": "claude-hook"}
    ]


def test_049g_cli_enforce_keeps_report_rc_contract(tmp_path: Path) -> None:
    """D4 control: only --enforce turns an unknown local hook into rc 1."""
    _make_motor(tmp_path, CONFIG_UNREGISTERED, {"foo.py": "# fixture\n"})

    assert cgw.main(["--motor-root", str(tmp_path), "--hook-census"]) == 0
    assert cgw.main(["--motor-root", str(tmp_path), "--hook-census", "--enforce"]) == 1


def test_049g_mutation_unregistered_local_hook_rc1(tmp_path: Path) -> None:
    """DoD mutation: hook local -> scripts/foo.py sin prefijo ni registro ->
    enforce rc 1 (barrera invisible detectada)."""
    _make_motor(tmp_path, CONFIG_UNREGISTERED, {"foo.py": "x"})
    policy = {
        "known_hooks": [],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    assert cgw.hook_census_report(tmp_path, policy, enforce=True) == 1


def test_049g_mutation_registered_hook_rc0(tmp_path: Path) -> None:
    """DoD mutation: el mismo hook registrado en known_hooks -> rc 0."""
    _make_motor(tmp_path, CONFIG_UNREGISTERED, {"foo.py": "x"})
    policy = {
        "known_hooks": ["foo"],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    assert cgw.hook_census_report(tmp_path, policy, enforce=True) == 0


def test_049g_prefix_guard_is_recognized(tmp_path: Path) -> None:
    """Los prefijos canonicos siguen reconocidos (GUARD_PREFIXES intacto)."""
    _make_motor(
        tmp_path,
        CONFIG_UNREGISTERED.replace("scripts/foo.py", "scripts/check_foo.py"),
        {"check_foo.py": "x"},
    )
    policy = {
        "known_hooks": [],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    assert cgw.hook_census_report(tmp_path, policy, enforce=True) == 0


def test_049g_remote_repo_hooks_out_of_denominator(tmp_path: Path) -> None:
    """Decision 2: hooks de repos REMOTOS quedan fuera del denominador."""
    config = (
        "repos:\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
        "    rev: v1.0.0\n"
        "    hooks:\n"
        "      - id: trailing-whitespace\n"
    )
    _make_motor(tmp_path, config, {})
    policy = {
        "known_hooks": [],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    census = cgw.census_hooks(tmp_path)
    assert census == {}
    assert cgw.hook_census_report(tmp_path, policy, enforce=True) == 0


def test_049g_report_mode_never_fails(tmp_path: Path) -> None:
    """Condicion 3 de la orquestadora: modo informe rc 0 SIEMPRE (la
    activacion de rc 1 es solo con --enforce y tras clasificacion)."""
    _make_motor(tmp_path, CONFIG_UNREGISTERED, {"foo.py": "x"})
    policy = {
        "known_hooks": [],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    assert cgw.hook_census_report(tmp_path, policy, enforce=False) == 0


def test_049g_real_tree_three_cases_visible(tmp_path: Path) -> None:
    """DoD: los 3 casos de la ficha VISIBLES con su invocador real en el
    arbol real (motor + destino claude settings)."""
    motor = Path(__file__).resolve().parent.parent.parent
    destino = (
        motor.parent.parent.parent
        / "orquestador_de_agentes_workspace"
        / "nocturno-brabander-20261024"
    )
    census = cgw.census_hooks(motor, destino if destino.is_dir() else None)
    # Caso 1: pip_audit_project [pre-push] via pre-commit.
    assert "scripts/pip_audit_project.py" in census
    stages_pa = {i["stage"] for i in census["scripts/pip_audit_project.py"]}
    assert any("pre-push" in s for s in stages_pa)
    # Caso 2: claude_guard_entry [claude-hook] via .claude/settings.json del destino.
    assert ".agent/hooks/claude_guard_entry.py" in census
    # Caso 3: prepush_check [closeout] y SIN stage pre-push (los dos hechos
    # ciertos a la vez que wired/unwired no puede representar).
    assert "scripts/prepush_check.py" in census
    stages_pc = {i["stage"] for i in census["scripts/prepush_check.py"]}
    sources_pc = {i["source"] for i in census["scripts/prepush_check.py"]}
    assert "closeout" in stages_pc
    assert "pre-push" not in stages_pc
    assert any("gates.py" in s for s in sources_pc)


def test_049g_r3_comment_mention_is_not_invocation(tmp_path: Path) -> None:
    """Ronda 3 (hallazgo Codex): un COMENTARIO que menciona foo.py no es una
    invocacion; la linea de codigo real si se censada."""
    config = (
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: real\n"
        "        entry: python scripts/check_real.py\n"
        "        language: system\n"
        "        stages: [pre-commit]\n"
    )
    _make_motor(
        tmp_path,
        config,
        {
            "check_real.py": "x",
            "foo.py": "x",
            "prepush_check.py": "x",
        },
    )
    # Comentario en un modulo de closeout que menciona foo.py: NO invoca.
    closeout = tmp_path / "scripts" / "closeout_steps"
    closeout.mkdir(parents=True, exist_ok=True)
    (closeout / "gates.py").write_text(
        "# comment mentions foo.py only\nfrom prepush_check import x\n",
        encoding="utf-8",
    )
    policy = {
        # prepush_check registrado por clase (los 3 casos de la ficha viven en
        # known_hooks del policy real); foo.py queda SIN registrar para probar
        # que el comentario no lo hace invocado y que enforce lo cazaria.
        "known_hooks": ["prepush_check"],
        "known_unwired": {},
        "extra_guards": {},
        "wired_via": {},
    }
    census = cgw.census_hooks(tmp_path)
    assert "scripts/foo.py" not in census
    assert "scripts/check_real.py" in census
    assert "prepush_check.py" in census
    assert cgw.hook_census_report(tmp_path, policy, enforce=True) == 0


def test_049g_r3_workflows_yaml_extension(tmp_path: Path) -> None:
    """Ronda 3 (hallazgo Codex): los workflows .yaml tambien se censan."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yaml").write_text(
        "jobs:\n  a:\n    steps:\n      - run: python scripts/foo.py\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("x", encoding="utf-8")
    census = cgw.census_hooks(tmp_path)
    assert "scripts/foo.py" in census
    assert any("ci.yaml" in i["source"] for i in census["scripts/foo.py"])
