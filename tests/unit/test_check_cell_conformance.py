"""Pruebas hermeticas del comprobador de celdas WOT-2026-161l."""

import hashlib
import json
import os
import sqlite3
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
                "payload": {"lineage": {"parentThreadId": "mcp:IM-1"}},
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
                "payload": {"lineage": {"parentThreadId": "mcp:IM-1"}},
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
                "payload": {"lineage": {"parentThreadId": "mcp:OTHER"}},
            }
        ],
    )
    assert _run(registry, store, "--check-pairing") == 2


def test_check_pairing_sin_parent_no_medido(fixtures):
    registry, store = fixtures
    _write_registry(registry, [_session("IM-1", celda=_cell())])
    _write_store(store, [{"thread_id": "thread:delegated-task:one", "payload": {}}])
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


def test_registro_vivo_solo_lectura_no_medido_rc3():
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


def test_contract_error_is_explicit_registry_error():
    from scripts.flight import registry_ops

    with pytest.raises(registry_ops.RegistryError) as caught:
        registry_ops._parse_json_field("{", "celda", dict)
    assert caught.value.code == registry_ops.RC_INVALID
