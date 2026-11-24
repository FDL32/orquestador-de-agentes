"""Pruebas hermeticas del comprobador de celdas WOT-2026-161l."""

import hashlib
import importlib.util
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
        "revisor": "claude-sonnet-5",
        "builder": {"name": "codex gpt-5.6-luna", "threadId": builder},
        "lentes": ["glm5.3-flash", "deepseek-v4-flash"],
        "v1": "codex gpt-5.6-luna",
        "nivel": "medio",
        "esfuerzo": "alto",
        "cuenta": {"preferente": "alvarovans", "refugio": "brabander"},
        "fase": ["A", "B", "C", "D"],
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


def _write_agents(path, mutate=None):
    source = (
        Path(checker.__file__).resolve().parents[2]
        / ".agent"
        / "config"
        / "agents.json"
    )
    value = json.loads(source.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run_new(registry, store, agents, flag):
    return checker.main(
        [
            "--registry",
            str(registry),
            "--store",
            str(store),
            "--agents-json",
            str(agents),
            flag,
        ]
    )


def _load_checker_from(path, name):
    """Carga una copia del checker para verificar mutaciones sin tocar el modulo real."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixtures(tmp_path):
    registry, store = tmp_path / "registry.json", tmp_path / "state.sqlite"
    _write_registry(registry, [])
    _write_store(store, [])
    return registry, store


def test_post_cutoff_im_requires_declared_complete_cell(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    _write_registry(
        registry,
        [_session("IM-new", started="2026-11-24T00:00:00+01:00", celda=_cell())],
    )
    assert _run_new(registry, store, agents, "--check-im") == 0

    missing = tmp_path / "agents-missing.json"
    _write_agents(missing, lambda value: value.pop("celdas"))
    assert _run_new(registry, store, missing, "--check-im") == 2

    malformed = [
        lambda value: value["celdas"]["im"]["builder"].update(backend_key="BA-NO"),
        lambda value: value["celdas"]["im"].update(nivel="alto"),
        lambda value: value["celdas"]["im"].update(
            cuenta={"preferente": "otro", "refugio": "brabander"}
        ),
        lambda value: value["celdas"]["im"].update(
            fase_B_subagentes_largos_claude=True
        ),
        lambda value: value["celdas"]["im"].update(fase_aplicable=["A", "E"]),
        lambda value: value["celdas"]["im"].update(fase_aplicable=[{"fase": "A"}]),
    ]
    for index, mutate in enumerate(malformed):
        candidate = tmp_path / f"agents-malformed-{index}.json"
        _write_agents(candidate, mutate)
        assert _run_new(registry, store, candidate, "--check-im") == 2

    divergent = tmp_path / "agents-copy-divergent.json"
    _write_agents(divergent, lambda value: value["celdas"]["im"].update(nivel="alto"))
    assert _run_new(registry, store, divergent, "--check-im") == 2


def test_post_cutoff_tr_uses_declared_models(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    session = _session(
        "TR-new",
        role="triaje",
        started="2026-11-24T00:00:00+01:00",
        celda={"triador": "nan/gemma4", "revisor": "mimo-v2.6-flash"},
    )
    _write_registry(registry, [session])
    assert _run_new(registry, store, agents, "--check-tr") == 0
    session["celda"]["revisor"] = "claude-sonnet-5"
    _write_registry(registry, [session])
    assert _run_new(registry, store, agents, "--check-tr") == 2
    missing = tmp_path / "agents-no-tr.json"
    _write_agents(missing, lambda value: value["celdas"].pop("tr"))
    assert _run_new(registry, store, missing, "--check-tr") == 2


def test_declaration_scope_is_per_mode(fixtures, tmp_path):
    """Cada modo lee solo su celda: --check-im no lee celdas.tr ni al reves.

    Before: la declaracion se validaba entera en cualquier modo con sesion nueva,
        asi que una celda rota marcaba de rojo al comprobador de la otra.
    During: ``_load_cell_declaration`` solo valida las celdas que pide el modo.
    After: celdas.tr ausente deja ``--check-im`` en verde y celdas.im ausente
        deja ``--check-tr`` en verde; cada modo sigue fallando en su propia celda.
    """
    registry, store = fixtures
    no_tr = tmp_path / "agents-scope-no-tr.json"
    _write_agents(no_tr, lambda value: value["celdas"].pop("tr"))
    _write_registry(
        registry,
        [_session("IM-new", started="2026-11-24T00:00:00+01:00", celda=_cell())],
    )
    assert _run_new(registry, store, no_tr, "--check-im") == 0

    no_im = tmp_path / "agents-scope-no-im.json"
    _write_agents(no_im, lambda value: value["celdas"].pop("im"))
    _write_registry(
        registry,
        [
            _session(
                "TR-new",
                role="triaje",
                started="2026-11-24T00:00:00+01:00",
                celda={"triador": "nan/gemma4", "revisor": "mimo-v2.6-flash"},
            )
        ],
    )
    assert _run_new(registry, store, no_im, "--check-tr") == 0
    _write_registry(
        registry,
        [_session("IM-new", started="2026-11-24T00:00:00+01:00", celda=_cell())],
    )
    assert _run_new(registry, store, no_im, "--check-im") == 2


def test_legacy_only_does_not_read_agents_json(fixtures, tmp_path):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-old", celda=_cell())])
    missing = tmp_path / "does-not-exist.json"
    assert (
        checker.main(
            [
                "--registry",
                str(registry),
                "--store",
                str(store),
                "--agents-json",
                str(missing),
                "--check-im",
            ]
        )
        == 0
    )


def test_declared_model_pattern_has_boundaries():
    assert checker._model_pattern("claude-sonnet-5").search("claude-sonnet-5")
    assert checker._model_pattern("claude-sonnet-5").search("claude sonnet 5")
    assert not checker._model_pattern("claude-sonnet-5").search("claude-sonnet-5-5")
    assert not checker._model_pattern("gemma4").search("antigemma4")
    assert not checker._model_pattern("gemma4").search("gemma4flash")


def test_direct_caller_without_declaration_loads_default(fixtures):
    """Un llamador directo sin declaracion mide de verdad (hallazgo V1 MAYOR).

    Before: ``check_im``/``check_tr`` devolvian ``RC_VIOLATION`` a cualquier
        llamador que no aportara ``declaration``; el detector cableado
        ``flight_stall_check.py:1070`` llama ``check_tr`` sin tercer argumento,
        asi que pasaria a avisar "celda triaje no conforme" sobre una celda
        conforme (un guard que miente es peor que un guard ausente).
    During: si el llamador no trae declaracion y alguna sesion sujeta a las
        reglas nuevas lo exige, la resuelve perezosamente desde ``agents.json``
        por defecto; una lectura ilegible sigue siendo violacion cerrada.
    After: la sesion TR conforme con ``started`` ausente da rc 0 por API
        directa, igual que por CLI.
    """
    registry, _store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-direct",
                role="triaje",
                started=None,
                celda={"triador": "nan/gemma4", "revisor": "mimo-v2.6-flash"},
            ),
            _session("IM-direct", started=None, celda=_cell()),
        ],
    )
    sessions = json.loads(Path(registry).read_text(encoding="utf-8"))["sessions"]
    assert checker.check_tr(sessions, "2026-11-15") == 0
    assert checker.check_im(sessions, "2026-11-15") == 0


def test_direct_caller_declaration_unreadable_is_violation_not_exception(
    fixtures, monkeypatch
):
    """La carga perezosa falla cerrada SIN excepcion para el llamador directo.

    Before: la resolucion interna podia elevar ``CellDeclarationError`` fuera de
        ``_run_mode``, que es el unico traductor conocido a rc.
    During: el fallback captura ese error y devuelve ``None``.
    After: los dos modos devuelven rc 2 sin propagar excepcion al consumidor.
    """
    registry, _store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-broken",
                role="triaje",
                started=None,
                celda={"triador": "nan/gemma4", "revisor": "mimo-v2.6-flash"},
            ),
            _session("IM-broken", started=None, celda=_cell()),
        ],
    )
    sessions = json.loads(Path(registry).read_text(encoding="utf-8"))["sessions"]
    monkeypatch.setattr(
        checker, "_default_agents_json_path", lambda: Path("no-existe-221d.json")
    )
    assert checker.check_tr(sessions, "2026-11-15") == 2
    assert checker.check_im(sessions, "2026-11-15") == 2


def test_re_triador_y_revisor_tr_siguen_patrones_de_modulo():
    """Contrato del consumidor fuera del FLT: registry_ops los lee por nombre.

    Before: ``registry_ops._validate_cell_requirements`` usa
        ``checker.RE_TRIADOR`` y ``checker.RE_REVISOR_TR`` como atributos de
        modulo en cada alta de triaje.
    During: los dos patrones siguen existiendo y casan con el par legacy del
        canon P35 sin relajar sus bordes.
    After: los cuatro casos (par legacy y sus dos rechazos tipicos) se cumplen.
    """
    assert checker.RE_TRIADOR.search("nan/gemma4")
    assert not checker.RE_TRIADOR.search("antigemma4")
    assert checker.RE_REVISOR_TR.search("mimo-v2.6-flash")
    assert not checker.RE_REVISOR_TR.search("glm5.3-flash")


def test_post_cutoff_mutation_missing_nivel_is_violation(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    cell = _cell()
    cell.pop("nivel")
    _write_registry(
        registry,
        [
            _session(
                "IM-mutation-nivel", started="2026-11-24T00:00:00+01:00", celda=cell
            )
        ],
    )
    assert _run_new(registry, store, agents, "--check-im") == 2


def test_post_cutoff_mutation_wrong_esfuerzo_is_violation(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    cell = _cell()
    cell["esfuerzo"] = "medio"
    _write_registry(
        registry,
        [
            _session(
                "IM-mutation-esfuerzo", started="2026-11-24T00:00:00+01:00", celda=cell
            )
        ],
    )
    assert _run_new(registry, store, agents, "--check-im") == 2


def test_post_cutoff_mutation_wrong_cuenta_is_violation(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    cell = _cell()
    cell["cuenta"] = {"preferente": "brabander", "refugio": "alvarovans"}
    _write_registry(
        registry,
        [
            _session(
                "IM-mutation-cuenta", started="2026-11-24T00:00:00+01:00", celda=cell
            )
        ],
    )
    assert _run_new(registry, store, agents, "--check-im") == 2


def test_post_cutoff_mutation_missing_v1_is_violation(fixtures, tmp_path):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    cell = _cell()
    cell.pop("v1")
    _write_registry(
        registry,
        [_session("IM-mutation-v1", started="2026-11-24T00:00:00+01:00", celda=cell)],
    )
    assert _run_new(registry, store, agents, "--check-im") == 2


def test_retroactive_cutoff_preserves_legacy_and_rejects_new_contract(
    fixtures, tmp_path
):
    registry, store = fixtures
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    cell = _cell()
    for key in ("nivel", "esfuerzo", "cuenta", "fase", "v1"):
        cell.pop(key)
    _write_registry(
        registry, [_session("IM-old", started="2026-11-10T00:00:00+01:00", celda=cell)]
    )
    assert _run_new(registry, store, agents, "--check-im") == 0
    _write_registry(
        registry, [_session("IM-new", started="2026-11-24T00:00:00+01:00", celda=cell)]
    )
    assert _run_new(registry, store, agents, "--check-im") == 2
    _write_registry(registry, [_session("IM-unknown", started=None, celda=cell)])
    assert _run_new(registry, store, agents, "--check-im") == 2


def test_read_only_conforme_rc0(fixtures):
    registry, store = fixtures
    im = _session("IM-1", celda=_cell())
    tr = _session(
        "TR-1",
        "triaje",
        celda={
            "triador": "gemma4",
            "revisor": "mimo-v2.6-flash",
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
                "TR-1",
                "triaje",
                celda={"triador": "gemma4", "revisor": "mimo-v2.6-flash"},
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
                celda={"triador": "qwen3.8-flash", "revisor": "mimo-v2.6-flash"},
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
        ("revisor", {"a": "mimo-v2.6-flash"}),
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
    ``mimo-v2.6-flash`` en el repr); ahora solo cuenta texto.
    """
    registry, store = fixtures
    celda = {"triador": "gemma4", "revisor": "mimo-v2.6-flash"}
    celda[campo] = valor
    _write_registry(registry, [_session("TR-1", "triaje", celda=celda)])
    assert _run(registry, store, "--check-tr") == 2


@pytest.mark.parametrize(
    ("triador", "revisor", "expected"),
    [
        ("antigemma4", "mimo-v2.6-flash", 2),
        ("gemma4", "antimimo-v2.6-flash", 2),
        ("gemma4", "mimo-v2.6-flashfree", 2),
        ("gemma4", "mimo-v2.5", 2),
        ("gemma4", "glm5.3-flash", 2),
        ("gemma4", "nan/glm5.3-flash", 2),
        ("gemma4", "nan/mimo-v2.6-flash", 0),
        ("gemma4 (kilo)", "mimo-v2.6-flash", 0),
        ("gemma4", "mimo-v2.6-flash", 0),
    ],
    ids=[
        "antigemma4-rc2",
        "antimimo-rc2",
        "mimo-sufijo-largo-rc2",
        "mimo-version-distinta-rc2",
        "glm-antes-valido-rc2",
        "glm-con-prefijo-rc2",
        "mimo-con-prefijo-rc0",
        "gemma-con-sufijo-rc0",
        "par-exacto-rc0",
    ],
)
def test_check_tr_modelos_con_frontera(fixtures, triador, revisor, expected):
    """CO-69 ronda 9: el par TR exige frontera, como codex/sol.

    ``"gemma4" in triador`` aceptaba "antigemma4" y ``"mimo-v2.6-flash" in
    revisor`` aceptaba "antimimo-v2.6-flash"; ambos deben ser violacion.
    WOT-2026-163g: el literal del revisor paso de glm5.3-flash a
    mimo-v2.6-flash y las filas glm pasan de rc 0 a rc 2.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [_session("TR-1", "triaje", celda={"triador": triador, "revisor": revisor})],
    )
    assert _run(registry, store, "--check-tr") == expected


@pytest.mark.parametrize(
    "revisor",
    ["mimo-v2.6-flash", "nan/mimo-v2.6-flash"],
    ids=["mimo-plano", "mimo-con-prefijo-nan"],
)
def test_check_tr_revisor_mimo_rc0(fixtures, revisor):
    """Verify the replacement reviewer model is accepted in both forms.

    Before: the regex matched only ``glm5.3-flash`` and accepted its nan
    prefixed form. During: the d99b0f8a order replaces glm with mimo and the
    checker remains fail-closed for the new exact reviewer model. After: both
    mimo forms return rc 0; with the old regex this test stays red.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-1",
                "triaje",
                celda={"triador": "gemma4", "revisor": revisor},
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 0


@pytest.mark.parametrize(
    "revisor",
    ["glm5.3-flash", "nan/glm5.3-flash"],
    ids=["glm-antes-valido", "glm-con-prefijo-nan"],
)
def test_check_tr_revisor_glm_rc2(fixtures, revisor):
    """Verify the superseded reviewer model is rejected fail-closed.

    Before: the regex matched ``glm5.3-flash`` and its nan prefixed form with
    rc 0. During: order d99b0f8a replaces glm with mimo, so both old forms
    must return rc 2. After: with the old regex this test stays red.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-1",
                "triaje",
                celda={"triador": "gemma4", "revisor": revisor},
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 2


def test_check_tr_accepts_legacy_triador_dict_and_supervisor_alias(fixtures):
    """Accept the legacy TR cell shape without weakening model boundaries.

    Before: legacy TR cells used a ``triador`` dictionary and ``supervisor``
        alias instead of the canonical flat fields.
    During: check_tr reads the builder-style name and the reviewer alias only
        when the explicit reviewer key is absent.
    After: the legacy shape passes while a reviewer model with a bad boundary
        remains a violation.
    """
    registry, store = fixtures
    _write_registry(
        registry,
        [
            _session(
                "TR-legacy",
                "triaje",
                celda={
                    "triador": {"name": "opencode nan/gemma4 hijo"},
                    "supervisor": "opencode nan/mimo-v2.6-flash",
                },
            )
        ],
    )
    assert _run(registry, store, "--check-tr") == 0
    registry.write_text(
        json.dumps(
            {
                "sessions": [
                    _session(
                        "TR-legacy",
                        "triaje",
                        celda={
                            "triador": {"name": "gemma4"},
                            "revisor": "nan/mimo-v2.6-flashfree",
                            "supervisor": "nan/mimo-v2.6-flash",
                        },
                    )
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert _run(registry, store, "--check-tr") == 2


def test_check_lenses_prefers_session_entries_and_normalizes_dicts(fixtures):
    """Use session lenses first and normalize its supported entry shapes.

    Before: check_lenses inspected only ``celda.lentes`` and counted strings.
    During: it selects a non-empty session list, then reads ``modelo`` or
        ``lente`` from dictionaries while preserving textual entries.
    After: two distinct session models pass even when the cell fallback has
        only one lens, and a one-entry session list still fails.
    """
    registry, store = fixtures
    session = _session(
        "TR-lenses",
        "triaje",
        lentes=[{"modelo": "Model-A"}, {"lente": "lens-b"}],
        celda={"lentes": ["only-fallback"]},
    )
    _write_registry(registry, [session])
    assert _run(registry, store, "--check-lenses") == 0
    session["lentes"] = [{"modelo": "Model-A"}]
    _write_registry(registry, [session])
    assert _run(registry, store, "--check-lenses") == 2


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


def test_im_vivos_settled_at_entero_no_medido(fixtures):
    """CO-69 ronda 9: ``settledAt`` entero no puede ocultar un IM vivo.

    ``str(20261110)`` es ISO basico (aceptado desde 3.11) y ``settled()`` daba
    True; con 3 IM ACTIVA y uno "asentado" por ese dato el tope daba rc 0. Ahora
    el dato no textual es NO MEDIDO (rc 3), nunca verde.
    """
    registry, store = fixtures
    _three_ims(registry)
    _write_store(
        store,
        [
            {
                "thread_id": "mcp:IM-0",
                "payload": {"settledAt": 20261110},
            }
        ],
    )
    assert _run(registry, store, "--check-im-vivos") == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"settledAt": 20261110},
        {"settledAt": date(2026, 11, 10)},
        {"settledAt": "2026-11-10T10:00:00Z", "unsettledAt": 20261110},
        {"settledAt": "2026-11-10T10:00:00Z", "unsettledAt": date(2026, 11, 10)},
    ],
    ids=[
        "settled-entero",
        "settled-date",
        "unsettled-entero",
        "unsettled-date",
    ],
)
def test_settled_fecha_no_textual_no_medido(fixtures, monkeypatch, payload):
    """CO-69 ronda 9: fechas de asentamiento no textuales -> MeasurementError.

    El ``date`` cubre la misma clase en Python 3.10 (su ``str`` ya es ISO valido),
    donde el entero no llega a parsear.
    """
    _, store = fixtures
    _write_store(store, [{"thread_id": "t", "payload": {}}])
    connection, _, settled = checker._store_lookup(store)
    try:
        monkeypatch.setattr(checker, "_payload", lambda row: payload)
        with pytest.raises(checker.MeasurementError):
            settled("t")
    finally:
        connection.close()


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


def _r3_hashed_session(tmp_path, kind, agents):
    """Produce una sesion hashada mediante el CLI productivo de altas."""
    from scripts.flight import registry_ops

    registry = tmp_path / f"{kind}-registry.json"
    roster = tmp_path / f"{kind}-roster.json"
    _write_registry(registry, [])
    roster.write_text(
        json.dumps({"active_roles": {"orquestador": {"estado": "ACTIVO"}}}),
        encoding="utf-8",
    )
    args = [
        "alta",
        "--registry",
        str(registry),
        "--roster",
        str(roster),
        "--agents-json",
        str(agents),
        "--code",
        f"R3-{kind}",
        "--role",
        "implantacion" if kind == "im" else "triaje",
        "--slot",
        kind,
        "--thread-id",
        f"thread-{kind}",
        "--started",
        "2026-11-24T10:00:00+01:00",
        "--status",
        "ACTIVA",
        "--by",
        "test",
        "--reason",
        "r3",
        "--orden-message-id",
        "9c01c011-e0c0-414e-87a7-df5b5c02f32c",
        "--motivo",
        "alta r3",
        "--celda-de",
        kind,
        "--apply",
    ]
    assert registry_ops.main(args) == 0
    return registry, json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]


def test_m05_hashed_and_legacy_sessions_are_measured_from_frozen_resolution(tmp_path):
    """Before: altas hashadas y legacy comparten el checker. During: mide IM/TR. After: vigente, vieja y legacy pasan."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    for kind in ("im", "tr"):
        registry, current = _r3_hashed_session(tmp_path, kind, agents)
        assert (
            _run_new(registry, tmp_path / "store.sqlite", agents, f"--check-{kind}")
            == 0
        )
        old_agents = tmp_path / f"{kind}-old.json"
        old_agents.write_bytes(agents.read_bytes())
        changed = json.loads(old_agents.read_text(encoding="utf-8"))
        changed["asignaciones"]["im.revisor"]["candidatos"][0]["model"] = (
            "gemini-old-declaration"
        )
        old_agents.write_text(json.dumps(changed), encoding="utf-8")
        old_registry = tmp_path / f"{kind}-old-registry.json"
        _write_registry(old_registry, [current])
        assert (
            _run_new(
                old_registry,
                tmp_path / "store-old.sqlite",
                old_agents,
                f"--check-{kind}",
            )
            == 0
        )
        legacy_registry = tmp_path / f"{kind}-legacy-registry.json"
        legacy = _session(
            f"legacy-{kind}",
            role="implantacion" if kind == "im" else "triaje",
            started="2026-11-23T10:00:00+01:00",
            celda=_cell()
            if kind == "im"
            else {"triador": "nan/gemma4", "revisor": "mimo-v2.6-flash"},
        )
        post_cutoff = _session(
            f"legacy-new-{kind}",
            role=legacy["role"],
            started="2026-11-24T10:00:00+01:00",
            celda=legacy["celda"],
        )
        _write_registry(legacy_registry, [legacy, post_cutoff])
        assert (
            _run_new(
                legacy_registry,
                tmp_path / f"store-legacy-{kind}.sqlite",
                agents,
                f"--check-{kind}",
            )
            == 0
        )


def test_m05_hashed_negative_cases_fail_closed(tmp_path):
    """Before: el recibo protege la alta. During: muta celda, fuente y recibo. After: cada dano devuelve violacion."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    registry, session = _r3_hashed_session(tmp_path, "im", agents)
    cases = []
    broken_cell = json.loads(json.dumps(session))
    broken_cell["celda"]["v1"] = "otro"
    cases.append(broken_cell)
    malformed = json.loads(json.dumps(session))
    malformed["celda_asignacion"].pop("resolucion")
    cases.append(malformed)
    changed_resolution = json.loads(json.dumps(session))
    changed_resolution["celda_asignacion"]["resolucion"]["puestos"]["im.revisor"][
        "model"
    ] = "otro"
    cases.append(changed_resolution)
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("no es json", encoding="utf-8")
    for index, candidate in enumerate(cases):
        candidate_registry = tmp_path / f"broken-{index}.json"
        _write_registry(candidate_registry, [candidate])
        assert (
            _run_new(
                candidate_registry,
                tmp_path / f"broken-{index}.sqlite",
                agents,
                "--check-im",
            )
            == 2
        )
    assert (
        _run_new(registry, tmp_path / "unreadable.sqlite", unreadable, "--check-im")
        == 2
    )


def test_m05_hashed_tr_negative_cases_fail_closed(tmp_path):
    """Before: TR tambien conserva un recibo hashado. During: corrompe celda y recibo. After: el modo TR falla cerrado."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    _registry, session = _r3_hashed_session(tmp_path, "tr", agents)
    broken_cell = json.loads(json.dumps(session))
    broken_cell["celda"]["revisor"] = "otro"
    malformed = json.loads(json.dumps(session))
    malformed["celda_asignacion"].pop("hash")
    for index, candidate in enumerate((broken_cell, malformed)):
        candidate_registry = tmp_path / f"broken-tr-{index}.json"
        _write_registry(candidate_registry, [candidate])
        assert (
            _run_new(
                candidate_registry,
                tmp_path / f"broken-tr-{index}.sqlite",
                agents,
                "--check-tr",
            )
            == 2
        )


def test_mutation_compare_against_current_hash_breaks_old_session(tmp_path):
    """Before: el control real usa el hash guardado. During: muta copia a exigir hash actual. After: el mutante rechaza la sesion vieja."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    registry, _session_value = _r3_hashed_session(tmp_path, "im", agents)
    changed = json.loads(agents.read_text(encoding="utf-8"))
    changed["asignaciones"]["im.revisor"]["candidatos"][0]["model"] = "mutated-model"
    agents.write_text(json.dumps(changed), encoding="utf-8")
    assert _run_new(registry, tmp_path / "real.sqlite", agents, "--check-im") == 0
    source = Path(checker.__file__).read_text(encoding="utf-8")
    needle = 'if current_hash == receipt["hash"]:'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "check_mutant.py"
    mutant_path.write_text(source.replace(needle, "if True:"), encoding="utf-8")
    spec = __import__("importlib.util").util.spec_from_file_location(
        "checker_mutant", mutant_path
    )
    mutant = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mutant)
    assert (
        mutant.main(
            ["--registry", str(registry), "--agents-json", str(agents), "--check-im"]
        )
        == 2
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("orden.messageId", "no-es-uuid"),
        ("orden.messageId", ""),
        ("orden.messageId", 7),
        ("orden.messageId", None),
        ("hash", "abc"),
        ("hash", "G" * 16),
        ("motivo", ""),
        ("motivo", "   "),
    ],
    ids=[
        "orden-texto",
        "orden-vacio",
        "orden-int",
        "orden-null",
        "hash-corto",
        "hash-no-hex",
        "motivo-vacio",
        "motivo-espacios",
    ],
)
def test_hashed_receipt_fields_fail_closed_for_im_and_main(tmp_path, field, value):
    """Before: el recibo hashado puede venir corrupto. During: altera un campo. After: check_im y CLI devuelven rc 2."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    _registry, session = _r3_hashed_session(tmp_path, "im", agents)
    candidate = json.loads(json.dumps(session))
    if field == "orden.messageId":
        candidate["celda_asignacion"]["orden"]["messageId"] = value
    else:
        candidate["celda_asignacion"][field] = value
    assert checker.check_im([candidate], "2026-11-24", agents_json=agents) == 2
    registry = tmp_path / f"invalid-{field.replace('.', '-')}-{value!s}.json"
    _write_registry(registry, [candidate])
    assert (
        _run_new(registry, tmp_path / f"store-{value!s}.sqlite", agents, "--check-im")
        == 2
    )


def test_hashed_receipt_valid_order_hash_and_reason_remains_conformant(tmp_path):
    """Before: una alta productiva contiene recibo valido. During: mide directo y por CLI. After: ambos devuelven rc 0."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    registry, session = _r3_hashed_session(tmp_path, "im", agents)
    assert checker.check_im([session], "2026-11-24", agents_json=agents) == 0
    assert _run_new(registry, tmp_path / "valid.sqlite", agents, "--check-im") == 0


def test_mutation_receipt_orden_not_validated_accepts_non_uuid(tmp_path):
    """Before: el checker real rechaza orden no UUID. During: copia sin esa validacion. After: el mutante acepta y el real rechaza."""
    agents = tmp_path / "agents.json"
    _write_agents(agents)
    _registry, session = _r3_hashed_session(tmp_path, "im", agents)
    candidate = json.loads(json.dumps(session))
    candidate["celda_asignacion"]["orden"]["messageId"] = "no-es-uuid"
    registry = tmp_path / "mutation-registry.json"
    _write_registry(registry, [candidate])
    assert _run_new(registry, tmp_path / "real.sqlite", agents, "--check-im") == 2
    source = Path(checker.__file__).read_text(encoding="utf-8")
    needle = (
        "if not isinstance(order_id, str) or not resolver.UUID_RE.fullmatch(order_id):"
    )
    assert source.count(needle) == 1
    mutant_path = tmp_path / "checker_order_mutant.py"
    mutant_path.write_text(source.replace(needle, "if False:"), encoding="utf-8")
    (tmp_path / "resolver_asignacion.py").write_text(
        Path(checker.__file__)
        .with_name("resolver_asignacion.py")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    mutant = _load_checker_from(mutant_path, "checker_order_mutant")
    assert mutant.check_im([candidate], "2026-11-24", agents_json=agents) == 0
