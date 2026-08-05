"""Barrera WOT-2026-048h: `write: false` sin enforcement posible FALLA nombrando el par.

Cierra la laguna DECLARADA de WOT-2026-048k. El criterio load-bearing es que
solo se vigilan los perfiles con VECTOR REAL (`channel: agent`): un gate que
exigiera `readonly_agent` a un backend HTTP (`channel: api`) seria over-gating,
y un gate que grita donde no hay riesgo acaba con allowlist o desactivado.
"""

from __future__ import annotations

import json

from scripts.check_agent_write_enforced import find_unenforced_pairs, main


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
