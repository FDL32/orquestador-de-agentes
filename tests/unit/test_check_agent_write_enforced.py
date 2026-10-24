"""Barrera WOT-2026-048h: `write: false` sin enforcement posible FALLA nombrando el par.

Cierra la laguna DECLARADA de WOT-2026-048k. El criterio load-bearing es que
solo se vigilan los perfiles con VECTOR REAL (`channel: agent`): un gate que
exigiera `readonly_agent` a un backend HTTP (`channel: api`) seria over-gating,
y un gate que grita donde no hay riesgo acaba con allowlist o desactivado.
"""

from __future__ import annotations

import json

from scripts.check_agent_write_enforced import (
    find_unenforced_pairs,
    has_native_sandbox,
    main,
)


def _cfg(profiles: dict, backends: dict) -> dict:
    return {"ensemble_profiles": profiles, "backends": backends}


def test_agent_profile_without_readonly_agent_is_reported():
    """(2) el par huerfano se NOMBRA: perfil + backend, no un 'hay problemas'.

    Mutation que aisla la rama: si el gate deja de comprobar `readonly_agent`
    (o lo da por bueno cuando falta), esta lista queda vacia y el test cae. El
    fixture tiene UN solo perfil con vector, asi que nada mas puede producir el
    hallazgo.
    """
    cfg = _cfg(
        {"p_agente": {"channel": "agent", "write": False, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    pairs = find_unenforced_pairs(cfg)
    assert len(pairs) == 1, f"el par huerfano debe detectarse: {pairs}"
    assert pairs[0]["profile"] == "p_agente"
    assert pairs[0]["backend"] == "b_sin", (
        "nombrar solo el perfil obliga a buscar el backend a mano"
    )


def test_api_channel_is_not_over_gated():
    """(1) un backend HTTP NO se vigila: no tiene el vector.

    Es la mitad del DoD que evita que el gate se relaje solo. Los cuatro
    perfiles `nan_api` reales van por HTTP, sin system prompt de agente ni
    permisos de FS: exigirles `readonly_agent` seria ruido, y el ruido es como
    mueren los gates.
    """
    cfg = _cfg(
        {"p_http": {"channel": "api", "write": False, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    assert find_unenforced_pairs(cfg) == [], (
        "un backend sin vector no debe exigir enforcement (over-gating)"
    )


def test_agent_with_readonly_agent_passes():
    """Control positivo: con `readonly_agent` declarado, no hay hallazgo."""
    cfg = _cfg(
        {"p_ok": {"channel": "agent", "write": False, "backend": "b_ok"}},
        {"b_ok": {"readonly_agent": "auditor"}},
    )
    assert find_unenforced_pairs(cfg) == []


def test_write_true_is_not_gated():
    """Un perfil que NO declara `write: false` no promete nada que enforcear."""
    cfg = _cfg(
        {"p_rw": {"channel": "agent", "write": True, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    assert find_unenforced_pairs(cfg) == []


def test_undeclared_backend_is_reported_not_silently_passed():
    """Un backend ausente de `backends` se REPORTA, no se da por bueno.

    Sin esto, un typo en `backend:` convertiria el gate en verde mudo -- la
    misma clase de fallo que el ticket denuncia (un guard que no encuentra su
    objeto y pasa).
    """
    cfg = _cfg(
        {"p_typo": {"channel": "agent", "write": False, "backend": "no_existe"}},
        {"b_ok": {"readonly_agent": "auditor"}},
    )
    pairs = find_unenforced_pairs(cfg)
    assert len(pairs) == 1
    assert pairs[0]["backend_declared"] is False


def test_cli_exit_1_on_orphan_and_0_when_clean(tmp_path, capsys):
    """El CLI mapea hallazgo -> exit 1 y limpio -> exit 0."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            _cfg(
                {"p": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {}},
            )
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(bad)]) == 1
    assert "p" in capsys.readouterr().err

    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            _cfg(
                {"p": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {"readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(good)]) == 0


def test_unreadable_config_fails_closed(tmp_path):
    """No poder LEER la config no es estar limpio: exit 2, nunca 0."""
    assert main(["--config", str(tmp_path / "no_existe.json")]) == 2


def test_check_is_wired_into_closeout(tmp_path, monkeypatch):
    """(3) CABLEADO: el gate se INVOCA desde `run_preflight_check` en closeout.

    Es la asercion que lo separa de una norma. Mutation: quitar la llamada de
    `run_preflight_check` deja `llamado` en False, sin que ningun otro test de
    este fichero se entere -- comportamiento y cableado se miden por separado.
    """
    import scripts.prepush_check as pc

    llamado = {"v": False}

    def _spy(root):
        llamado["v"] = True
        return pc.CheckResult(name="spy", passed=True, output="", is_blocking=False)

    ok = pc.CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_portable_memory_archive_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_validate_all",
        "run_closeout_reconciliation_check",
        "run_motor_destination_integration_check",
        "run_contract_formation_check",
        "run_backlog_contract_check",
    ):
        monkeypatch.setattr(pc, fn, lambda *a, **k: ok)
    monkeypatch.setattr(pc, "run_agent_write_enforced_check", _spy)

    pc.run_preflight_check(tmp_path, closeout_mode=True)
    assert llamado["v"] is True, (
        "el gate existe pero nadie lo invoca -> norma, no barrera (DoD punto 3)"
    )


def test_warn_is_visible_not_silent(tmp_path, monkeypatch):
    """El WARN se modela `passed=False` + `is_blocking=False`, nunca `passed=True`.

    `run_preflight_check` imprime `result.output` SOLO si `not result.passed`:
    un WARN con `passed=True` seria INVISIBLE, que es la deuda-invisible que
    estos gates combaten. Mutation: cambiar a `passed=True` deja de reportar el
    par huerfano y esta asercion cae.
    """
    import scripts.prepush_check as pc

    monkeypatch.setattr(
        pc,
        "_MOTOR_ROOT",
        tmp_path,
    )
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {"p_huerfano": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {}},
            )
        ),
        encoding="utf-8",
    )
    r = pc.run_agent_write_enforced_check(tmp_path)
    assert r.passed is False, "un WARN con passed=True seria invisible en el runner"
    assert r.is_blocking is False, "la deuda es PREEXISTENTE: avisa, no bloquea"
    assert "p_huerfano" in r.output, (
        f"debe nombrar el par, no decir 'hay deuda': {r.output}"
    )


def test_dynamic_check_wired_into_preflight_runner(tmp_path, monkeypatch):
    """WOT-2026-086 (DEC-086P10-001): `run_agent_write_enforced_check` tambien
    corre la comprobacion DINAMICA cuando el `readonly_agent` estatico ya paso.

    Mutation que aisla la rama: si el runner deja de llamar a
    `find_dynamic_unenforced_pairs`, este test deja de detectar el agente
    ausente y cae.
    """
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cawe, "_list_agents", lambda executable, cwd: ["build", "manager"]
    )
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is False, (
        "el agente declarado ausente del cwd real debe verse: la restriccion "
        f"era decorativa aunque la estatica pasara: {r.output}"
    )
    assert "auditor" in r.output
    assert r.is_blocking is True, (
        "bucle adversarial WOT-2026-086 (BA30/BA05, CRITICO): esto NO es deuda "
        "preexistente como el WARN estatico -- es un vector de escritura real "
        "confirmado; dejarlo pasar como WARN permitiria el push con la barrera "
        "rota"
    )


def test_dynamic_check_cli_error_never_blocks(tmp_path, monkeypatch):
    """Bucle adversarial WOT-2026-086, SEGUNDA RONDA (sobre el commit que ya
    tenia el fix de arriba): 5/5 lentes convergieron en que este caso SI
    bloqueaba, contradiciendo la propia politica documentada en el commit
    ("medicion fallida no es vector confirmado").

    Causa raiz medida: `find_dynamic_unenforced_pairs` NUNCA propaga la
    excepcion de `_list_agents` -- la captura internamente y la mete en
    `dyn_pairs` con clave `error`. El `try/except` de
    `run_agent_write_enforced_check` (que solo atrapa una excepcion que ya no
    llega) era CODIGO MUERTO, y `dyn_pairs` no vacio se mapeaba entero a
    `is_blocking=True` sin mirar si el elemento traia `error`.

    Mutation que aisla la rama: si el runner deja de distinguir `error` de
    agente-ausente-confirmado (vuelve a tratar TODO `dyn_pairs` como
    confirmado), este test cae porque `is_blocking` pasa a `True`.
    """
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )

    def _boom(executable, cwd):
        raise FileNotFoundError("opencode: no such file or directory")

    monkeypatch.setattr(cawe, "_list_agents", _boom)
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is False, "una medicion fallida sigue siendo visible (no OK mudo)"
    assert r.is_blocking is False, (
        "CLI ausente/roto es MEDICION FALLIDA, no vector confirmado -- "
        f"bloquear aqui rompe pushes legitimos en maquinas sin opencode: {r.output}"
    )
    assert "opencode" in r.output


def test_dynamic_check_confirmed_agent_blocks_even_with_a_measurement_failure(
    tmp_path, monkeypatch
):
    """Control: si HAY un agente confirmado ausente Y ADEMAS otro perfil no se
    pudo medir, el bloqueo por el confirmado no debe degradarse a WARN."""
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_confirmado": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_a",
                        "repo_scope": "destino",
                    },
                    "p_sin_medir": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_b",
                        "repo_scope": "destino",
                    },
                },
                {
                    "b_a": {"executable": "a_exe", "readonly_agent": "auditor"},
                    "b_b": {"executable": "b_exe", "readonly_agent": "auditor"},
                },
            )
        ),
        encoding="utf-8",
    )

    def _fake_list(executable, cwd):
        if executable == "a_exe":
            return ["build", "manager"]  # confirmado: auditor ausente
        raise TimeoutError("b_exe no respondio")

    monkeypatch.setattr(cawe, "_list_agents", _fake_list)
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.is_blocking is True, "un confirmado real no se diluye por otro sin medir"
    assert "p_confirmado" in r.output
    assert "p_sin_medir" in r.output, "la medicion fallida se reporta, no se silencia"


def test_dynamic_check_passes_when_agent_is_present(tmp_path, monkeypatch):
    """Control positivo: con el agente presente en el listado real, no hay WARN
    dinamico (el estatico sigue siendo el unico que puede fallar)."""
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cawe, "_list_agents", lambda executable, cwd: ["build", "auditor", "manager"]
    )
    # Mockear _agent_permission_rules para que no ejecute subprocess contra el
    # backend real. Lista REALISTA (como la medida 2026-10-25 para `auditor`):
    # la generica allow-all SIEMPRE va primero, las especificas la sobreescriben.
    monkeypatch.setattr(
        cawe,
        "_agent_permission_rules",
        lambda executable, cwd, agent_name: [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "bash", "action": "deny", "pattern": "*"},
            {"permission": "task", "action": "deny", "pattern": "*"},
            {"permission": "todowrite", "action": "deny", "pattern": "*"},
        ],
    )
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is True
    assert r.is_blocking is False


class TestNativeSandboxCountsAsEnforcement:
    """Un sandbox nativo del CLI acredita `write: false` (incidente 2026-08-05).

    Contexto medido: una lente `codex` con `write: false` ESCRIBIO en el
    workspace de otra sesion -- reescribio `work_plan.md`, `TURN.md`, `STATE.md`
    y `.session_state.json`. La restriccion era DECORATIVA porque `codex` no
    declara `readonly_agent` (mecanismo de opencode) y nadie miraba otra forma.

    La leccion, y por eso hay tests para AMBAS formas: la lente no fallo por
    inestabilidad, fallo por encargo mal acotado. GLM, sin permisos, ABORTA;
    codex, con permisos, ACTUA. El encargo malo es el mismo; el dano, no.
    """

    def test_codex_style_sandbox_flag_is_accepted(self):
        backend = {"args": ["exec", "--skip-git-repo-check", "--sandbox", "read-only"]}
        assert has_native_sandbox(backend) is True

    def test_short_sandbox_flag_is_accepted(self):
        assert has_native_sandbox({"args": ["exec", "-s", "read-only"]}) is True

    def test_write_capable_sandbox_modes_are_rejected(self):
        """`workspace-write` y `danger-full-access` NO son readonly."""
        for mode in ("workspace-write", "danger-full-access"):
            assert has_native_sandbox({"args": ["exec", "--sandbox", mode]}) is False, (
                f"{mode} permite escribir y no puede acreditar write:false"
            )

    def test_bare_sandbox_flag_acredits_nothing(self):
        assert has_native_sandbox({"args": ["exec", "--sandbox"]}) is False

    def test_claude_style_readonly_tool_allowlist_is_accepted(self):
        backend = {"args": ["-p", "--tools", "Read,Grep,Glob"]}
        assert has_native_sandbox(backend) is True

    def test_tool_allowlist_with_a_mutating_tool_is_rejected(self):
        """Una sola herramienta mutadora en la allowlist reabre el vector."""
        for tool in ("Bash", "Edit", "Write", "Task"):
            backend = {"args": ["-p", "--tools", f"Read,Grep,{tool}"]}
            assert has_native_sandbox(backend) is False, (
                f"{tool} puede mutar el arbol: la allowlist no acredita readonly"
            )

    def test_backend_without_any_enforcement_is_reported(self):
        """Control: sin sandbox ni readonly_agent, el par sigue siendo huerfano."""
        config = {
            "backends": {"x": {"args": ["run"]}},
            "ensemble_profiles": {
                "p": {"backend": "x", "channel": "agent", "write": False}
            },
        }
        pairs = find_unenforced_pairs(config)
        assert [p["profile"] for p in pairs] == ["p"]

    def test_real_config_has_no_unenforced_agent_profiles(self):
        """El repo REAL: ningun perfil con vector queda sin enforcement.

        Este es el test que habria cazado el incidente antes de que ocurriera.
        """
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        config = json.loads(
            (root / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
        )
        pairs = find_unenforced_pairs(config)
        assert pairs == [], (
            f"perfiles con write:false y vector sin enforcement: "
            f"{[p['profile'] for p in pairs]}"
        )


class TestDynamicReadonlyAgentExistence:
    """WOT-2026-086 (DEC-086P10-001): `readonly_agent` DECLARADO no es `readonly_agent`
    QUE EXISTE desde el cwd real de la lente.

    Incidente medido 2026-09-30: `challenger_opencode_glm_5_2` declara
    `readonly_agent: auditor` y `repo_scope: destino`, pero `auditor.md` solo
    vivia en `<motor>/.opencode/agents/`. Con `cwd=<destino>`, `opencode agent
    list` no incluia `auditor` y `opencode run --agent auditor` caia al agente
    por defecto (`build`, con edit+bash). La comprobacion ESTATICA de
    `find_unenforced_pairs` (arriba) pasaba en verde: solo mira si el backend
    DECLARA `readonly_agent`, nunca si existe donde se necesita.
    """

    def test_agent_missing_from_destino_listing_is_reported(self, monkeypatch):
        """El agente declarado NO aparece en el listado del cwd real -> hallazgo.

        Mutation que aisla la rama: si `find_dynamic_unenforced_pairs` deja de
        comparar contra el listado real (o lo da por bueno sin comparar), esta
        lista queda vacia y el test cae.
        """
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }

        def _fake_list(executable, cwd):
            # Simula el listado REAL medido: el destino no tiene `auditor`.
            if str(cwd) == str(destino):
                return ["build", "compaction", "explore", "general", "plan", "manager"]
            return ["build", "compaction", "auditor", "builder", "manager"]

        import scripts.check_agent_write_enforced as cawe

        motor = "C:/fake/motor"
        destino = "C:/fake/destino"
        monkeypatch.setattr(cawe, "_list_agents", _fake_list)
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root=motor, project_root=destino
        )
        assert len(pairs) == 1, f"el agente ausente en destino debe detectarse: {pairs}"
        assert pairs[0]["profile"] == "p_destino"
        assert pairs[0]["missing_agent"] == "auditor"
        assert pairs[0]["cwd"] == destino

    def test_agent_present_in_destino_listing_passes(self, monkeypatch):
        """Control positivo: si el agente SI aparece en el listado real, no hay hallazgo."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }
        monkeypatch.setattr(
            cawe,
            "_list_agents",
            lambda executable, cwd: ["build", "auditor", "manager"],
        )
        # _agent_permission_rules llama subprocess.run directo; hay que
        # mockearlo para que no intente ejecutar el backend real. Lista
        # REALISTA (genérica allow-all primero, especificas que la
        # sobreescriben despues -- formato medido 2026-10-25).
        monkeypatch.setattr(
            cawe,
            "_agent_permission_rules",
            lambda executable, cwd, agent_name: [
                {"permission": "*", "action": "allow", "pattern": "*"},
                {"permission": "edit", "action": "deny", "pattern": "*"},
                {"permission": "bash", "action": "deny", "pattern": "*"},
                {"permission": "task", "action": "deny", "pattern": "*"},
                {"permission": "todowrite", "action": "deny", "pattern": "*"},
            ],
        )
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == []

    def test_profile_without_repo_scope_destino_checks_motor_cwd(self, monkeypatch):
        """Un perfil SIN `repo_scope: destino` se comprueba contra el cwd del motor.

        `resolve_lens_repo_root` (ya existente) decide el cwd real; esta funcion
        no debe re-implementar esa resolucion, solo consumirla.
        """
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_motor": {"channel": "agent", "write": False, "backend": "b_opencode"}
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }
        seen_cwds = []

        def _fake_list(executable, cwd):
            seen_cwds.append(str(cwd))
            return ["build", "auditor", "manager"]

        monkeypatch.setattr(cawe, "_list_agents", _fake_list)
        # mockear _agent_permission_rules para que no ejecute subprocess
        # contra el backend real. Lista REALISTA (ver test anterior).
        monkeypatch.setattr(
            cawe,
            "_agent_permission_rules",
            lambda executable, cwd, agent_name: [
                {"permission": "*", "action": "allow", "pattern": "*"},
                {"permission": "edit", "action": "deny", "pattern": "*"},
                {"permission": "bash", "action": "deny", "pattern": "*"},
                {"permission": "task", "action": "deny", "pattern": "*"},
                {"permission": "todowrite", "action": "deny", "pattern": "*"},
            ],
        )
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == []
        assert seen_cwds == ["C:/fake/motor"], (
            f"sin repo_scope:destino debe consultar el motor, no el destino: {seen_cwds}"
        )

    def test_list_agents_raises_on_nonzero_returncode(self, monkeypatch):
        """Bucle adversarial WOT-2026-086 (5/5 lentes, BA13/BA24/BA30/BA05 con
        severidad CRITICO/ALTO): un CLI que falla (rc!=0) NO debe parsearse
        como listado valido. Un mensaje de error en stdout podria contener por
        casualidad el nombre del agente buscado y producir un FALSO OK del
        gate de seguridad.

        Mutation: quitar la comprobacion de `returncode` hace que este test
        falle (el nombre del agente en el "mensaje de error" se colaria como
        listado valido en vez de lanzar).
        """
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = "auditor: agent not found in this directory\n"
            stderr = "error: unknown command"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._list_agents("opencode", "C:/fake/destino")

    def test_list_agents_parses_stdout_on_success(self, monkeypatch):
        """Control positivo: con rc=0 el parseo normal sigue funcionando."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = "build (primary)\nauditor (primary)\nmanager (primary)\n"
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        names = cawe._list_agents("opencode", "C:/fake/motor")
        assert names == ["build", "auditor", "manager"]

    def test_listing_command_failure_is_reported_not_silently_passed(self, monkeypatch):
        """Si `_list_agents` no puede ejecutarse (CLI ausente, error), se reporta,
        nunca se da por bueno en silencio (misma disciplina fail-closed del resto
        del gate)."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }

        def _boom(executable, cwd):
            raise OSError("opencode no encontrado")

        monkeypatch.setattr(cawe, "_list_agents", _boom)
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 1
        assert pairs[0]["missing_agent"] == "auditor"
        assert "error" in pairs[0]

    def test_static_pass_with_dynamic_fail_is_caught_by_cli(
        self, tmp_path, monkeypatch
    ):
        """Extremo a extremo: la barrera ESTATICA da verde (declara readonly_agent)
        pero la DINAMICA (agente ausente del cwd real) hace fallar el CLI.

        Es exactamente el incidente medido: `find_unenforced_pairs` solo mira si
        se DECLARA; el nuevo paso dinamico mira si EXISTE donde hace falta.
        """
        import scripts.check_agent_write_enforced as cawe

        cfg_path = tmp_path / "agents.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "ensemble_profiles": {
                        "p_destino": {
                            "channel": "agent",
                            "write": False,
                            "backend": "b_opencode",
                            "repo_scope": "destino",
                        }
                    },
                    "backends": {
                        "b_opencode": {
                            "executable": "opencode",
                            "readonly_agent": "auditor",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        # Estatico: pasaria solo (readonly_agent SI declarado).
        assert (
            find_unenforced_pairs(json.loads(cfg_path.read_text(encoding="utf-8")))
            == []
        )

        monkeypatch.setattr(
            cawe, "_list_agents", lambda executable, cwd: ["build", "manager"]
        )
        rc = cawe.main(
            [
                "--config",
                str(cfg_path),
                "--check-dynamic",
                "--motor-root",
                "C:/fake/motor",
                "--project-root",
                "C:/fake/destino",
            ]
        )
        assert rc == 1, "la barrera dinamica debe fallar aunque la estatica pase"


class TestParseAgentPermissionBlocks:
    """WOT-2026-059j: _parse_agent_permission_blocks convierte el stdout crudo
    de `<backend> agent list` en un dict {nombre_agente: [reglas...]}.

    El formato real medido es una cabecera "nombre (primary)" sin indentacion,
    seguida de un bloque JSON tipo array indentado con espacios, hasta una linea
    `]`.
    """

    def test_parses_real_fixture_format(self):
        """Fixture real medido con este repo: dos agentes, cada uno con reglas."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = (
            "build (primary)\n"
            "  [\n"
            "  {\n"
            '    "permission": "*",\n'
            '    "action": "allow",\n'
            '    "pattern": "*"\n'
            "  },\n"
            "  {\n"
            '    "permission": "doom_loop",\n'
            '    "action": "ask",\n'
            '    "pattern": "*"\n'
            "  }\n"
            "]\n"
            "auditor (primary)\n"
            "  [\n"
            "  {\n"
            '    "permission": "*",\n'
            '    "action": "allow",\n'
            '    "pattern": "*"\n'
            "  }\n"
            "]\n"
        )
        result = _parse_agent_permission_blocks(stdout)
        assert "build" in result
        assert "auditor" in result
        assert len(result["build"]) == 2
        assert result["build"][0]["permission"] == "*"
        assert result["build"][0]["action"] == "allow"
        assert result["build"][0]["pattern"] == "*"
        assert len(result["auditor"]) == 1
        assert result["auditor"][0]["permission"] == "*"

    def test_parses_multiple_rules_in_order(self):
        """El orden de las reglas se preserva tal como aparece en el fixture."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = (
            "build (primary)\n"
            "  [\n"
            '  {"permission": "*", "action": "allow", "pattern": "*"},\n'
            '  {"permission": "edit", "action": "deny", "pattern": "*"}\n'
            "]\n"
        )
        result = _parse_agent_permission_blocks(stdout)
        assert len(result["build"]) == 2
        assert result["build"][0]["permission"] == "*"
        assert result["build"][1]["permission"] == "edit"

    def test_empty_block_gives_empty_list(self):
        """Un bloque sin reglas (solo []) -> lista vacia."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = "solo (primary)\n  []\n"
        result = _parse_agent_permission_blocks(stdout)
        assert result["solo"] == []


class TestAgentPermissionRules:
    """_agent_permission_rules obtiene la lista COMPLETA de reglas de un agente.

    Sustituye a `_first_permission_rule` (que devolvia solo rules[0]). Medido
    2026-10-25: rules[0] es un baseline allow-all UNIVERSAL en el formato real
    de `opencode agent list` (build/plan/manager/auditor lo comparten
    identico), asi que mirar solo la primera regla no distingue un agente
    abierto de uno correctamente restringido -- hace falta la lista entera.
    """

    def test_returns_full_rule_list_for_existing_agent(self, monkeypatch):
        """Devuelve TODAS las reglas del agente pedido, no solo la primera."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = (
                "build (primary)\n"
                "  [\n"
                '  {"permission": "*", "action": "allow", "pattern": "*"},\n'
                '  {"permission": "edit", "action": "deny", "pattern": "*"}\n'
                "  ]\n"
            )
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "build")
        assert rules == [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
        ]

    def test_returns_none_for_agent_not_in_listing(self, monkeypatch):
        """El agente no aparece en el listado -> None."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = 'build (primary)\n  [\n  {"permission": "*", "action": "allow", "pattern": "*"}\n  ]\n'
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "no_existe")
        assert rules is None

    def test_returns_empty_list_for_empty_agent_block(self, monkeypatch):
        """Agente con bloque vacio -> lista vacia (existe, sin reglas)."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = "solo (primary)\n  []\n"
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "solo")
        assert rules == []

    def test_raises_on_nonzero_returncode(self, monkeypatch):
        """Un CLI que falla (rc!=0) -> RuntimeError, nunca parsea stdout de error."""
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = "auditor: agent not found in this directory\n"
            stderr = "error: unknown command"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._agent_permission_rules("opencode", "C:/fake", "auditor")

    def test_ignores_nonzero_process_not_parsing_failing_stdout(self, monkeypatch):
        """Bucle adversarial WOT-2026-059j: el stdout de un proceso fallido
        podria contener el nombre del agente buscado por casualidad. Si se
        parsea, se colaria como listado valido -> FALSO OK del gate.

        Mutation: quitar la comprobacion de `returncode` hace que este test
        falle (el nombre del agente en el "mensaje de error" se colaria como
        regla valida).
        """
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = (
                "error: permission denied\n"
                "auditor (primary)\n"
                "  [\n"
                '  {"permission": "*", "action": "allow", "pattern": "*"}\n'
                "  ]\n"
            )
            stderr = "failed"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._agent_permission_rules("opencode", "C:/fake", "auditor")


class TestPermissiveWritePermissions:
    """_permissive_write_permissions resuelve last-match-wins sobre la lista
    COMPLETA de reglas, restringido a los 4 permisos de escritura vigilados.

    Sustituye a `_is_permissive_rule(rules[0])`. MEDIDO 2026-10-25: el formato
    real de `opencode agent list` pone SIEMPRE `{permission: "*", action:
    "allow", pattern: "*"}` como primera regla -- build, plan, manager Y
    auditor lo comparten identico -- y las reglas que SI restringen
    (edit/bash/task/todowrite: deny) vienen despues, sobreescribiendola. Mirar
    solo rules[0] producia FALSO POSITIVO para TODO agente.
    """

    def test_baseline_only_is_fully_permissive(self):
        """Sin ninguna regla especifica que sobreescriba, el baseline allow-all
        deja los 4 permisos de escritura abiertos -- un agente genuinamente sin
        restriccion SI debe detectarse."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [{"permission": "*", "action": "allow", "pattern": "*"}]
        assert _permissive_write_permissions(rules) == [
            "bash",
            "edit",
            "task",
            "todowrite",
        ]

    def test_specific_denies_after_baseline_clear_the_agent(self):
        """Caso REAL medido de `auditor`: baseline allow-all PRIMERO, luego
        edit/bash/task/todowrite: deny -- no debe reportarse nada."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "doom_loop", "action": "ask", "pattern": "*"},
            {"permission": "read", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "glob", "action": "allow", "pattern": "*"},
            {"permission": "bash", "action": "deny", "pattern": "*"},
            {"permission": "task", "action": "deny", "pattern": "*"},
            {"permission": "todowrite", "action": "deny", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == []

    def test_partial_override_names_only_the_open_ones(self):
        """Si solo `edit` tiene override a deny, `bash`/`task`/`todowrite`
        siguen abiertos por el baseline -- deben nombrarse, no silenciarse."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == ["bash", "task", "todowrite"]

    def test_later_rule_overrides_earlier_specific_rule(self):
        """Last-match-wins tambien entre dos reglas ESPECIFICAS del mismo tipo."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "edit", "action": "allow", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == ["edit"]

    def test_none_or_empty_returns_empty_not_permissive(self):
        """Sin datos no se puede afirmar permisividad (ver docstring: `[]`)."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        assert _permissive_write_permissions(None) == []
        assert _permissive_write_permissions([]) == []


class TestPermissiveAgentDetection:
    """WOT-2026-059j: ROJO-a-VERDE -- un readonly_agent declarado y EXISTENTE
    pero con permisos de escritura REALMENTE abiertos debe ser detectado.

    Caso medido ORIGINAL: `challenger_opencode_glm_5_2` (readonly_agent:
    auditor, write: false) tenia como primera regla real {"permission": "*",
    "action": "allow", "pattern": "*"}, identica a la del agente de escritura
    `build`.

    CORRECCION 2026-10-25 (misma sesion, hallazgo NUEVO sobre el mecanismo de
    arriba): esa primera regla allow-all resulto ser UNIVERSAL -- build, plan,
    manager Y auditor la comparten identica en el formato real de `opencode
    agent list` -- asi que mirar solo rules[0] (`_is_permissive_rule`) daba
    FALSO POSITIVO para TODO agente, incluido uno correctamente restringido.
    El fix mira la lista COMPLETA (`_agent_permission_rules` +
    `_permissive_write_permissions`, last-match-wins) para que las reglas
    especificas (edit/bash/task/todowrite: deny) que vienen DESPUES del
    baseline en la misma lista puedan despejar al agente.
    """

    def test_rojo_permissive_agent_detected(self, monkeypatch):
        """Perfil write:false + readonly_agent declarado y EXISTENTE, pero SIN
        ninguna regla especifica que cierre los permisos de escritura ->
        find_dynamic_unenforced_pairs lo lista (agente genuinamente abierto,
        como `build`: solo tiene el baseline allow-all, sin overrides)."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 1, f"debe detectar el agente permisivo: {pairs}"
        assert pairs[0]["profile"] == "challenger_test"
        assert pairs[0]["permissive_agent"] == "auditor"
        assert pairs[0]["open_permissions"] == ["bash", "edit", "task", "todowrite"]

    def test_green_with_baseline_plus_specific_denies_passes(self, monkeypatch):
        """Caso REAL medido 2026-10-25 de `auditor`: baseline allow-all
        PRIMERO (universal en el CLI), edit/bash/task/todowrite: deny
        DESPUES -- no debe generar hallazgo. Este es el caso que la version
        vieja (rules[0] unicamente) marcaba incorrectamente como permisivo."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [
                    {"permission": "*", "action": "allow", "pattern": "*"},
                    {"permission": "edit", "action": "deny", "pattern": "*"},
                    {"permission": "bash", "action": "deny", "pattern": "*"},
                    {"permission": "task", "action": "deny", "pattern": "*"},
                    {"permission": "todowrite", "action": "deny", "pattern": "*"},
                ]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == [], (
            f"baseline + overrides especificos de escritura a deny no debe "
            f"generar hallazgo: {pairs}"
        )

    def test_mutation_isolates_branch(self, monkeypatch):
        """Mutation que aisla la rama _permissive_write_permissions: compara
        baseline (sin mock) contra version mutada (-> []) y exige que los
        resultados SEAN DISTINTOS.

        baseline: no mock _permissive_write_permissions -> la implementacion
            real detecta el agente permisivo -> pairs_baseline == [1 hallazgo].
        mutada: monkeypatch _permissive_write_permissions a [] -> si la rama se
            comenta/quita, el resultado es identico a baseline -> test FALLA.
            Con el fix cableado: pairs_mutada == [] (se pierden los permisivos).
        """
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        # PASO 1: baseline SIN mock _permissive_write_permissions.
        pairs_baseline = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs_baseline) == 1, (
            f"baseline debe detectar el agente permisivo: {pairs_baseline}"
        )
        assert pairs_baseline[0]["permissive_agent"] == "auditor"

        # PASO 2: mutacion -- _permissive_write_permissions SIEMPRE [].
        monkeypatch.setattr(cawe, "_permissive_write_permissions", lambda rules: [])

        pairs_mutada = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs_mutada == [], (
            f"con _permissive_write_permissions forzado a [], no debe haber "
            f"hallazgo: {pairs_mutada}"
        )

        # PASO 3: los resultados SON DISTINTOS -> _permissive_write_permissions
        # es load-bearing. Si se comenta la llamada en
        # find_dynamic_unenforced_pairs, baseline y mutada darian [] y este
        # assert falla.
        assert pairs_baseline != pairs_mutada, (
            "baseline y mutada deben diferir; si son iguales, la rama "
            "_permissive_write_permissions no se ejecuta en "
            "find_dynamic_unenforced_pairs"
        )

    def test_dynamic_cli_fails_with_permissive_agent(
        self, tmp_path, monkeypatch, capsys
    ):
        """Extremo a extremo: el CLI (main con --check-dynamic) retorna 1
        cuando hay un agente permisivo detectado."""
        import scripts.check_agent_write_enforced as cawe

        cfg_path = tmp_path / "agents.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "ensemble_profiles": {
                        "challenger_test": {
                            "channel": "agent",
                            "write": False,
                            "backend": "b_opencode",
                            "repo_scope": "destino",
                        }
                    },
                    "backends": {
                        "b_opencode": {
                            "executable": "opencode",
                            "readonly_agent": "auditor",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        rc = cawe.main(
            [
                "--config",
                str(cfg_path),
                "--check-dynamic",
                "--motor-root",
                "C:/fake/motor",
                "--project-root",
                "C:/fake/destino",
            ]
        )
        assert rc == 1, "el CLI debe fallar con un agente permisivo detectado"
        err = capsys.readouterr().err
        assert "permisiva" in err or "PERMISIVOS" in err, (
            f"el mensaje debe distinguir permisisvo de ausente: {err}"
        )

    def test_mixed_permissive_and_missing_reports_both(self, monkeypatch):
        """Si hay un perfil con agente permisivo y otro con agente ausente,
        ambos se reportan."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_permissive": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_a",
                    "repo_scope": "destino",
                },
                "p_missing": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_b",
                    "repo_scope": "destino",
                },
            },
            "backends": {
                "b_a": {"executable": "opencode", "readonly_agent": "auditor"},
                "b_b": {"executable": "opencode", "readonly_agent": "ghost"},
            },
        }

        def _fake_list_agents(executable, cwd):
            # "ghost" NO aparece en el listado (agente ausente)
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 2
        profiles = {p["profile"] for p in pairs}
        assert "p_permissive" in profiles
        assert "p_missing" in profiles
        permissive_pair = next(p for p in pairs if p["profile"] == "p_permissive")
        missing_pair = next(p for p in pairs if p["profile"] == "p_missing")
        assert permissive_pair["permissive_agent"] == "auditor"
        assert permissive_pair["open_permissions"] == [
            "bash",
            "edit",
            "task",
            "todowrite",
        ]
        assert missing_pair["missing_agent"] == "ghost"
