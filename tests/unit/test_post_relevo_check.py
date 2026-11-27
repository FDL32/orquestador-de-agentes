"""Tests for the post-rotation detector.

The fixtures model the three paths passed by the heartbeat and never use the
live flight files.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "flight" / "post_relevo_check.py"
)


def _load_module():
    """Load the detector module from its repository path.

    Before: the new detector path is part of the fixture repository.
    During: import the module without changing the process import path.
    After: return the loaded module for direct behavioral tests.
    """
    spec = importlib.util.spec_from_file_location("post_relevo_check", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    """Write a canonical JSON fixture.

    Before: path is inside a temporary test directory.
    During: serialize the value as UTF-8 JSON with one final newline.
    After: the detector can read the resulting file without normalization.
    """
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))


def _make_store(path: Path) -> Path:
    """Create the minimal read-only T3 projection schema for one test."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE orchestration_v2_projection_threads ("
        "thread_id TEXT, project_id TEXT, title TEXT, runtime_mode TEXT, "
        "created_at TEXT, deleted_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE orchestration_v2_projection_runs ("
        "thread_id TEXT, status TEXT, ordinal INTEGER)"
    )
    connection.commit()
    connection.close()
    return path


def _store_thread(path: Path, thread_id: str, *, settled: bool) -> None:
    """Add one hermetic CO row, optionally marked settled in its payload."""
    payload = {"status": "settled"} if settled else {}
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads "
        "(thread_id, project_id, title, runtime_mode, created_at, deleted_at, "
        "payload_json, provider_instance_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            thread_id,
            "test",
            "CO fixture",
            "auto",
            "2026-11-16T17:00:00+00:00",
            None,
            json.dumps(payload),
            None,
        ),
    )
    connection.commit()
    connection.close()


@pytest.fixture(autouse=True)
def _t3_store(tmp_path, monkeypatch):
    """Use a temporary T3 store for every post-relevo test."""
    store = _make_store(tmp_path / "statev2.sqlite")
    monkeypatch.setenv("T3_STATE_DB", str(store))
    return store


def _write_ficha(path: Path, route: str) -> None:
    """Write the minimal real ficha shape consumed by cola_apta.

    Before: path is a temporary ficha location and route is disjoint.
    During: write a Files Likely Touched section with one route bullet.
    After: cola_apta can classify the live cell without a mocked decision.
    """
    path.write_text(
        "# Test ficha\n\n## Files Likely Touched\n\n- " + route + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, *, deadline="2026-11-16T17:07:00+00:00"):
    """Create a flight directory, operations directory, and backlog fixture.

    Before: tmp_path is an isolated pytest directory.
    During: create one active incoming coordinator and optional child sessions.
    After: return the three explicit paths and the mutable registry object.
    """
    flight = tmp_path / "flight"
    ops = tmp_path / "ops"
    flight.mkdir()
    ops.mkdir()
    registry = {
        "orquestador_activo": "CO-IN",
        "sessions": [
            {
                "code": "CO-IN",
                "role": "orquestadora",
                "started": "2026-11-16T17:00:00+00:00",
                "status": "ACTIVA (ACK medido 2026-11-16T17:00:00+00:00)",
                "post_relevo_plazo": deadline,
            },
            {
                "code": "IM-OLD",
                "role": "implantacion",
                "started": "2026-11-16T16:00:00+00:00",
                "status": "ACTIVA",
            },
        ],
    }
    _write_json(
        flight / "flight_roster.json",
        {"active_roles": {"orquestador": {"session_code": "CO-IN"}}},
    )
    _write_json(flight / "session_registry.json", registry)
    (flight / "roster_changes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "backlog.md").write_text(
        "| Ticket | Title | Scope | State | Depends on | Reactivation |\n"
        "|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    return flight, ops, tmp_path / "backlog.md", registry


def test_no_marker_is_not_evaluated(tmp_path):
    """Missing deadline is an explicit fail-open result.

    Before: the incoming session has no deadline and no parseable ACK marker.
    During: evaluate the detector at a time after the expected window.
    After: return rc 0 and explain that no evaluation was possible.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path, deadline=None)
    registry["sessions"][0].pop("post_relevo_plazo")
    registry["sessions"][0]["status"] = "ACTIVA (ACK pendiente)"
    _write_json(flight / "session_registry.json", registry)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 0
    assert "NO EVALUADO" in result.message


def test_m04_registry_with_non_object_session_is_unreadable(tmp_path):
    """m-04: post-relevo does not silently discard malformed registry rows."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].append("corrupta")
    _write_json(flight / "session_registry.json", registry)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 2
    assert result.message.startswith("ERROR: post-relevo no medible:")


def test_deadline_window_is_fail_open_until_expired(tmp_path, monkeypatch):
    """The detector does not evaluate or alert before the deadline.

    Before: the incoming session has a valid future post-rotation deadline.
    During: evaluate at a timestamp inside the seven-minute window.
    After: return rc 0 without creating detector alert state.
    """
    module = _load_module()
    flight, ops, backlog, _ = _fixture(tmp_path)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(args) or 0
    )

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:06:59+00:00")
    expired = module.evaluate(flight, ops, backlog, now="2026-11-16T17:07:00+00:00")

    assert result.rc == 0
    assert "NO EVALUADO" in result.message
    assert expired.rc == 1
    assert calls


def test_less_than_two_live_ims_triggers_alert(tmp_path, monkeypatch):
    """An expired handoff with one live IM emits one post-rotation alert.

    Before: the deadline has passed and only one canonical live IM exists.
    During: evaluate using explicit paths and a fake alert backend.
    After: rc 1 and a single post-relevo key are reported.
    """
    module = _load_module()
    flight, ops, backlog, _ = _fixture(tmp_path)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(args) or 0
    )

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 1
    assert "menos de 2 IM" in result.message
    assert "post-relevo-CO-IN" in result.message
    assert "scripts/flight/post_relevo_check.py" in result.message
    assert calls[0][0] == "post-relevo-CO-IN"
    assert calls[0][1] in result.message
    assert calls[0][2:] == (ops, "CO-IN")
    state = json.loads((ops / "post_relevo_state.json").read_text(encoding="utf-8"))
    assert state["active"] == ["post-relevo-CO-IN"]


def test_reporta_a_counts_created_session_not_launched_by(tmp_path, monkeypatch):
    """The created-session branch uses reporta_a as its only parent field.

    Before: a new TR has a matching reporta_a but a different launched_by.
    During: evaluate after the incoming coordinator deadline.
    After: no-created is false and the remaining live-IM branch is observable.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
                "launched_by": "WRONG-PARENT",
            },
            {
                "code": "TR-NEW-1",
                "role": "triaje",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
                "launched_by": "WRONG-PARENT",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert "sin creados" not in result.reasons


def test_no_created_branch_triggers_with_two_live_ims(tmp_path, monkeypatch):
    """The no-created branch is independent from the live-IM threshold.

    Before: two live IMs satisfy the count but no IM/TR reports to the entrant.
    During: evaluate after the measured deadline.
    After: rc 1 contains only the no-created reason.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].append(
        {
            "code": "IM-SECOND",
            "role": "implantacion",
            "started": "2026-11-16T16:01:00+00:00",
            "status": "ACTIVA",
        }
    )
    _write_json(flight / "session_registry.json", registry)
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 1
    assert result.reasons == ("sin IM/TR creados tras el ACTIVO con reporta_a",)


def test_unclaimed_apta_ticket_triggers_its_own_branch(tmp_path, monkeypatch):
    """An eligible unbriefed backlog row is an independent trigger.

    Before: live IM count and post-ACTIVO creations are both healthy.
    During: make the read-only cola_apta result expose one unclaimed APTA row.
    After: only the APTA reason remains and the detector returns rc 1.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"][1]["slot"] = "implantacion-old"
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "slot": "implantacion-new-1",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "slot": "implantacion-new-2",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    registry["sessions"].append(
        {
            "code": "TR-NEW",
            "role": "triaje",
            "started": "2026-11-16T17:08:30+00:00",
            "status": "ACTIVA",
            "reporta_a": "CO-IN",
        }
    )
    _write_json(flight / "session_registry.json", registry)
    backlog.write_text(
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| Alta | WOT-2026-999a | Ready ticket | scripts/new.py | pending | - | test | - |\n",
        encoding="utf-8",
    )
    _write_ficha(tmp_path / "FICHA_WOT-2026-999a.md", "scripts/new.py")
    _write_ficha(tmp_path / "FICHA_WOT-2026-implantacion-old.md", "scripts/old.py")
    _write_ficha(tmp_path / "FICHA_WOT-2026-implantacion-new-1.md", "scripts/a.py")
    _write_ficha(tmp_path / "FICHA_WOT-2026-implantacion-new-2.md", "scripts/b.py")
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 1
    assert result.reasons == ("ficha APTA sin brief",)


def test_resolution_appends_public_ledger_row(tmp_path, monkeypatch):
    """Resolving a real alert appends the post-relevo ledger resolution row.

    Before: a real comms_alert state is seeded without displaying a toast.
    During: trigger, then clear the condition and evaluate the clean tick.
    After: the ledger contains one nine-field RESOLVED row for the detector.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)

    def seed_alert(key, _message, alert_dir, _session_code):
        alerts = module._load_sibling("comms_alert.py")
        alerts.configure(str(alert_dir))
        alerts.mark_seen(key, "URGENTE", owner="post_relevo")
        return 0

    monkeypatch.setattr(module, "_alert", seed_alert)
    first = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")
    assert first.rc == 1

    registry["sessions"].append(
        {
            "code": "IM-NEW",
            "role": "implantacion",
            "started": "2026-11-16T17:08:00+00:00",
            "status": "ACTIVA",
            "reporta_a": "CO-IN",
        }
    )
    _write_json(flight / "session_registry.json", registry)
    clean = module.evaluate(flight, ops, backlog, now="2026-11-16T17:22:00+00:00")

    assert clean.rc == 0
    rows = [
        json.loads(line)
        for line in (ops / "comms_ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    resolution = rows[-1]
    assert set(resolution) == {
        "ts",
        "by",
        "a",
        "modo",
        "resultado",
        "error",
        "providerInstanceId",
        "mensaje_id",
        "nota",
    }
    assert resolution["by"] == "post_relevo"
    assert resolution["mensaje_id"].startswith("post_relevo:")
    assert resolution["resultado"] == "RESOLVED"


def test_alert_key_is_stable_and_public_backoff_handles_repetition(
    tmp_path, monkeypatch
):
    """A repeated condition is delegated each tick to the public alert flow.

    Before: the same expired condition is evaluated twice.
    During: the fake alert backend records event and resolution operations.
    After: the public comms flow receives both ticks and the clean tick resolves the key.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    events = []
    monkeypatch.setattr(
        module,
        "_alert",
        lambda *args, **kwargs: events.append(("event", args)) or 0,
    )
    first = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")
    second = module.evaluate(flight, ops, backlog, now="2026-11-16T17:21:00+00:00")
    assert first.rc == second.rc == 1
    assert len(events) == 2

    registry["sessions"].append(
        {
            "code": "IM-NEW-2",
            "role": "implantacion",
            "started": "2026-11-16T17:08:00+00:00",
            "status": "ACTIVA",
            "reporta_a": "CO-IN",
        }
    )
    _write_json(flight / "session_registry.json", registry)
    clean = module.evaluate(flight, ops, backlog, now="2026-11-16T17:22:00+00:00")
    assert clean.rc == 0
    assert json.loads((ops / "post_relevo_state.json").read_text())["active"] == []


def test_m07_p24_se_anade_con_otra_razon_y_separa_dos_co(tmp_path, monkeypatch):
    """m-07: P24 no depende de reasons vacio y agrega todos los CO en una clave."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "CO-OUT-1",
                "role": "orquestadora",
                "threadId": "co-out-1",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
            },
            {
                "code": "CO-OUT-2",
                "role": "orquestadora",
                "threadId": "co-out-2",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(args) or 0
    )

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    keys = {call[0] for call in calls}
    assert "menos de 2 IM vivos" in result.message
    assert keys == {
        "post-relevo-CO-IN",
        "post-relevo-CO-IN-p24",
    }
    assert len([call for call in calls if call[0] == "post-relevo-CO-IN-p24"]) == 1
    assert "CO-OUT-1, CO-OUT-2" in result.message


def test_m07_p24_resuelve_solo_co_desaparecido(tmp_path, monkeypatch):
    """m-07: desaparecer todos los CO resuelve la clave P24 agregada."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "CO-OUT-1",
                "role": "orquestadora",
                "threadId": "co-out-1",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
            },
            {
                "code": "CO-OUT-2",
                "role": "orquestadora",
                "threadId": "co-out-2",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(("alert", args)) or 0
    )
    module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    registry["sessions"] = [
        item
        for item in registry["sessions"]
        if item["code"] not in {"CO-OUT-1", "CO-OUT-2"}
    ]
    _write_json(flight / "session_registry.json", registry)
    monkeypatch.setattr(
        module, "_resolve", lambda *args, **kwargs: calls.append(("resolve", args)) or 0
    )
    module.evaluate(flight, ops, backlog, now="2026-11-16T17:21:00+00:00")

    resolved = {args[0] for kind, args in calls if kind == "resolve"}
    assert resolved == {"post-relevo-CO-IN-p24"}


def test_m07_p24_detecta_co_asentable_fuera_de_la_terna(tmp_path, monkeypatch):
    """m-07: el tick posterior a gracia mide una CO asentable fuera de la terna."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].append(
        {
            "code": "IM-NEW-1",
            "role": "implantacion",
            "started": "2026-11-16T17:08:00+00:00",
            "status": "ACTIVA",
            "reporta_a": "CO-IN",
        }
    )
    registry["sessions"].append(
        {
            "code": "IM-NEW-2",
            "role": "implantacion",
            "started": "2026-11-16T17:08:30+00:00",
            "status": "ACTIVA",
            "reporta_a": "CO-IN",
        }
    )
    registry["sessions"].append(
        {
            "code": "CO-OUT",
            "role": "orquestadora",
            "threadId": "co-out-thread",
            "started": "2026-11-16T17:08:00+00:00",
            "status": "ACTIVA",
        }
    )
    _write_json(flight / "session_registry.json", registry)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(args) or 0
    )

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert "CO asentable fuera de la terna" in result.message
    assert calls


def test_p24_uses_t3_settlement_not_registry_status(tmp_path, monkeypatch, _t3_store):
    """CASCADA is current unless the T3 row itself says settled."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "CO-OUT",
                "role": "orquestadora",
                "threadId": "co-out-thread",
                "status": "CASCADA DE CONTEXTO (consultable)",
            },
            {
                "code": "CO-SET",
                "role": "orquestadora",
                "threadId": "co-set-thread",
                "status": "ACTIVA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    _store_thread(_t3_store, "co-out-thread", settled=False)
    _store_thread(_t3_store, "co-set-thread", settled=True)
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 1
    assert "CO-OUT" in result.message
    assert "CO-SET" not in result.message


def test_p24_terna_contexto_head_is_inside_triad(tmp_path, monkeypatch, _t3_store):
    """A readable context head is excluded from P24 like an active role."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    roster = {
        "active_roles": {"orquestador": {"session_code": "CO-IN"}},
        "cadena_contexto": [
            {"threadId": "co-ancestor-thread", "session_code": "CO-ANC"}
        ],
    }
    _write_json(flight / "flight_roster.json", roster)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "CO-ANC",
                "role": "orquestadora",
                "threadId": "co-ancestor-thread",
                "status": "ACTIVA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    _store_thread(_t3_store, "co-ancestor-thread", settled=False)
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert "CO-ANC" not in result.message


@pytest.mark.parametrize("kind", ["missing", "corrupt"], ids=["missing", "corrupt"])
def test_p24_store_t3_no_medido_is_fail_closed(tmp_path, monkeypatch, kind):
    """An expired tick cannot return clean when T3 is unavailable."""
    module = _load_module()
    flight, ops, backlog, _ = _fixture(tmp_path)
    path = tmp_path / ("missing.sqlite" if kind == "missing" else "broken.sqlite")
    if kind == "corrupt":
        path.write_bytes(b"not sqlite")
    monkeypatch.setenv("T3_STATE_DB", str(path))

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc != 0
    assert "store T3 no medido" in result.message


def test_main_uses_explicit_store_before_environment(tmp_path, monkeypatch, capsys):
    """The optional CLI store is selected and remains read-only."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "CO-OUT",
                "role": "orquestadora",
                "threadId": "co-out-thread",
                "status": "ACTIVA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    explicit = _make_store(tmp_path / "explicit.sqlite")
    env_store = _make_store(tmp_path / "env.sqlite")
    _store_thread(explicit, "co-out-thread", settled=True)
    _store_thread(env_store, "co-out-thread", settled=False)
    monkeypatch.setenv("T3_STATE_DB", str(env_store))
    monkeypatch.setattr(module, "_alert", lambda *args, **kwargs: 0)
    explicit_before = explicit.read_bytes()
    env_before = env_store.read_bytes()
    common = [
        "--flight-dir",
        str(flight),
        "--ops-dir",
        str(ops),
        "--backlog",
        str(backlog),
        "--now",
        "2026-11-16T17:20:00+00:00",
    ]

    explicit_rc = module.main([*common, "--store", str(explicit)])
    explicit_output = capsys.readouterr().out
    env_rc = module.main(common)
    env_output = capsys.readouterr().out

    assert explicit_rc == 0
    assert "CO-OUT" not in explicit_output
    assert env_rc == 1
    assert "CO-OUT" in env_output
    assert explicit.read_bytes() == explicit_before
    assert env_store.read_bytes() == env_before


def test_p24_historic_registry_is_sane_without_toast(tmp_path, monkeypatch, _t3_store):
    """P24 ignores a realistic registry of historical cascade rows.

    Before: the isolated registry contains one active entrant, two live IMs, and
        approximately one hundred historical CO rows using production status text.
    During: run the real comms_alert event path with its notify operation disabled
        through the module API, so no desktop toast can be emitted.
    After: the sane registry produces no P24 alert and the alert ledger has no rows.
    """
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    incoming = registry["sessions"][0]
    incoming["post_relevo_plazo"] = "2026-11-16T17:07:00+00:00"
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
        ]
    )
    historical = ["CASCADA DE CONTEXTO", "SETTLED", "CASCADA ASENTADA EN T3"]
    registry["sessions"].extend(
        {
            "code": f"CO-HIST-{index:03d}",
            "role": "orquestadora",
            "threadId": f"co-hist-{index:03d}",
            "started": "2026-11-16T16:00:00+00:00",
            "status": historical[index % len(historical)],
        }
        for index in range(100)
    )
    _write_json(flight / "session_registry.json", registry)
    for index in range(100):
        _store_thread(_t3_store, f"co-hist-{index:03d}", settled=True)
    alerts = module._load_sibling("comms_alert.py")
    alerts.configure(str(ops))
    monkeypatch.setattr(alerts, "notify", lambda *args, **kwargs: 0)
    load_sibling = module._load_sibling
    monkeypatch.setattr(
        module,
        "_load_sibling",
        lambda name: alerts if name == "comms_alert.py" else load_sibling(name),
    )

    result = module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    assert result.rc == 0
    assert "P24" not in result.message
    assert not (ops / "comms_ledger.jsonl").exists()


def test_p24_uses_one_aggregated_alert_for_all_current_cos(tmp_path, monkeypatch):
    """P24 emits one aggregated alert, retaining every current CO identity."""
    module = _load_module()
    flight, ops, backlog, registry = _fixture(tmp_path)
    registry["sessions"].extend(
        [
            {
                "code": "IM-NEW-1",
                "role": "implantacion",
                "started": "2026-11-16T17:08:00+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "IM-NEW-2",
                "role": "implantacion",
                "started": "2026-11-16T17:08:30+00:00",
                "status": "ACTIVA",
                "reporta_a": "CO-IN",
            },
            {
                "code": "CO-OUT-1",
                "role": "orquestadora",
                "threadId": "co-out-1",
                "status": "ACTIVA",
            },
            {
                "code": "CO-OUT-2",
                "role": "orquestadora",
                "threadId": "co-out-2",
                "status": "SUPERVISORA",
            },
        ]
    )
    _write_json(flight / "session_registry.json", registry)
    calls = []
    monkeypatch.setattr(
        module, "_alert", lambda *args, **kwargs: calls.append(args) or 0
    )

    module.evaluate(flight, ops, backlog, now="2026-11-16T17:20:00+00:00")

    p24_calls = [call for call in calls if call[0].endswith("-p24")]
    assert len(p24_calls) == 1
    assert "CO-OUT-1, CO-OUT-2" in p24_calls[0][1]
