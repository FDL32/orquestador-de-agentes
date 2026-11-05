"""Pruebas de la caja 4A: heartbeat-check, reloj de tarea y owners D25."""

import importlib.util
import json
from pathlib import Path

import pytest


_BASE_PATH = Path(__file__).with_name("test_flight_stall_check.py")
_BASE_SPEC = importlib.util.spec_from_file_location("heartbeat_test_base", _BASE_PATH)
base = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(base)


@pytest.fixture
def heartbeat_box(tmp_path, monkeypatch):
    """Construye la caja sintetica de 153t sin modificar su fichero de tests."""
    return base.Box(tmp_path, monkeypatch)


def _write_stall_state(box, payload):
    (box.ops / "stall_state.json").write_text(json.dumps(payload), encoding="utf-8")


def test_heartbeat_usa_ts_latido_y_borde_35_minutos(heartbeat_box):
    box = heartbeat_box
    for age, expected_rc in ((34 * 60 + 59, 0), (35 * 60, 0), (35 * 60 + 1, 2)):
        _write_stall_state(box, {"ts_latido": box.clock.now - age})
        result = box.tick("--heartbeat-check")
        assert result.rc == expected_rc
        assert (box.ops / "task_state.json").exists()
        assert "ts_latido" not in json.loads(
            (box.ops / "task_state.json").read_text(encoding="utf-8")
        )


def test_heartbeat_usa_ts_legado_fresco_y_no_escribe_ts_latido(heartbeat_box):
    box = heartbeat_box
    _write_stall_state(box, {"ts": box.clock.now - 35 * 60})

    result = box.tick("--heartbeat-check")

    assert result.rc == 0
    assert "latido-muerto" not in result.keys
    assert "ts_latido" not in box.stall_state()
    assert "ts_tarea" in json.loads(
        (box.ops / "task_state.json").read_text(encoding="utf-8")
    )


def test_heartbeat_ts_legado_viejo_emite_urgente_task(heartbeat_box):
    box = heartbeat_box
    _write_stall_state(box, {"ts": box.clock.now - 35 * 60 - 1})

    result = box.tick("--heartbeat-check")

    assert result.rc == 2
    assert ("latido-muerto", "URGENTE", "task") in result.events
    assert "ts antiguo" in result.sent[0][1]
    assert box.ca_state()["event:latido-muerto"]["owner"] == "task"


def test_heartbeat_ausente_corrupto_y_no_finito_son_urgentes(heartbeat_box):
    box = heartbeat_box
    for payload in (
        {},
        {"ts_latido": "bad"},
        {"ts_latido": True},
        {"ts_latido": float("nan")},
    ):
        _write_stall_state(box, payload)
        result = box.tick("--heartbeat-check")
        assert result.rc == 2
        assert ("latido-muerto", "URGENTE", "task") in result.events
        assert "ts_latido" in result.out

    (box.ops / "stall_state.json").write_text("{broken", encoding="utf-8")
    result = box.tick("--heartbeat-check")
    assert result.rc == 2 and "ts_latido ausente" in result.out


def test_heartbeat_futuro_es_ilegible(heartbeat_box):
    box = heartbeat_box
    _write_stall_state(box, {"ts_latido": box.clock.now + 1})

    result = box.tick("--heartbeat-check")

    assert result.rc == 2
    assert "ts_latido ausente o ilegible" in result.out


def test_heartbeat_dry_run_no_escribe_ni_notifica(heartbeat_box):
    box = heartbeat_box
    _write_stall_state(box, {"ts_latido": box.clock.now - 36 * 60})
    before = (box.ops / "stall_state.json").read_bytes()

    result = box.tick("--heartbeat-check", "--dry-run")

    assert result.rc == 2
    assert result.events == []
    assert result.sent == []
    assert not (box.ops / "task_state.json").exists()
    assert (box.ops / "stall_state.json").read_bytes() == before


def test_heartbeat_no_detectores_y_claves_son_disjuntas(heartbeat_box, monkeypatch):
    box = heartbeat_box

    def fail_detect(*args):
        raise AssertionError("heartbeat-check no debe ejecutar detectores")

    monkeypatch.setattr(box.m, "_detect", fail_detect)
    _write_stall_state(box, {"ts_latido": box.clock.now})
    result = box.tick("--heartbeat-check")

    assert result.rc == 0
    assert all(event[2] != "stall" for event in result.events)
    assert all(event[0] != "tarea-muerta" for event in result.events)


def test_heartbeat_aviso_fallido_se_distingue_del_reloj_viejo(heartbeat_box):
    box = heartbeat_box
    _write_stall_state(box, {"ts_latido": box.clock.now - 36 * 60})
    box.notify_rc = 2

    result = box.tick("--heartbeat-check")

    assert result.rc == 2
    assert len(result.sent) == 1
    assert "ts_latido" in result.sent[0][1]
    assert "rc_aviso=2" in result.out
    assert "ALERT_FALLIDO" in (box.ops / "comms_ledger.jsonl").read_text(
        encoding="utf-8"
    )
    assert "aviso fallido" not in result.sent[0][1]


def test_heartbeat_avisa_aunque_falle_guardado_de_task_state(
    heartbeat_box, monkeypatch
):
    box = heartbeat_box
    _write_stall_state(box, {"ts_latido": box.clock.now - 36 * 60})

    def fail_save(_ts):
        raise OSError("replace denied")

    monkeypatch.setattr(box.m, "_save_task_state", fail_save)
    result = box.tick("--heartbeat-check")

    assert result.rc == 2
    assert "STALL_CHECK_BROKEN: task_state: OSError" in result.out
    assert ("latido-muerto", "URGENTE", "task") in result.events
    assert len(result.sent) == 1


def test_heartbeat_task_state_es_atomico_y_temporal_por_pid(heartbeat_box, monkeypatch):
    box = heartbeat_box
    _write_stall_state(box, {"ts_latido": box.clock.now})
    replaces = []
    real_replace = box.m.os.replace
    monkeypatch.setattr(box.m.os, "getpid", lambda: 6161)
    monkeypatch.setattr(
        box.m.os,
        "replace",
        lambda source, target: (
            replaces.append((Path(source).name, Path(target).name)),
            real_replace(source, target),
        )[1],
    )

    result = box.tick("--heartbeat-check")

    assert result.rc == 0
    assert ("task_state.6161.tmp", "task_state.json") in replaces
    assert not list(box.ops.glob("task_state.*.tmp"))


def test_heartbeat_cli_excluye_baseline_y_self_check(heartbeat_box):
    box = heartbeat_box
    for other in ("--baseline", "--self-check"):
        with pytest.raises(SystemExit) as exc:
            box.m.main(["--heartbeat-check", other])
        assert exc.value.code == 2


def test_heartbeat_cli_exige_ops_y_flight(heartbeat_box):
    with pytest.raises(SystemExit) as exc:
        heartbeat_box.m.main(["--heartbeat-check"])
    assert exc.value.code == 2
