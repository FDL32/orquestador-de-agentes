"""Barrera WOT-2026-048l: la frescura del checkout PRINCIPAL se COMPRUEBA y se AVISA.

Background medido 2026-08-04: `scripts/sync_principal.py` existe, funciona
(`--apply` hizo fast-forward limpio `abb5a4b -> b2eab7f`) y NADIE lo invoca.
El prompt de cierre lo cita DOS veces (`:114`, `:115`) pero solo para NORMALIZAR
el estado stale, nunca para PRESCRIBIRLO como paso. Cableado real: 0 hits en
`prepush_check.py` y en `.agent/agent_controller.py`; el unico hit de
`.pre-commit-config.yaml` es un COMENTARIO.

Censo SEMANTICO (no solo textual, por el caveat de Codex BA05 en el bucle L810):
`daily_sync_principal.ps1` tambien existe y solo se cita A SI MISMO (3 hits
internos, incluido su propio `Register-ScheduledTask` que el operador debe
lanzar a mano). Ni el nombre ni un equivalente semantico estaban cableados.

CONSECUENCIA MEDIDA, no hipotetica: el principal llevaba `abb5a4b` mientras
`origin/main` iba por `b2eab7f`, y los prompts DIVERGIAN entre checkouts
(297 vs 290 lineas) -- incluido el propio prompt de cierre. El operador paso la
ruta del PRINCIPAL al pedir el cierre; leerlo de ahi habria ejecutado un
contrato obsoleto sin que nada avisara.

DECISION DEL DoD (b), ya resuelta en la ficha y NO re-decidida aqui: el check
**AVISA, no ejecuta**. Ejecutar el sync mutaria un checkout que el operador
puede estar usando; avisar con el comando exacto es la opcion barata y
reversible. Por eso `is_blocking=False` y por eso estos tests aseveran que NO
hay mutacion.
"""

from __future__ import annotations

import scripts.prepush_check as pc


def test_principal_stale_is_reported_and_names_the_fix(tmp_path, monkeypatch):
    """(a)+(c): principal STALE -> el check lo REPORTA y cita el comando exacto.

    Mutation que aisla la rama: si `run_principal_freshness_check` deja de
    consultar el plan (o ignora `action == "advance"`), el output pierde el
    aviso y esta asercion cae. El `passed` NO puede sostener el test: es True en
    ambos casos por diseno (avisa, no bloquea), asi que la unica senal es el
    CONTENIDO del reporte.
    """
    monkeypatch.setattr(
        pc,
        "_principal_sync_plan",
        lambda root: {
            "action": "advance",
            "primary_sha": "abb5a4b",
            "target_sha": "b2eab7f",
        },
    )
    r = pc.run_principal_freshness_check(tmp_path)
    assert r.passed is True, "avisar no es bloquear (DoD b): el cierre no se detiene"
    assert r.is_blocking is False, (
        "mutaria un checkout que el operador puede estar usando"
    )
    assert "abb5a4b" in r.output and "b2eab7f" in r.output, (
        f"el aviso debe decir DE DONDE a DONDE, no solo 'stale': {r.output}"
    )
    assert "sync_principal.py" in r.output, (
        f"un aviso sin el comando exacto obliga a buscarlo: {r.output}"
    )


def test_principal_current_says_so_without_noise(tmp_path, monkeypatch):
    """Control negativo: principal AL DIA -> no inventa un aviso."""
    monkeypatch.setattr(
        pc,
        "_principal_sync_plan",
        lambda root: {
            "action": "already_current",
            "primary_sha": "b2eab7f",
            "target_sha": "b2eab7f",
        },
    )
    r = pc.run_principal_freshness_check(tmp_path)
    assert r.passed is True
    assert "sync_principal.py --apply" not in r.output, (
        f"no debe pedir un sync que no hace falta: {r.output}"
    )


def test_unresolvable_principal_skips_named_not_mute(tmp_path, monkeypatch):
    """Sin principal resoluble -> SKIP NOMBRADO, nunca un verde mudo.

    Un destino que no tiene checkout principal (o un motor sin worktrees) no es
    un fallo; pero callarse convertiria la barrera en la misma clase de defecto
    que este ticket denuncia: un guard que no encuentra su objeto y pasa.
    """
    monkeypatch.setattr(pc, "_principal_sync_plan", lambda root: None)
    r = pc.run_principal_freshness_check(tmp_path)
    assert r.passed is True
    assert r.is_blocking is False
    assert "SKIP" in r.output.upper(), f"el SKIP debe ser explicito: {r.output}"


def test_check_is_wired_into_closeout(tmp_path, monkeypatch):
    """(c) CABLEADO: el check se INVOCA desde run_preflight_check en closeout.

    Es la asercion que separa una barrera de una norma -- y es exactamente lo
    que faltaba: el script existia y funcionaba, pero ningun camino automatico
    lo llamaba. Mutation: quitar la llamada de `run_preflight_check` deja
    `llamado` en False.
    """
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
    monkeypatch.setattr(pc, "run_principal_freshness_check", _spy)

    pc.run_preflight_check(tmp_path, closeout_mode=True)
    assert llamado["v"] is True, (
        "el check existe pero nadie lo invoca -> es una NORMA, no una barrera: "
        "exactamente el defecto que WOT-2026-048l denuncia"
    )
