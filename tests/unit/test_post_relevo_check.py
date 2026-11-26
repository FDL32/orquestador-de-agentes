"""Tests for the post-rotation detector.

The fixtures model the three paths passed by the heartbeat and never use the
live flight files.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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


def test_alert_key_is_unique_and_resolves(tmp_path, monkeypatch):
    """A repeated condition alerts once and a later clean tick resolves it.

    Before: the same expired condition is evaluated twice.
    During: the fake alert backend records event and resolution operations.
    After: the second alert is suppressed and the clean tick resolves the key.
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
    assert len(events) == 1

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
