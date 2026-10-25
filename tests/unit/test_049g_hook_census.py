"""Tests WOT-2026-049g: censo de barreras por INVOCADORES."""

from __future__ import annotations

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
