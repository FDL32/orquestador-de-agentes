"""Tests de cobertura REAL derivados del panel de asignaciones del vuelo.

Los esperados de eligible_coverage se derivan del panel mediante el resolvedor
real, y cada clausula del DoD se mide contra la configuracion cargada en memoria.
"""
# [NON-REVERSE-CLASSICAL: test de contrato/cobertura nueva]

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402
import ensemble_dispatch as ed  # noqa: E402


_RS_WATCHDOG_MODE = (
    "timeout: watchdog de 1500s vencido sin respuesta de la lente; "
    "arbol de procesos del hijo (pid 4242) matado"
)
_RS_INTERNAL_MODE = (
    "unexpected: RuntimeError: backend CLI sin respuesta tras 900s; arbol de "
    "procesos matado. CAUSA NO DETERMINADA -- comprueba en este orden"
)

_OLD_VIEW = [
    "BA04",
    "BA07",
    "BA258",
    "BA259",
    "BA150",
    "BA151",
    "BA08",
    "BA09",
]


def _config():
    """Carga la configuracion del motor desde un unico punto.

    Before: el test necesita el documento de configuracion vigente.
    During: delega exclusivamente en ``ensemble_dispatch.load_motor_config``.
    After: devuelve la configuracion cargada, susceptible de parche en memoria.
    """
    return ed.load_motor_config()


def _resolver():
    """Carga el resolvedor de asignaciones hermano por ruta absoluta.

    Before: existe ``scripts/flight/resolver_asignacion.py`` en el motor.
    During: crea un modulo desde esa ruta y ejecuta su loader, sin tocar sys.path.
    After: devuelve el modulo del resolvedor listo para cargar o derivar datos.
    """
    resolver_path = SCRIPTS_DIR / "flight" / "resolver_asignacion.py"
    spec = importlib.util.spec_from_file_location(
        "resolver_for_reserve_coverage", resolver_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("no se pudo cargar resolver_asignacion.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _derived_view(config):
    """Deriva la vista elegible usando solo la configuracion recibida.

    Before: ``config`` contiene asignaciones y registro coherentes.
    During: pasa ``config["asignaciones"]`` al resolvedor sin leer disco, para
        que un control positivo pueda parchear el documento completo en memoria.
    After: devuelve la lista de backend_keys que el panel hace elegible.
    """
    return _resolver().derive_eligible(config["asignaciones"], config)


def _entry(config):
    """Obtiene la entrada de cobertura de la fase y autoridad auditadas.

    Before: ``config`` contiene el registro ``ensemble_registry``.
    During: navega hasta la clave canonica de MANAGER_REVIEW en repo_motor.
    After: devuelve el diccionario de cobertura que se debe validar o auditar.
    """
    return config["ensemble_registry"]["eligible_coverage"]["MANAGER_REVIEW:repo_motor"]


def _config_for(view):
    """Prepara la configuracion real o el fixture de la vista antigua.

    Before: ``view`` es ``real`` o ``old`` y la configuracion real es cargable.
    During: conserva la real o clona en profundidad y sustituye solo la vista
        antigua para probar que la semantica no depende de claves concretas.
    After: devuelve una configuracion aislada para el escenario solicitado.
    """
    if view == "real":
        return _config()
    if view == "old":
        config = copy.deepcopy(_config())
        _entry(config)["backend_keys"] = list(_OLD_VIEW)
        return config
    raise ValueError(f"vista desconocida: {view}")


def _emitted(nonce="N1", commit="abc", loop="L700", ts="2026-07-24T10:00:00+00:00"):
    return {
        "ts": ts,
        "issuer_role": "orchestrator",
        "issuer_backend_key": "BA01",
        "issued_before_ts": ts,
        "commit_sha": commit,
        "loop_id": loop,
        "challenge_nonce": nonce,
    }


def _rs_row(backend, *, hang=None, answered=True, nonce="N1", sec=5, commit="abc"):
    """Fila `ronda` con TODOS los campos de SCORECARD_FIELDS (formato real)."""
    row = {k: None for k in ed.SCORECARD_FIELDS}
    row.update(
        ts=f"2026-07-24T10:05:{sec:02d}+00:00",
        event="ronda",
        ticket="WOT-2026-161t",
        rol="challenger",
        task_type="code-review",
        backend="kilo",
        model="x",
        ronda=1,
        outcome=None if answered else "no-aportacion",
        evidencia="hallazgo" if answered else "(respuesta vacia)",
        input_bytes=100,
        context_kind="diff",
        failure_mode=hang,
        latency_ms=1000,
        phase="MANAGER_REVIEW",
        loop_id="UNI-X",
        backend_key=backend,
        commit_sha=commit,
        challenge_nonce=nonce,
        output_chars=50 if answered else 0,
    )
    return row


def _rs_hang(backend, *, times=2, nonce="N1", mode=_RS_WATCHDOG_MODE, start=10):
    return [
        _rs_row(backend, hang=mode, answered=False, nonce=nonce, sec=start + i)
        for i in range(times)
    ]


def audit_real(monkeypatch, rows, config):
    """Ejecuta cle.audit con evidencia parcheada y config recibida.

    Before: ``rows`` tiene la forma de _rs_row, ``config`` es la entrada a
        auditar y monkeypatch esta activo.
    During: parchea _read_scorecard y read_emitted_nonces sin usar disco, y fija
        phase y delivery_authority para activar la cobertura declarada.
    After: devuelve el primer veredicto para el unico commit ``abc``.
    """
    monkeypatch.setattr(cle, "_read_scorecard", lambda root: (list(rows), "x"))
    monkeypatch.setattr(cle, "read_emitted_nonces", lambda root: [_emitted()])
    verdicts = cle.audit(
        Path("dummy"),
        commit_shas=["abc"],
        deliverable_type="code",
        phase="MANAGER_REVIEW",
        delivery_authority="repo_motor",
        config=config,
    )
    return verdicts[0]


def _select_keys(entry):
    """Selecciona las dos primeras claves elegibles de la entrada auditada.

    Before: ``entry`` es una entrada de cobertura validada.
    During: comprueba que la entrada permite construir dos lentes distintas y
        conserva el orden posicional declarado.
    After: devuelve ``(k1, k2)`` sin introducir claves concretas en el test.
    """
    backend_keys = entry["backend_keys"]
    if len(backend_keys) < 2:
        pytest.fail(
            "precondicion: la entrada auditada tiene <2 backend_keys elegibles; "
            "los escenarios de dos lentes distintas no son construibles"
        )
    first, second = backend_keys[:2]
    if first == second:
        pytest.fail(
            "precondicion: la entrada auditada no tiene dos backend_keys distintas; "
            "los escenarios de dos lentes distintas no son construibles"
        )
    return first, second


def _rows_two_answered(k1, k2):
    """Construye dos respuestas sustantivas para dos posiciones elegibles.

    Before: ``k1`` y ``k2`` son claves distintas de la entrada auditada.
    During: crea una ronda respondida para cada clave con el mismo nonce.
    After: devuelve las dos filas que deben satisfacer min_distinct.
    """
    return [_rs_row(k1), _rs_row(k2, sec=6)]


def _rows_second_only(k1, k2):
    """Construye una sola respuesta para la segunda clave posicional.

    Before: ``k1`` y ``k2`` son claves distintas de la entrada auditada.
    During: conserva solo la segunda posicion.
    After: devuelve una ronda, insuficiente para el minimo declarado.
    """
    del k1
    return [_rs_row(k2)]


def _rows_first_only(k1, k2):
    """Construye una sola respuesta para la primera clave posicional.

    Before: ``k1`` y ``k2`` son claves distintas de la entrada auditada.
    During: conserva solo la primera posicion.
    After: devuelve una ronda, insuficiente para el minimo declarado.
    """
    del k2
    return [_rs_row(k1)]


def _rows_second_hung(k1, k2):
    """Construye una respuesta y una segunda ronda colgada.

    Before: ``k1`` y ``k2`` son claves distintas de la entrada auditada.
    During: marca la segunda ronda con el modo watchdog y sin respuesta.
    After: devuelve evidencia donde solo la primera lente puede contar.
    """
    return [
        _rs_row(k1),
        _rs_row(k2, hang=_RS_WATCHDOG_MODE, answered=False, sec=12),
    ]


def _assert_two_answered(verdict, rows, k1, k2):
    """Comprueba que dos respuestas distintas cubren el minimo.

    Before: ``verdict`` procede de dos filas respondidas para ``k1`` y ``k2``.
    During: contrasta claves de filas, veredicto, distincion y minimo aplicado.
    After: demuestra cobertura sin aceptar una tercera clave accidental.
    """
    assert {row["backend_key"] for row in rows} == {k1, k2}
    assert verdict["ok"] is True
    assert sorted(verdict["distinct_backends"]) == sorted([k1, k2])
    assert verdict["min_aplicado"] == 2


def _assert_single(verdict, rows, k1, k2):
    """Comprueba que una unica respuesta no cubre el minimo.

    Before: ``verdict`` procede de una sola fila entre ``k1`` y ``k2``.
    During: contrasta la unica clave contada y el minimo aplicado.
    After: demuestra que una lente aislada no satisface la politica declarada.
    """
    del k1, k2
    expected = rows[0]["backend_key"]
    assert verdict["ok"] is False
    assert verdict["distinct_backends"] == [expected]
    assert verdict["min_aplicado"] == 2


def _assert_hung(verdict, rows, k1, k2):
    """Comprueba que una segunda lente colgada no cuenta ni activa reserva.

    Before: ``verdict`` procede de una respuesta y una ronda watchdog.
    During: contrasta que solo ``k1`` queda contado y que no aparecen campos de
        reserva en una entrada que no declara reservas.
    After: demuestra el tratamiento sustantivo de la ronda colgada.
    """
    del rows
    assert verdict["ok"] is False
    assert verdict["distinct_backends"] == [k1]
    assert k2 not in verdict["distinct_backends"]
    assert "reserve_substitutions" not in verdict
    assert "reserve_exhausted" not in verdict


_SCENARIOS = {
    "c04a": (_rows_two_answered, _assert_two_answered),
    "c04b": (_rows_second_only, _assert_single),
    "c04c": (_rows_second_hung, _assert_hung),
    "c04d": (_rows_two_answered, _assert_two_answered),
    "c04e": (_rows_first_only, _assert_single),
    "c04f": (_rows_second_hung, _assert_hung),
    "c04g": (_rows_two_answered, _assert_two_answered),
    "c04h": (_rows_two_answered, _assert_two_answered),
}


def test_real_entry_matches_derived_view():
    """c-01: la entrada real coincide con la vista derivada del panel.

    Before: se carga la configuracion real a traves de _config.
    During: se deriva la vista sobre el mismo objeto en memoria y se valida
        ademas la declaracion real por la ruta canonica del resolvedor.
    After: backend_keys coincide con derive_eligible sin fijar claves concretas;
        la derivacion no lee disco para permitir el control positivo en memoria.
    """
    config = _config()
    entry = _entry(config)
    assert entry["backend_keys"] == _derived_view(config)
    document, assignments = _resolver().load_declaration()
    assert assignments is document["asignaciones"]


def test_real_entry_is_valid_and_declares_no_reserve():
    """c-02: load_eligible_coverage da la entrada sin reason y sin reserva."""
    config = _config()
    entry = _entry(config)
    assert cle.validate_coverage_entry(entry, config) is None
    loaded, reason, key = cle.load_eligible_coverage(
        config, "MANAGER_REVIEW", "repo_motor"
    )
    assert key == "MANAGER_REVIEW:repo_motor"
    assert reason is None
    assert loaded is not None
    assert "reserve_backend_keys" not in entry
    assert "reserve_after_timeouts" not in entry


def test_real_entry_keeps_other_keys_untouched():
    """c-03: conserva los controles de politica independientes de la vista."""
    config = _config()
    entry = _entry(config)
    assert entry["min_distinct"] == 2
    assert entry["policy"] == "declared"
    assert entry["excluded_backend_keys"] == ["BA05"]
    assert entry["exempt_tickets"] == ["WOT-2026-129d"]


@pytest.mark.parametrize(
    "scenario, view",
    [
        ("c04a", "real"),
        ("c04a", "old"),
        ("c04b", "real"),
        ("c04b", "old"),
        ("c04c", "real"),
        ("c04c", "old"),
        ("c04d", "real"),
        ("c04d", "old"),
        ("c04e", "real"),
        ("c04e", "old"),
        ("c04f", "real"),
        ("c04f", "old"),
        ("c04g", "real"),
        ("c04g", "old"),
        ("c04h", "real"),
        ("c04h", "old"),
    ],
    ids=[
        "c04a-real",
        "c04a-old",
        "c04b-real",
        "c04b-old",
        "c04c-real",
        "c04c-old",
        "c04d-real",
        "c04d-old",
        "c04e-real",
        "c04e-old",
        "c04f-real",
        "c04f-old",
        "c04g-real",
        "c04g-old",
        "c04h-real",
        "c04h-old",
    ],
)
def test_coverage_scenarios(monkeypatch, scenario, view):
    """c-04a..h: mide los sucesores con vista real y fixture antiguo.

    Before: ``scenario`` identifica un constructor y una asercion de la tabla,
        y ``view`` selecciona la entrada real o la antigua.
    During: selecciona claves por posicion, audita filas construidas y aplica
        la asercion asociada sin depender de nombres de claves.
    After: cada caso demuestra la semantica de cobertura que le corresponde.
    """
    config = _config_for(view)
    entry = _entry(config)
    k1, k2 = _select_keys(entry)
    build_rows, check_verdict = _SCENARIOS[scenario]
    rows = build_rows(k1, k2)
    verdict = audit_real(monkeypatch, rows, config)
    check_verdict(verdict, rows, k1, k2)


def test_note_documents_derived_view_and_family_rule():
    """c-05: el note documenta vista derivada, familias y 129r."""
    config = _config()
    entry = _entry(config)
    note = entry["note"]
    for text in (
        "VISTA DERIVADA de asignaciones.lentes_p34",
        "scripts/flight/render_asignaciones.py --apply",
        "BA05 excluida por WOT-2026-129r",
        "WOT-2026-129d exento",
        "min_distinct=2",
        "NO se declara reserva",
        "WOT-2026-152t",
        "La independencia por familia la aplica la coordinadora",
    ):
        assert text in note
    for stale in ("BA02", "BA03", "BA06", "BA254"):
        assert stale not in note
