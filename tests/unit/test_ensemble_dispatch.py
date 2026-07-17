"""Tests for scripts/ensemble_dispatch.py + ensemble schema (WOT-2026-019o).

Hermetic by construction: every dispatch test injects a fake `transport`
(no network, no real CLI). The load-bearing barriers, each with the mutation
it pins:
  - privacy_preflight runs INSIDE send_to_profile, fail-closed (mutation:
    remove the preflight call -> the payload reaches the transport -> RED);
  - scorecard append happens for EVERY round including no-aportacion
    (mutation: drop the append -> row-count assertions go RED);
  - round 0 = premise_check is a dispatcher INVARIANT (mutation: make it
    configurable/skippable -> RED);
  - writer is UTF-8 WITHOUT BOM (byte-level assertion);
  - backend_leaders.json is DERIVED (hash of source, leader only with n>=5,
    exploration policy as a field of the artifact itself);
  - config resolution is MOTOR-EXPLICIT (M9): AGENT_PROJECT_ROOT pointing at
    a foreign dir does NOT change which agents.json the dispatcher loads;
  - credentials only as env-var NAMES (api_key_env); literal credential keys
    in agents.json fail validation with exit != 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


_AGENT_DIR = _MOTOR_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import (  # noqa: E402
    AgentsConfigError,
    _migrate_1_2_to_1_3,
    _validate_ensemble,
)


def _config(*, trusted: bool = False, private_roots: list[str] | None = None):
    """Minimal valid ensemble config for hermetic dispatch tests."""
    backend: dict = {
        "executable": "",
        "args": [],
        "discovery": {"method": "path_only"},
    }
    if trusted:
        backend["trusted"] = True
    return {
        "schema_version": "1.3",
        "backends": {"fake": backend},
        "ensemble_profiles": {
            "p_prop": {
                "backend": "fake",
                "channel": "api",
                "model": "m1",
                "api_base_url": "https://fake.example/v1/chat/completions",
                "api_key_env": "FAKE_API_KEY",
                "data_sensitivity": "public",
                "write": False,
            },
            "p_chal": {
                "backend": "fake",
                "channel": "api",
                "model": "m2",
                "api_base_url": "https://fake.example/v1/chat/completions",
                "api_key_env": "FAKE_API_KEY",
                "data_sensitivity": "public",
                "write": False,
            },
        },
        "ensemble_pipelines": {
            "pipe": {
                "proposer": "p_prop",
                "challenger": "p_chal",
                "rubric": "prompts/audit_agent_output.md",
                "max_rounds": 2,
            }
        },
        "ensemble_private_roots": private_roots or [],
    }


class _FakeTransport:
    """Records calls; returns canned replies (empty string = no-aportacion)."""

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.replies = list(replies or [])

    def __call__(self, profile, backend_cfg, messages, timeout):
        self.calls.append(
            {"profile": profile, "messages": messages, "timeout": timeout}
        )
        return self.replies.pop(0) if self.replies else "respuesta"


# --------------------------------------------------------------------------- #
# privacy_preflight: fail-closed, both branches, and it guards the SEND path
# --------------------------------------------------------------------------- #


def test_preflight_blocks_non_public_to_untrusted():
    """Declarative branch: sensitivity != public + untrusted -> block.
    Absent sensitivity is treated as private (fail-closed)."""
    allowed, reason = ed.privacy_preflight("x", "private", {}, [])
    assert not allowed and "private" in reason
    allowed, _ = ed.privacy_preflight("x", None, {}, [])
    assert not allowed, "sensitivity AUSENTE debe tratarse como private"


def test_preflight_blocks_private_root_in_payload():
    """Content branch: public payload citing a declared private root -> block."""
    allowed, reason = ed.privacy_preflight(
        "ver C:/repos/privado/secreto.md", "public", {}, ["C:/repos/privado"]
    )
    assert not allowed and "privada" in reason


def test_preflight_allows_public_and_trusted():
    allowed, _ = ed.privacy_preflight("x", "public", {}, [])
    assert allowed
    allowed, _ = ed.privacy_preflight("cualquier cosa", "secret", {"trusted": True}, [])
    assert allowed, "backend trusted:true pasa siempre"


def test_send_blocks_before_transport():
    """MUTATION PIN: without the preflight inside send_to_profile, the
    payload would reach the transport. The fake transport must record ZERO
    calls when the preflight blocks."""
    transport = _FakeTransport()
    with pytest.raises(ed.DispatchBlockedError):
        ed.send_to_profile(
            "p_prop",
            [{"role": "user", "content": "hola"}],
            config=_config(),
            sensitivity="private",
            transport=transport,
        )
    assert transport.calls == [], (
        "el payload SALIO pese al bloqueo del preflight (mutation: se quito "
        "el preflight del camino de envio)"
    )


def test_send_reaches_transport_when_allowed():
    transport = _FakeTransport(replies=["ok"])
    reply = ed.send_to_profile(
        "p_prop",
        [{"role": "user", "content": "hola"}],
        config=_config(),
        sensitivity="public",
        transport=transport,
    )
    assert reply == "ok" and len(transport.calls) == 1


# --------------------------------------------------------------------------- #
# Scorecard: append-only, all rounds incl. no-aportacion, UTF-8 no BOM
# --------------------------------------------------------------------------- #


def _rows(project_root: Path) -> list[dict]:
    path = project_root / ed.SCORECARD_REL
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_run_pipeline_records_every_round(tmp_path):
    """2 participantes x (ronda 0 + 2 rondas) = 6 filas. MUTATION PIN: drop
    the append from _record_round -> this count goes RED."""
    transport = _FakeTransport(replies=["r"] * 6)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material publico",
        sensitivity="public",
        transport=transport,
    )
    rows = _rows(tmp_path)
    assert len(rows) == 6
    assert all(r["event"] == "ronda" for r in rows)


def test_round_zero_is_premise_check_invariant(tmp_path):
    """ROUND 0 exists for BOTH roles even at max_rounds=1, and its prompt
    carries the premise-check preamble. Mutation: make round 0 skippable ->
    RED."""
    transport = _FakeTransport(replies=["r"] * 4)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
    )
    rows = _rows(tmp_path)
    zero_rows = [r for r in rows if r["ronda"] == 0]
    assert {r["rol"] for r in zero_rows} == {"proposer", "challenger"}
    first_two_prompts = [c["messages"][0]["content"] for c in transport.calls[:2]]
    assert all("PREMISE CHECK" in p for p in first_two_prompts)


def test_empty_reply_recorded_as_no_aportacion(tmp_path):
    """NIT-B5: without zeros there is survivorship bias. An empty reply is a
    row with outcome=no-aportacion, never a missing row."""
    transport = _FakeTransport(replies=["", "algo", "", "algo", "", "algo"])
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
    )
    rows = _rows(tmp_path)
    assert len(rows) == 6
    assert sum(1 for r in rows if r["outcome"] == "no-aportacion") == 3


def test_scorecard_writer_utf8_no_bom(tmp_path):
    ed.append_scorecard(
        tmp_path,
        {"ts": "t", "event": "ronda", "evidencia": "acentuacion-y-ascii"},
    )
    raw = (tmp_path / ed.SCORECARD_REL).read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf", "el writer NO debe emitir BOM"
    assert raw.endswith(b"\n")


# --------------------------------------------------------------------------- #
# Adjudication + leaders projection
# --------------------------------------------------------------------------- #


def _seed_rounds(project_root: Path, n: int, *, task_type="code-review", start=0):
    for i in range(start, start + n):
        ed.append_scorecard(
            project_root,
            {
                "ts": f"t{i}",
                "event": "ronda",
                "ticket": f"WOT-TEST-{i:03d}a",
                "rol": "challenger",
                "task_type": task_type,
                "backend": "fake",
                "model": "m2",
                "ronda": 1,
                "outcome": None,
                "evidencia": "e",
                "input_bytes": 10,
                "context_kind": "diff",
            },
        )


def test_adjudicate_requires_evidence_and_valid_outcome(tmp_path):
    _seed_rounds(tmp_path, 1)
    with pytest.raises(ValueError, match="OBLIGATORIA"):
        ed.adjudicate(
            tmp_path,
            ticket="WOT-TEST-000a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="   ",
            adjudicator_backend="fake-adjudicator",
        )
    with pytest.raises(ValueError, match="invalido"):
        ed.adjudicate(
            tmp_path,
            ticket="WOT-TEST-000a",
            ronda=1,
            rol="challenger",
            outcome="me-gusta",
            evidence="cmd + salida",
            adjudicator_backend="fake-adjudicator",
        )


def test_adjudicate_refuses_unrecorded_round(tmp_path):
    """No se adjudica lo que no se registro (guard del tercer rol)."""
    with pytest.raises(ValueError, match="no existe fila"):
        ed.adjudicate(
            tmp_path,
            ticket="WOT-NUNCA-999z",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd + salida",
            adjudicator_backend="fake-adjudicator",
        )


def test_adjudicate_appends_event_and_regenerates_leaders(tmp_path):
    _seed_rounds(tmp_path, 1)
    before = len(_rows(tmp_path))
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="pytest -k x -> exit 0",
        adjudicator_backend="fake-adjudicator",
    )
    rows = _rows(tmp_path)
    assert len(rows) == before + 1, "la adjudicacion APPENDEA, nunca muta"
    assert rows[-1]["event"] == "adjudicacion"
    assert (tmp_path / ed.LEADERS_REL).exists()


def test_supersede_event_overrides_previous_adjudication(tmp_path):
    """Veto humano: un evento supersede posterior pisa la adjudicacion previa
    en la proyeccion, sin editar filas."""
    _seed_rounds(tmp_path, 1)
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="fake-adjudicator",
    )
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="falso-positivo",
        evidence="veto humano: repro fallo",
        adjudicator_backend="human",
        supersede=True,
    )
    rows = _rows(tmp_path)
    assert rows[-1]["event"] == "supersede"
    cells = ed._adjudicated_cells(rows)
    assert cells[("WOT-TEST-000a", 1, "challenger")]["outcome"] == "falso-positivo"


def test_leaders_requires_min_n(tmp_path):
    """n < 5 -> sin lider, rotar. n >= 5 -> lider declarado. La proyeccion
    lleva hash de la fuente y la politica de exploracion como campo."""
    _seed_rounds(tmp_path, 4)
    for i in range(4):
        ed.adjudicate(
            tmp_path,
            ticket=f"WOT-TEST-{i:03d}a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd",
            adjudicator_backend="fake-adjudicator",
        )
    leaders = json.loads((tmp_path / ed.LEADERS_REL).read_text(encoding="utf-8"))
    assert leaders["por_task_type"]["code-review"]["lider"] is None
    assert "rotar" in leaders["por_task_type"]["code-review"]["nota"]

    _seed_rounds(tmp_path, 1, start=4)  # quinta muestra: celda NUEVA
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-004a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="fake-adjudicator",
    )
    leaders = json.loads((tmp_path / ed.LEADERS_REL).read_text(encoding="utf-8"))
    cell = leaders["por_task_type"]["code-review"]
    assert cell["lider"] == {"backend": "fake", "model": "m2"}
    assert cell["n_muestras"] >= ed.LEADER_MIN_N
    assert leaders["scorecard_sha256"]
    assert "1-de-5" in leaders["exploration_policy"]
    raw = (tmp_path / ed.LEADERS_REL).read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"


# --------------------------------------------------------------------------- #
# WOT-2026-025y: scorecard hygiene -- session_id, TASK_TYPES, latency_ms,
# adjudicator identity. Each test below pins a specific mutation branch from
# the frozen contract T-025Y-001 (see MUTATION_WOT-2026-025y.md for the
# persisted red/green pairs).
# --------------------------------------------------------------------------- #


def test_scorecard_fields_prefix_is_frozen():
    """R0 pin: the 16 EXISTING fields keep their name/order (invariant); the
    4 new WOT-2026-025y fields are appended AFTER them. Mutation: insert a
    new field in the middle of the list -> this assertion goes RED."""
    assert ed.SCORECARD_FIELDS[:16] == [
        "ts",
        "event",
        "ticket",
        "rol",
        "task_type",
        "backend",
        "model",
        "backend_version",
        "ronda",
        "outcome",
        "evidencia",
        "finding_confirmed_by",
        "adjudication_evidence",
        "input_bytes",
        "context_kind",
        "failure_mode",
    ]
    assert ed.SCORECARD_FIELDS[16:] == [
        "session_id",
        "latency_ms",
        "adjudicator_backend",
        "adjudicator_model",
    ], "los 4 campos nuevos deben ir DESPUES del prefijo frozen (D1)"


def test_task_types_enum_frozen():
    assert {
        "code-gen",
        "code-review",
        "prose",
        "translation",
        "triage",
        "contract-audit",
        "adjudication",
    } == ed.TASK_TYPES


def test_append_scorecard_discards_extra_fields(tmp_path):
    """R1 pin: a key outside SCORECARD_FIELDS is silently dropped by the
    comprehension in append_scorecard. Mutation: write ALL of row's keys
    instead of only SCORECARD_FIELDS ones -> the extra key would leak into
    the persisted row and this assertion goes RED."""
    ed.append_scorecard(
        tmp_path,
        {"ts": "t", "event": "ronda", "campo_fantasma": "no-deberia-persistir"},
    )
    rows = _rows(tmp_path)
    assert "campo_fantasma" not in rows[-1]
    assert set(rows[-1].keys()) == set(ed.SCORECARD_FIELDS)


def test_task_type_invalid_blocks_run_pipeline_api(tmp_path):
    """(c) API path: task_type invalido -> ValueError en la ENTRADA de
    run_pipeline, antes de tocar ronda alguna."""
    transport = _FakeTransport()
    with pytest.raises(ValueError, match="task_type"):
        ed.run_pipeline(
            "pipe",
            config=_config(),
            project_root=tmp_path,
            ticket="WOT-TEST-001a",
            task_type="basura-invalida",
            payload="material",
            sensitivity="public",
            transport=transport,
        )
    assert transport.calls == [], (
        "task_type invalido debe bloquear ANTES de enviar nada a un backend"
    )
    assert (tmp_path / ed.SCORECARD_REL).exists() is False


def test_task_type_invalid_blocks_cli_exit_nonzero(tmp_path, monkeypatch):
    """(c) CLI path: `run --task-type basura` sale con exit != 0 (D2: un
    unico guard en run_pipeline gobierna ambos caminos, API y CLI).
    `send_to_profile` se stubea para que, SI la validacion se saltara, el
    comando completaria con EXITO (rc=0) en vez de fallar por otra razon
    (auth/red): asi el exit code queda atado SOLO al guard de task_type,
    no a un efecto colateral (mutation: quitar el guard de run_pipeline
    hace que rc pase de 1 a 0, no solo 'algun no-cero')."""
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "ok")
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    rc = ed.main(
        [
            "run",
            "--pipeline",
            "pipe",
            "--ticket",
            "WOT-TEST-001a",
            "--task-type",
            "basura-invalida",
            "--payload-file",
            str(payload_file),
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 1, "task_type invalido debe bloquear via ValueError -> exit 1"


def test_latency_ms_measured_with_controlled_delta(tmp_path, monkeypatch):
    """(d) [ENMIENDA -- delta controlado, NUNCA floor assertion]. perf_counter
    se monkeypatchea para avanzar un delta CONOCIDO (50ms) en cada llamada;
    toda fila de ronda debe llevar latency_ms == 50 exacto (int), nunca solo
    >= 0. Mutation: dejar de medir/pasar latency_ms (o pasar un timestamp
    fijo) hace que esta igualdad exacta caiga."""
    ticks = iter(0.05 * i for i in range(0, 200))
    monkeypatch.setattr(ed.time, "perf_counter", lambda: next(ticks))
    transport = _FakeTransport(replies=["r"] * 4)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
    )
    rows = _rows(tmp_path)
    assert len(rows) == 4
    assert all(r["latency_ms"] == 50 for r in rows), (
        f"latency_ms debia ser EXACTAMENTE 50 (delta controlado): {rows}"
    )


def test_adjudicate_row_has_no_latency_ms(tmp_path):
    """(d)/R2 pin: la fila REAL de adjudicacion nunca mide latencia (no hay
    llamada a un backend dentro de adjudicate()); append_scorecard rellena
    None porque la clave esta ausente del dict que construye adjudicate()."""
    _seed_rounds(tmp_path, 1)
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="fake-adjudicator",
    )
    rows = _rows(tmp_path)
    assert rows[-1]["event"] == "adjudicacion"
    assert rows[-1]["latency_ms"] is None


def test_session_id_flows_from_flag_in_run_pipeline(tmp_path):
    """(b): --session-id en run se propaga a CADA fila de ronda."""
    transport = _FakeTransport(replies=["r"] * 4)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
        session_id="sess-scratch-001",
    )
    rows = _rows(tmp_path)
    assert len(rows) == 4
    assert all(r["session_id"] == "sess-scratch-001" for r in rows)


def test_session_id_absent_defaults_to_none_in_run_pipeline(tmp_path):
    """(b) D5: session_id es OPCIONAL -- ausente, cada fila lo lleva a None
    via el relleno de append_scorecard."""
    transport = _FakeTransport(replies=["r"] * 4)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
    )
    rows = _rows(tmp_path)
    assert all(r["session_id"] is None for r in rows)


def test_adjudicate_session_id_comes_from_flag_not_source(tmp_path):
    """(b) [ENMIENDA] MUTATION PIN: la fuente (ronda original) lleva un
    session_id DISTINTO al de la sesion que adjudica. Si adjudicate() usara
    source.get('session_id') en vez del parametro session_id, la fila
    adjudicada terminaria con el session_id EQUIVOCADO y este assert cae."""
    ed.append_scorecard(
        tmp_path,
        {
            "ts": "t0",
            "event": "ronda",
            "ticket": "WOT-TEST-000a",
            "rol": "challenger",
            "task_type": "code-review",
            "backend": "fake",
            "model": "m2",
            "ronda": 1,
            "outcome": None,
            "evidencia": "e",
            "input_bytes": 10,
            "context_kind": "diff",
            "session_id": "sess-de-la-ronda-original",
        },
    )
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="fake-adjudicator",
        session_id="sess-adjudicando",
    )
    rows = _rows(tmp_path)
    assert rows[-1]["session_id"] == "sess-adjudicando", (
        "la fila de adjudicacion DEBE tomar session_id del FLAG de "
        "adjudicate(), nunca de source.get('session_id')"
    )


def test_adjudicator_backend_required_and_recorded_separately_from_source_backend(
    tmp_path,
):
    """(e): adjudicator_backend es OBLIGATORIO (ValueError si vacio) y se
    registra en su PROPIA columna, sin pisar el 'backend' EXISTENTE (que
    sigue copiado del SOURCE -- Forbidden Surface, HALLAZGO 1)."""
    _seed_rounds(tmp_path, 1)  # source backend == 'fake'
    with pytest.raises(ValueError, match="adjudicator_backend"):
        ed.adjudicate(
            tmp_path,
            ticket="WOT-TEST-000a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd",
            adjudicator_backend="",
        )
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="claude-opus",
        adjudicator_model="opus-4.8",
    )
    rows = _rows(tmp_path)
    last = rows[-1]
    assert last["adjudicator_backend"] == "claude-opus"
    assert last["adjudicator_model"] == "opus-4.8"
    assert last["backend"] == "fake", (
        "el campo EXISTENTE 'backend' sigue copiado del SOURCE (:640-641, "
        "Forbidden Surface); la identidad del adjudicador va en su propia "
        "columna"
    )


def test_adjudicate_rol_adjudicator_still_exits_2_by_design():
    """(g)/A2 pin: --rol choices=[proposer,challenger] NO se amplia con
    'adjudicator'. La capacidad de registrar QUIEN adjudico vive en
    --adjudicator-backend, no en un --rol expandido; por eso este comando
    SIGUE dando SystemExit(2) (argparse invalid choice), by design."""
    with pytest.raises(SystemExit) as exc_info:
        ed.main(
            [
                "adjudicate",
                "--ticket",
                "WOT-TEST-000a",
                "--ronda",
                "1",
                "--rol",
                "adjudicator",
                "--outcome",
                "adoptada",
                "--evidence",
                "cmd",
                "--adjudicator-backend",
                "human",
                "--project-root",
                ".",
            ]
        )
    assert exc_info.value.code == 2


def test_leaders_attribute_to_contributor_not_adjudicator(tmp_path):
    """(f)/(g) [ENMIENDA -- atribucion OBSERVABLE con umbral]: se siembran y
    adjudican >= LEADER_MIN_N rondas de task_type=code-review del mismo
    (backend=fake, model=m2); backend_leaders debe atribuir el liderazgo a
    fake|m2 (quien APORTO), NUNCA al adjudicador ('human'). MUTATION PIN
    R-proyeccion: si :640-641 copiaran adjudicator_backend/task_type de la
    fila de adjudicacion en vez del SOURCE, el bucket/cell_key cambiaria y
    esta atribucion caeria (ver MUTATION_WOT-2026-025y.md)."""
    _seed_rounds(tmp_path, ed.LEADER_MIN_N, task_type="code-review")
    for i in range(ed.LEADER_MIN_N):
        ed.adjudicate(
            tmp_path,
            ticket=f"WOT-TEST-{i:03d}a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd",
            adjudicator_backend="human",
        )
    leaders = json.loads((tmp_path / ed.LEADERS_REL).read_text(encoding="utf-8"))
    cell = leaders["por_task_type"]["code-review"]
    assert cell["lider"] == {"backend": "fake", "model": "m2"}, (
        "el lider debe ser QUIEN APORTO (fake|m2), no el adjudicador (human)"
    )
    assert cell["n_muestras"] >= ed.LEADER_MIN_N


# --------------------------------------------------------------------------- #
# Smoke by CONTENT + B2 + motor-explicit resolution (M9) + root guard
# --------------------------------------------------------------------------- #


def test_smoke_verdict_is_by_content_not_exit_code():
    ok = ed.smoke_profile(
        "p_prop",
        config=_config(),
        transport=_FakeTransport(replies=["PONG-019o"]),
    )
    assert ok["alive"] is True
    wrong = ed.smoke_profile(
        "p_prop",
        config=_config(),
        transport=_FakeTransport(replies=["Authentication Error"]),
    )
    assert wrong["alive"] is False, (
        "una respuesta sin el token NO es un backend vivo (opencode devuelve "
        "exit 0 con Auth Error, medido)"
    )


def test_smoke_dead_backend_is_step_skip_not_crash():
    def _boom(profile, backend_cfg, messages, timeout):
        raise RuntimeError("timeout de red")

    result = ed.smoke_profile("p_prop", config=_config(), transport=_boom)
    assert result["alive"] is False and "timeout" in result["detail"]


def test_transport_agent_timeout_kills_process_tree(monkeypatch):
    """Pipe-inheritance hang (medido 2026-07-16): si el CLI del backend no
    responde, _transport_agent debe matar el ARBOL (no solo el hijo directo)
    y levantar RuntimeError. Mutation: quitar la llamada a _kill_process_tree
    del except -> este test flip RED."""
    import subprocess as _sp

    killed: list[int] = []

    class _HangingPopen:
        pid = 424242

        def __init__(self, *a, **k):
            pass

        def communicate(self, timeout=None):
            raise _sp.TimeoutExpired(cmd="fake", timeout=timeout)

    monkeypatch.setattr(ed.subprocess, "Popen", _HangingPopen)
    monkeypatch.setattr(ed, "_kill_process_tree", lambda pid: killed.append(pid))

    with pytest.raises(RuntimeError, match="arbol de procesos"):
        ed._transport_agent(
            {"backend": "fake"},
            {"executable": "fake-cli", "args": []},
            [{"role": "user", "content": "x"}],
            timeout=1,
        )
    assert killed == [424242], (
        "el timeout DEBE matar el arbol de procesos: sin eso, un descendiente "
        "que herede los pipes congela el smoke/piloto entero"
    )


def test_run_pipeline_writes_only_ensemble_runtime(tmp_path):
    """B2: el dispatcher no aplica nada al arbol; su unica escritura es el
    runtime de ensemble bajo el project_root."""
    transport = _FakeTransport(replies=["r"] * 6)
    ed.run_pipeline(
        "pipe",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-001a",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
    )
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [tmp_path / ed.SCORECARD_REL]


def test_motor_explicit_config_resolution_m9(monkeypatch, tmp_path):
    """M9 PIN: AGENT_PROJECT_ROOT hacia un dir ajeno SIN claves ensemble no
    cambia la config que carga el dispatcher (resolucion por __file__)."""
    foreign = tmp_path / ".agent" / "config"
    foreign.mkdir(parents=True)
    (foreign / "agents.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "backends": {
                    "x": {
                        "executable": "",
                        "args": [],
                        "discovery": {"method": "path_only"},
                    }
                },
                "role_assignments": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    config = ed.load_motor_config()
    assert config.get("ensemble_profiles"), (
        "el dispatcher resolvio el agents.json del entorno (workspace) en "
        "vez del MOTOR: M9 roto"
    )


def test_project_root_guard_refuses_motor(tmp_path):
    with pytest.raises(ValueError, match="repo_motor"):
        ed._resolve_project_root(str(ed.MOTOR_ROOT))
    assert ed._resolve_project_root(str(tmp_path)) == tmp_path.resolve()


# --------------------------------------------------------------------------- #
# Schema layer (single layer in agents_config) + migration 1.2 -> 1.3
# --------------------------------------------------------------------------- #


def _schema_config(**overrides):
    base = _config()
    base["role_assignments"] = {}
    base.update(overrides)
    return base


def test_schema_rejects_unknown_backend_and_bad_channel(tmp_path):
    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"]["backend"] = "no-existe"
    with pytest.raises(AgentsConfigError, match="unknown backend"):
        _validate_ensemble(cfg, tmp_path / "agents.json")
    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"]["channel"] = "webhook"
    with pytest.raises(AgentsConfigError, match="channel"):
        _validate_ensemble(cfg, tmp_path / "agents.json")


def test_schema_rejects_literal_credentials(tmp_path):
    """M7: un token literal en agents.json -> validacion falla."""
    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"]["api_key"] = "sk-secreto-literal"
    with pytest.raises(AgentsConfigError, match="credential"):
        _validate_ensemble(cfg, tmp_path / "agents.json")
    cfg = _schema_config()
    cfg["backends"]["fake"]["token"] = "abc123"  # noqa: S105 -- el test PRUEBA el ban
    with pytest.raises(AgentsConfigError, match="credential"):
        _validate_ensemble(cfg, tmp_path / "agents.json")
    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"]["api_key_env"] = "sk-valor-literal"
    with pytest.raises(AgentsConfigError, match="ENV VAR NAME"):
        _validate_ensemble(cfg, tmp_path / "agents.json")


def test_schema_rejects_bad_pipeline_and_rounds(tmp_path):
    cfg = _schema_config()
    cfg["ensemble_pipelines"]["pipe"]["challenger"] = "fantasma"
    with pytest.raises(AgentsConfigError, match="challenger"):
        _validate_ensemble(cfg, tmp_path / "agents.json")
    cfg = _schema_config()
    cfg["ensemble_pipelines"]["pipe"]["max_rounds"] = 4
    with pytest.raises(AgentsConfigError, match="max_rounds"):
        _validate_ensemble(cfg, tmp_path / "agents.json")


def test_schema_rejects_non_bool_trusted(tmp_path):
    cfg = _schema_config()
    cfg["backends"]["fake"]["trusted"] = "yes"
    with pytest.raises(AgentsConfigError, match="trusted"):
        _validate_ensemble(cfg, tmp_path / "agents.json")


def test_schema_retrocompatible_without_ensemble_keys(tmp_path):
    cfg = {
        "schema_version": "1.2",
        "backends": {
            "x": {
                "executable": "",
                "args": [],
                "discovery": {"method": "path_only"},
            }
        },
    }
    assert _validate_ensemble(cfg, tmp_path / "agents.json") is None


def test_migration_1_2_to_1_3_backfills_empty_structures():
    migrated = _migrate_1_2_to_1_3({"schema_version": "1.2"})
    assert migrated["schema_version"] == "1.3"
    assert migrated["ensemble_profiles"] == {}
    assert migrated["ensemble_pipelines"] == {}
    assert migrated["ensemble_private_roots"] == []
    already = _migrate_1_2_to_1_3(
        {"schema_version": "1.2", "ensemble_private_roots": ["x"]}
    )
    assert already["ensemble_private_roots"] == ["x"], "setdefault, no pisar"


def test_motor_agents_json_validates_via_single_layer():
    """El agents.json REAL del motor (1.3) pasa la capa unica, y el gate CLI
    la invoca sin re-declarar schema."""
    config = ed.load_motor_config()
    assert config["schema_version"] == "1.3"
    assert "review_adversarial" in config["ensemble_pipelines"]
    import validate_agent_config as vac

    assert vac.validate_motor_agents_config() is None
