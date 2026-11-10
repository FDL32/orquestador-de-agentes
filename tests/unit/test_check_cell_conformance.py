"""Pruebas hermeticas del comprobador de celdas WOT-2026-161l."""

import hashlib
import json
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from scripts.flight import check_cell_conformance as checker


def _session(
    code,
    role="implantacion",
    status="ACTIVA",
    started="2026-11-10T10:00:00+01:00",
    **extra,
):
    value = {
        "code": code,
        "role": role,
        "status": status,
        "started": started,
        "threadId": f"mcp:{code}",
    }
    value.update(extra)
    return value


def _cell(builder="thread:delegated-task:one"):
    return {
        "revisor": "nan deepseek-v4-flash",
        "builder": {"name": "codex gpt-5.6-luna", "threadId": builder},
        "lentes": ["glm5.3-flash", "deepseek-v4-flash"],
    }


def _write_registry(path, sessions):
    path.write_text(json.dumps({"sessions": sessions}) + "\n", encoding="utf-8")


def _write_store(path, rows):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS orchestration_v2_projection_threads ("
        "thread_id TEXT PRIMARY KEY, deleted_at TEXT, payload_json TEXT, "
        "provider_instance_id TEXT)"
    )
    for row in rows:
        connection.execute(
            "INSERT INTO orchestration_v2_projection_threads "
            "(thread_id, deleted_at, payload_json, provider_instance_id) VALUES (?,?,?,?)",
            (
                row["thread_id"],
                row.get("deleted_at"),
                json.dumps(row.get("payload", {})),
                row.get("account"),
            ),
        )
    connection.commit()
    connection.close()


def _run(registry, store, *flags):
    return checker.main(["--registry", str(registry), "--store", str(store), *flags])


@pytest.fixture
def fixtures(tmp_path):
    registry, store = tmp_path / "registry.json", tmp_path / "state.sqlite"
    _write_registry(registry, [])
    _write_store(store, [])
    return registry, store


def test_read_only_conforme_rc0(fixtures):
    registry, store = fixtures
    im = _session("IM-1", celda=_cell())
    tr = _session(
        "TR-1",
        "triaje",
        celda={
            "triador": "gemma4",
            "revisor": "glm5.3-flash",
            "lentes": ["glm", "deepseek"],
        },
    )
    old = _session("IM-old", started="2026-11-09T23:59:00+01:00")
    _write_registry(registry, [old, im, tr])
    _write_store(
        store,
        [
            {
                "thread_id": "thread:delegated-task:one",
                "account": "codex-a",
                "payload": {
                    "lineage": {
                        "parentThreadId": "mcp:IM-1",
                        "relationshipToParent": "subagent",
                    }
                },
            }
        ],
    )
    assert _run(registry, store, "--read-only") == 0


def test_no_medido_nunca_verde(tmp_path):
    registry = tmp_path / "missing.json"
    assert checker.main(["--registry", str(registry), "--check-im"]) == 3


def test_registry_none_no_medido_rc3(tmp_path, monkeypatch):
    monkeypatch.delenv("FLIGHT_DIR", raising=False)
    assert checker.main(["--check-im"]) == 3


def test_store_inexistente_no_medido_rc3(fixtures):
    registry, _ = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    assert _run(registry, registry.parent / "missing.sqlite", "--check-pairing") == 3


def test_read_only_no_escribe(fixtures):
    registry, store = fixtures
    session = _session("IM-1", celda=_cell())
    _write_registry(registry, [session])
    _write_store(
        store,
        [
            {
                "thread_id": "thread:delegated-task:one",
                "account": "codex-a",
                "payload": {},
            }
        ],
    )
    before = {
        path: hashlib.sha256(path.read_bytes()).digest() for path in (registry, store)
    }
    _run(registry, store, "--read-only")
    assert before == {
        path: hashlib.sha256(path.read_bytes()).digest() for path in (registry, store)
    }


def test_check_im_celda_valida_rc0(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    assert _run(registry, store, "--check-im") == 0


def test_check_im_sesion_unica_rc2(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("IM-1", celda={"builder": "codex luna", "revisor": "codex luna"})],
    )
    assert _run(registry, store, "--check-im") == 2


def test_check_im_builder_dict_revisor_igual_al_nombre_rc2(fixtures):
    """c-02 (CO-69 ronda 5): con builder dict, la sesion unica se mide por name.

    Comparar contra ``str(builder)`` (el repr del dict) nunca casaba con el
    revisor y la celda daba rc 0: falso verde en la forma que el propio
    comprobador acepta (``_child_id`` lee ``threadId`` del dict).
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "IM-1",
                celda={
                    "revisor": "codex luna",
                    "builder": {
                        "name": "codex luna",
                        "threadId": "thread:delegated-task:x",
                    },
                },
            )
        ],
    )
    assert _run(registry, store, "--check-im") == 2


@pytest.mark.parametrize(
    "revisor",
    [None, 1, {"a": 1}, "   "],
    ids=["null", "numero", "dict", "espacios"],
)
def test_check_im_revisor_no_textual_rc2(fixtures, revisor):
    """Barrido c-02 (CO-69 ronda 7): el revisor debe ser texto identificable.

    Solo un ``str`` con contenido tras ``strip`` cuenta como revisor; ``None``,
    numeros, objetos y solo-espacios no identifican a nadie.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("IM-1", celda={"revisor": revisor, "builder": "codex luna"})],
    )
    assert _run(registry, store, "--check-im") == 2


@pytest.mark.parametrize(
    ("builder", "expected"),
    [
        ("anticodex", 2),
        ("codex luna", 0),
        ("codex-luna", 0),
    ],
    ids=["anticodex-rc2", "codex-espacio-rc0", "codex-guion-rc0"],
)
def test_check_im_builder_codex_con_frontera(fixtures, builder, expected):
    """MINOR-2 (BA03 ronda 7): ``"codex" in lowered`` no tenia frontera.

    Un builder "anticodex" se colaba como codex valido; ahora "codex" exige la
    misma frontera que "sol", y "codex luna" / "codex-luna" siguen valiendo.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "IM-1", celda={"revisor": "nan deepseek-v4-flash", "builder": builder}
            )
        ],
    )
    assert _run(registry, store, "--check-im") == expected


def test_check_im_builder_sol_rc2(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("IM-1", celda={"builder": "codex gpt-5.6-sol", "revisor": "nan"})],
    )
    assert _run(registry, store, "--check-im") == 2


def test_check_im_builder_no_codex_rc2(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("IM-1", celda={"builder": "claude sonnet", "revisor": "nan"})],
    )
    assert _run(registry, store, "--check-im") == 2


def test_check_im_builder_consola_no_es_sol_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "IM-1",
                celda={"builder": "codex/gpt-5.6-consola", "revisor": "nan"},
            )
        ],
    )
    assert _run(registry, store, "--check-im") == 0


def test_check_tr_par_valido_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-1", "triaje", celda={"triador": "gemma4", "revisor": "glm5.3-flash"}
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 0


def test_check_tr_sin_par_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("TR-1", "triaje", celda={"triador": "gemma4"})])
    assert _run(registry, store, "--check-tr") == 2


def test_check_tr_triador_incorrecto_rc2(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-1",
                "triaje",
                celda={"triador": "qwen3.8-flash", "revisor": "glm5.3-flash"},
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 2


def test_check_tr_revisor_incorrecto_rc2(fixtures):
    """CO-69: triador correcto y revisor PRESENTE pero erroneo -> rc 2.

    Antes solo se medía el triador o la ausencia del par; el mutante que borra
    la condición del revisor en ``check_tr`` sobrevivía a la batería focal.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-1",
                "triaje",
                celda={"triador": "gemma4", "revisor": "glm5.2"},
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 2


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("triador", {"a": "gemma4"}),
        ("triador", 1),
        ("revisor", {"a": "glm5.3-flash"}),
        ("revisor", 1),
    ],
    ids=[
        "triador-dict-con-modelo",
        "triador-numero",
        "revisor-dict-con-modelo",
        "revisor-numero",
    ],
)
def test_check_tr_campos_no_textuales_rc2(fixtures, campo, valor):
    """Barrido c-03 (CO-69 ronda 7): triador/revisor deben ser texto.

    Antes se aplicaba ``str(...)`` al valor, asi que un objeto cuyo repr
    contuviera el modelo esperado se colaba (dict con ``gemma4`` o
    ``glm5.3-flash`` en el repr); ahora solo cuenta texto.
    """
    registry, store = fixtures
    celda = {"triador": "gemma4", "revisor": "glm5.3-flash"}
    celda[campo] = valor
    _write_registry(registry, [_session("TR-1", "triaje", celda=celda)])
    assert _run(registry, store, "--check-tr") == 2


def test_check_lenses_dos_rc0(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    assert _run(registry, store, "--check-lenses") == 0


def test_check_lenses_una_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda={"lentes": ["glm"]})])
    assert _run(registry, store, "--check-lenses") == 2


def test_check_lenses_duplicadas_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda={"lentes": ["glm", "glm"]})])
    assert _run(registry, store, "--check-lenses") == 2


def test_check_lenses_triaje_deficientes_rc2(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("TR-1", "triaje", celda={"lentes": ["glm"]})],
    )
    assert _run(registry, store, "--check-lenses") == 2


@pytest.mark.parametrize(
    ("lentes", "expected"),
    [
        ([None, ""], 2),
        (["  ", "x"], 2),
        ([1, 2], 2),
        (["a", "A"], 2),
        (["glm", "deepseek"], 0),
    ],
    ids=["nulos", "espacios", "numeros", "duplicado-casefold", "dos-distintas"],
)
def test_check_lenses_solo_cuenta_lentes_identificables(fixtures, lentes, expected):
    """c-04 (CO-69 ronda 6): ``str(item)`` contaba None/numeros como lentes.

    Solo un ``str`` no vacio tras ``strip()`` es una lente; ``None``, ``""``,
    ``"  "``, numeros y objetos no cuentan, y dos formas ``casefold`` iguales
    son la misma lente.
    """
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda={"lentes": lentes})])
    assert _run(registry, store, "--check-lenses") == expected


def test_check_cutoff_previa_exenta_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session("IM-old", started="2026-11-09T23:59:00+01:00"),
            _session("IM-new", celda=_cell()),
        ],
    )
    assert _run(registry, store, "--check-cutoff") == 0


@pytest.mark.parametrize(
    "started",
    [20261109, date(2026, 11, 9)],
    ids=["entero-json", "objeto-date"],
)
def test_sessions_for_measure_fecha_no_textual_se_mide(started):
    """CO-69 ronda 8: ``started`` no textual no excluye la sesion de la medicion.

    Solo un texto puede conceder la exencion de fecha. ``str(20261109)`` da
    "20261109" (ISO basico aceptado desde 3.11) y el ``date`` reproduce la misma
    clase en 3.10; ambos deben medirse.
    """
    session = _session("IM-1", started=started)
    assert checker._sessions_for_measure([session], "2026-11-10") == [session]
    old_text = _session("IM-old", started="2026-11-09T10:00:00+01:00")
    assert checker._sessions_for_measure([old_text], "2026-11-10") == []


@pytest.mark.parametrize(
    "started",
    [20261109, date(2026, 11, 9)],
    ids=["entero-json", "objeto-date"],
)
def test_check_cutoff_fecha_no_textual_no_es_previa(started):
    """CO-69 ronda 8: ``started`` no textual no cuenta como previa al corte.

    Se llama a ``check_cutoff`` directamente porque un ``date`` no es
    serializable a JSON; el entero cubre la ruta del registry y el ``date`` la
    misma clase en Python 3.10 (su ``str`` ya es ISO valido).
    """
    session = _session("IM-1", started=started)
    assert checker.check_cutoff([session], "2026-11-10") == 3


def test_check_im_no_mide_sesion_previa_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session("IM-old", started="2026-11-09T23:59:00+01:00"),
            _session("IM-new", celda=_cell()),
        ],
    )
    assert _run(registry, store, "--check-im") == 0


def test_check_im_violacion_posterior_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda={"builder": "codex"})])
    assert _run(registry, store, "--check-im") == 2


def test_check_pairing_hijo_propio_rc0(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    _write_store(
        store,
        [
            {
                "thread_id": "thread:delegated-task:one",
                "payload": {
                    "lineage": {
                        "parentThreadId": "mcp:IM-1",
                        "relationshipToParent": "subagent",
                    }
                },
            }
        ],
    )
    assert _run(registry, store, "--check-pairing") == 0


def test_check_pairing_hijo_ajeno_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    _write_store(
        store,
        [
            {
                "thread_id": "thread:delegated-task:one",
                "payload": {
                    "lineage": {
                        "parentThreadId": "mcp:OTHER",
                        "relationshipToParent": "subagent",
                    }
                },
            }
        ],
    )
    assert _run(registry, store, "--check-pairing") == 2


def test_check_pairing_sin_parent_no_medido(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    _write_store(store, [{"thread_id": "thread:delegated-task:one", "payload": {}}])
    assert _run(registry, store, "--check-pairing") == 3


@pytest.mark.parametrize(
    "lineage",
    [
        {"parentThreadId": "mcp:IM-1"},
        {"parentThreadId": "mcp:IM-1", "relationshipToParent": "root"},
    ],
    ids=["ausente", "distinto"],
)
def test_check_pairing_relationship_no_medido(fixtures, lineage):
    """c-12: sin ``relationshipToParent`` o con valor distinto -> NO MEDIDO.

    El almacen real lo guarda en el 100 % de los hijos delegados (583/583); su
    ausencia no es una violacion del emparejamiento, es falta de dato.
    """
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    _write_store(
        store,
        [{"thread_id": "thread:delegated-task:one", "payload": {"lineage": lineage}}],
    )
    assert _run(registry, store, "--check-pairing") == 3


def test_check_pairing_hijo_ausente_rc2(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    assert _run(registry, store, "--check-pairing") == 2


def test_check_pairing_builder_sin_prefijo_no_medido(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("IM-1", celda={"builder": "codex luna"})],
    )
    assert _run(registry, store, "--check-pairing") == 3


def test_check_pairing_builder_dict_thread_sin_prefijo_no_medido(fixtures):
    """c-12 (CO-69 ronda 5): el prefijo exigido se mide tambien con builder dict.

    Sin el guard ``startswith("thread:delegated-task:")`` el hijo se buscaria
    por ``mcp:...`` y el resultado seria un veredicto (rc 2) en vez de NO
    MEDIDO (rc 3), que es lo que el contrato pide cuando la celda no declara un
    hilo delegado medible.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "IM-1",
                celda={
                    "revisor": "nan",
                    "builder": {
                        "name": "codex luna",
                        "threadId": "mcp:no-delegado",
                    },
                },
            )
        ],
    )
    assert _run(registry, store, "--check-pairing") == 3


def test_check_pairing_builder_dict_thread_no_textual_no_medido(fixtures):
    """Barrido c-12 (CO-69 ronda 7): un threadId no textual no es hijo medible.

    Antes ``_child_id`` devolvia el valor del dict tal cual; un entero hacia
    fallar ``startswith`` con un AttributeError que ``_run_mode`` no captura.
    Ahora no hay dato medible: NO MEDIDO.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "IM-1",
                celda={
                    "revisor": "nan",
                    "builder": {"name": "codex luna", "threadId": 123},
                },
            )
        ],
    )
    assert _run(registry, store, "--check-pairing") == 3


def test_store_lookup_settled_fechas_reales(fixtures):
    _, store = fixtures
    _write_store(
        store,
        [
            {"thread_id": "settled", "payload": {"settledAt": "2026-11-10T11:22:00Z"}},
            {
                "thread_id": "unsettled",
                "payload": {
                    "settledAt": "2026-11-10T11:22:00Z",
                    "unsettledAt": "2026-11-10T11:23:00Z",
                },
            },
            {
                "thread_id": "reset-settled",
                "payload": {
                    "settledAt": "2026-11-10T11:24:00Z",
                    "unsettledAt": "2026-11-10T11:23:00Z",
                },
            },
            {"thread_id": "live", "payload": {}},
        ],
    )
    connection, _, settled = checker._store_lookup(store)
    try:
        assert settled("settled") is True
        assert settled("unsettled") is False
        assert settled("reset-settled") is True
        assert settled("live") is False
    finally:
        connection.close()


def test_store_lookup_settled_deleted_y_status_legacy(fixtures):
    _, store = fixtures
    _write_store(
        store,
        [
            {
                "thread_id": "deleted",
                "deleted_at": "2026-11-10T11:22:00Z",
                "payload": {},
            },
            {"thread_id": "status", "payload": {"status": "settled"}},
        ],
    )
    connection, _, settled = checker._store_lookup(store)
    try:
        assert settled("deleted") is True
        assert settled("status") is True
    finally:
        connection.close()


def test_check_pairing_consulta_sqlite_error_no_medido(fixtures, monkeypatch):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])

    def fail(*args):
        raise sqlite3.OperationalError("consulta rota")

    monkeypatch.setattr(checker, "_thread_row", fail)
    assert _run(registry, store, "--check-pairing") == 3


def _three_ims(registry):
    _write_registry(
        registry,
        [
            _session(f"IM-{i}", celda=_cell(f"thread:delegated-task:{i}"))
            for i in range(3)
        ],
    )


def test_im_vivos_tres_rc_no_cero(fixtures):
    registry, store = fixtures
    _three_ims(registry)
    assert _run(registry, store, "--check-im-vivos") == 2


def test_im_vivos_dos_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(f"IM-{i}", celda=_cell(f"thread:delegated-task:{i}"))
            for i in range(2)
        ],
    )
    assert _run(registry, store, "--check-im-vivos") == 0


def test_im_vivos_descuenta_hilo_settled_real_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [_session(f"IM-{index}") for index in range(3)],
    )
    _write_store(
        store,
        [
            {
                "thread_id": "mcp:IM-0",
                "payload": {"settledAt": "2026-11-10T11:22:00Z"},
            }
        ],
    )
    assert _run(registry, store, "--check-im-vivos") == 0


def test_im_cuentas_misma_cuenta_rc_no_cero(fixtures):
    registry, store = fixtures
    sessions = [
        _session(f"IM-{i}", celda=_cell(f"thread:delegated-task:{i}")) for i in range(2)
    ]
    _write_registry(registry, sessions)
    _write_store(
        store,
        [
            {
                "thread_id": f"thread:delegated-task:{i}",
                "account": "codex-same",
                "payload": {"modelSelection": {"model": f"model-{i}"}},
            }
            for i in range(2)
        ],
    )
    assert _run(registry, store, "--check-im-cuentas") == 2


def test_im_cuentas_distintas_rc0(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(f"IM-{i}", celda=_cell(f"thread:delegated-task:{i}"))
            for i in range(2)
        ],
    )
    _write_store(
        store,
        [
            {
                "thread_id": f"thread:delegated-task:{i}",
                "account": f"codex-{i}",
                "payload": {},
            }
            for i in range(2)
        ],
    )
    assert _run(registry, store, "--check-im-cuentas") == 0


def test_im_cuentas_builder_dict_sin_prefijo_no_medido(fixtures):
    """c-17 (CO-69 ronda 7): sin prefijo delegated-task la cuenta no se mide.

    ``check_im_cuentas`` usaba ``_child_id`` sin exigir el prefijo que si exige
    ``check_pairing``: dos IM con ``builder.threadId = "mcp:..."`` y cuentas
    distintas daban rc 0 sin ser hijos delegated-task. Ahora es NO MEDIDO.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                f"IM-{i}",
                celda={
                    "revisor": "nan",
                    "builder": {
                        "name": "codex luna",
                        "threadId": f"mcp:otro-{i}",
                    },
                },
            )
            for i in range(2)
        ],
    )
    _write_store(
        store,
        [
            {
                "thread_id": f"mcp:otro-{i}",
                "account": f"codex-{i}",
                "payload": {},
            }
            for i in range(2)
        ],
    )
    assert _run(registry, store, "--check-im-cuentas") == 3


def test_im_status_settled_en_registry_no_es_vivo(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session("IM-109", status="settled", celda=_cell()),
            _session("IM-110", status="ASENTADA: done", celda=_cell()),
        ],
    )
    assert _run(registry, store, "--check-im-vivos") == 0


def test_is_im_vivo_vocabulario_real():
    dead = [
        "SETTLED (hilo completed y asentado ...)",
        "settled",
        "RELEVADA por IM-8 / NO_REABRIR",
        "CERRADA, sin trabajo",
        "COMPLETADA e INTEGRADA en la rama del vuelo",
        "ENTREGADO, SIN INTEGRAR",
        "ASENTADA: ...",
        "ASENTADA (...)",
        "FALLIDA (contexto agotado)",
    ]
    sessions = [
        _session(f"dead-{index}", status=status) for index, status in enumerate(dead)
    ]
    sessions += [
        _session("live-1", status="ACTIVA"),
        _session("live-2", status="ACTIVA (ACK medido ... )"),
    ]
    live = checker.live_ims(sessions, lambda thread_id: False)
    assert [session["code"] for session in live] == ["live-1", "live-2"]


def test_check_cutoff_violation_guard_regression(fixtures, monkeypatch):
    registry, store = fixtures
    sessions = [
        _session("old", started="2026-11-09T23:59:00+01:00"),
        _session("new", celda=_cell()),
    ]
    _write_registry(registry, sessions)
    monkeypatch.setattr(checker, "_sessions_for_measure", lambda value, cutoff: value)
    assert _run(registry, store, "--check-cutoff") == 2


def test_im_vivos_ignora_orquestadora_sin_started(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "OR-5",
                role="orquestadora",
                status="DESACTIVADA (sin trabajo)",
                started=None,
            ),
            _session("IM-111", celda=_cell()),
        ],
    )
    assert _run(registry, store, "--check-im-vivos") == 0


def test_started_ausente_en_im_y_tr_se_mide_fail_closed(fixtures):
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session("IM-1", started=None),
            _session(
                "TR-1",
                role="triaje",
                started=None,
                celda={"triador": "gemma4", "revisor": "glm5.3-flash"},
            ),
        ],
    )
    assert _run(registry, store, "--check-im") == 2
    _write_registry(
        registry,
        [
            _session("IM-1", started=None, celda=_cell()),
            _session(
                "TR-1",
                role="triaje",
                started=None,
                celda={"triador": "gemma4", "revisor": "glm5.3-flash"},
            ),
        ],
    )
    assert _run(registry, store, "--check-im") == 0


def test_registro_vivo_solo_lectura_mide_rc_distinto_de_3():
    candidates = []
    flight_dir = os.environ.get("FLIGHT_DIR")
    if flight_dir:
        candidates.append(Path(flight_dir) / "session_registry.json")
    project_root = os.environ.get("AGENT_PROJECT_ROOT")
    if project_root:
        candidates.extend(
            (Path(project_root) / ".agent" / "runtime").rglob("session_registry.json")
        )
    registry = next((path for path in candidates if path.is_file()), None)
    if registry is None:
        pytest.skip("no hay session_registry.json vivo disponible")
    store = Path(
        os.environ.get(
            "T3_STATE_DB", Path.home() / ".t3" / "userdata" / "statev2.sqlite"
        )
    )
    if not store.is_file():
        pytest.skip("no hay statev2.sqlite vivo disponible")
    before = hashlib.sha256(registry.read_bytes()).digest()
    assert _run(registry, store, "--check-im-vivos") != 3
    assert _run(registry, store, "--check-cutoff") != 3
    assert hashlib.sha256(registry.read_bytes()).digest() == before


def test_policy_declara_comprobador_wired():
    from scripts.check_guard_wiring import _load_policy

    policy = _load_policy(Path("scripts/guard_wiring_policy.yaml"))
    entry = policy["wired_via"].get("check_cell_conformance")
    assert entry
    assert "Probe:" in entry
    assert "flight_stall_check.py" in entry
    assert "check_cell_conformance.py|live_ims" in entry


def test_c09_canon_pilares_declara_cuatro_filas():
    path = (
        Path(__file__).parents[2] / ".agent" / "rules" / "common" / "vuelo_pilares.md"
    )
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^. P3[0456] ", line)
    ]
    assert len(lines) == 4
    assert all("check_cell_conformance" in line for line in lines)
    # CO-69 (WOT-2026-161l): las cuatro filas conservan las SIETE celdas de la
    # tabla y ninguna vacia; el mutante que borra una celda (p.ej. la columna
    # `fuente larga`) hace caer esta asercion.
    for line in lines:
        cells = line.strip().split("|")[1:-1]
        assert len(cells) == 7, f"fila con {len(cells)} celdas: {line[:24]}"
        assert all(cell.strip() for cell in cells), f"celda vacia en: {line[:24]}"


def test_contract_error_is_explicit_registry_error():
    from scripts.flight import registry_ops

    with pytest.raises(registry_ops.RegistryError) as caught:
        registry_ops._parse_json_field("{", "celda", dict)
    assert caught.value.code == registry_ops.RC_INVALID
