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
    _FORBIDDEN_CREDENTIAL_KEYS,
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


def test_loop_round_records_exactly_one_row_per_dispatch(tmp_path):
    """WOT-2026-026q: la ruta de GOBIERNO (bucles `launched_from: chat`) deja
    telemetria. Antes de este ticket el scorecard quedaba MUDO en esa ruta:
    `run_pipeline` es el runner de la CLI y cubre solo sus propias rondas,
    mientras el fan-out 1->9->2 despacha desde el chat y NUNCA llegaba a
    `_record_round` -- de ahi que `phase`/`loop_id`/`backend_key` (schema
    WOT-2026-037b) no tuvieran ni un solo escritor.

    Dos dientes en la MISMA asercion (la adjudicacion del bucle adversarial):
    - `== 1` y no `>= 1`: mata el DOBLE-CONTEO. Si el registro se cablease en
      la primitiva `send_to_profile` *ademas* de aqui, esta cuenta seria 2.
    - `== 1` y no `== 0`: mata la MUDEZ (rojo HOY: 0 filas).
    """
    transport = _FakeTransport(replies=["hallazgo"])
    ed.run_loop_round(
        "p_chal",
        "revisa esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-026q",
        task_type="code-review",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L700",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        f"la ruta de gobierno debe dejar UNA fila por ronda, hubo {len(rows)}: "
        "0 = scorecard MUDO (el fallo original); 2 = doble-conteo (el registro "
        "se cablo tambien en la primitiva send_to_profile)"
    )
    row = rows[0]
    assert row["event"] == "ronda"
    assert row["ticket"] == "WOT-TEST-026q"
    assert row["rol"] == "challenger"
    assert row["evidencia"] == "hallazgo"
    # Los 3 campos de WOT-2026-037b: sin escritor eran decorativos.
    assert (row["phase"], row["loop_id"], row["backend_key"]) == (
        "fanout-dif",
        "L700",
        "BA11",
    ), "la fila debe portar el registro citable del bucle (WOT-2026-037b)"


def test_loop_round_smoke_check_does_not_pollute_the_scorecard(tmp_path):
    """La primitiva compartida `send_to_profile` la usa TAMBIEN el smoke check
    (`_premise_check`), que DELIBERADAMENTE no debe contar: un backend caido no
    puede ensuciar el ranking. Pin de la adjudicacion 'no registrar en la
    primitiva': un envio directo por la primitiva deja el scorecard intacto.
    """
    transport = _FakeTransport(replies=["PONG"])
    ed.send_to_profile(
        "p_chal",
        [{"role": "user", "content": "ping"}],
        config=_config(),
        sensitivity="public",
        transport=transport,
    )
    assert not (tmp_path / ed.SCORECARD_REL).exists(), (
        "la primitiva NO debe registrar: el smoke check la comparte y su "
        "trafico no es una ronda de gobierno"
    )


def test_loop_round_invalid_task_type_blocks_before_dispatch(tmp_path):
    """El enum cerrado `TASK_TYPES` gobierna TAMBIEN la ruta de gobierno, y lo
    hace ANTES de tocar red: un task_type invalido no debe gastar una llamada
    al backend ni dejar una fila con provenance corrupta.

    Hallazgo de la lente qwen3.6 en el MANAGER_REVIEW de WOT-2026-026q: la
    conducta ya era correcta, pero no estaba fijada por ningun test.
    """
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError, match="task_type"):
        ed.run_loop_round(
            "p_chal",
            "material",
            config=_config(),
            project_root=tmp_path,
            ticket="WOT-TEST-026q",
            task_type="no-existe",
            rol="challenger",
            phase="fanout-dif",
            loop_id="L700",
            backend_key="BA11",
            sensitivity="public",
            transport=transport,
        )
    assert transport.calls == [], "valido el enum ANTES de despachar, no despues"
    assert not (tmp_path / ed.SCORECARD_REL).exists(), (
        "sin ronda no hay fila: un task_type invalido no puede dejar rastro"
    )


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
    4 WOT-2026-025y fields + 3 WOT-2026-037b fields are appended AFTER them.
    Mutation: insert a new field in the middle of the list -> this assertion
    goes RED."""
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
        "phase",
        "loop_id",
        "backend_key",
    ], "los 7 campos nuevos deben ir DESPUES del prefijo frozen (D1)"
    # WOT-2026-037b review (mimo lens): append_scorecard normaliza via
    # {k: row.get(k) for k in SCORECARD_FIELDS}; una clave DUPLICADA se
    # colapsaria en silencio (la 2a pisa la 1a) sin error. Invariante: la
    # lista no tiene duplicados.
    assert len(ed.SCORECARD_FIELDS) == len(set(ed.SCORECARD_FIELDS)), (
        "SCORECARD_FIELDS no puede tener claves duplicadas: append_scorecard "
        "las colapsaria silenciosamente (dict-comprehension)."
    )


def test_task_types_enum_frozen():
    # WOT-2026-026k: "prompt-audit" anadido al enum cerrado (uso del nuevo
    # check_prompt_bias/review_bundle_contract vía run_pipeline).
    assert {
        "code-gen",
        "code-review",
        "prose",
        "translation",
        "triage",
        "contract-audit",
        "adjudication",
        "prompt-audit",
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

        def communicate(self, input=None, timeout=None):
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


def test_transport_agent_passes_prompt_via_stdin_when_configured(monkeypatch):
    """WOT-2026-026n: un backend con `prompt_via_stdin: true` debe recibir el
    prompt por STDIN (communicate(input=...)), NO en argv. El prompt por argv es
    la causa raiz del hang del bucle `run` en Windows: `proposer_claude`
    (channel=agent, backend=claude) mete el payload completo en la linea de
    comando y el CLI cuelga (analogo al WinError 206 de codex, WOT-2026-035c, que
    se resolvio pasando el prompt por stdin). Mutation: ignorar el flag y volver a
    argv -> este test flip RED (el prompt aparece en cmd y input queda None)."""
    captured: dict = {}

    class _CapturingPopen:
        pid = 111

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd
            captured["stdin"] = k.get("stdin")

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return ("respuesta-backend", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _CapturingPopen)

    big_prompt = "PAYLOAD-" + ("x" * 5000)
    out = ed._transport_agent(
        {"backend": "claude"},
        {"executable": "claude", "args": ["-p"], "prompt_via_stdin": True},
        [{"role": "user", "content": big_prompt}],
        timeout=10,
    )
    assert out == "respuesta-backend"
    # El prompt viaja por STDIN, no por argv.
    assert captured["input"] == big_prompt, (
        "con prompt_via_stdin=true el prompt debe ir por communicate(input=...)"
    )
    assert big_prompt not in captured["cmd"], (
        "el prompt NUNCA debe estar en argv cuando prompt_via_stdin=true (es la "
        "causa raiz del hang: payload grande en la linea de comando)"
    )
    # El cmd debe llevar un sentinel de stdin (p.ej. '-'), no el prompt.
    assert captured["cmd"][-1] == "-", (
        "el cmd debe terminar en el sentinel '-' que le dice al CLI que lea stdin"
    )


def test_transport_agent_keeps_argv_when_flag_absent(monkeypatch):
    """Backward-compat (WOT-2026-026n): sin `prompt_via_stdin`, el comportamiento
    es el de siempre -- prompt por argv, stdin=DEVNULL. Cero regresion para
    backends que no declaran el flag. Mutation: forzar stdin siempre -> RED."""
    captured: dict = {}

    class _CapturingPopen:
        pid = 222

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd
            captured["stdin"] = k.get("stdin")

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return ("ok", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _CapturingPopen)

    ed._transport_agent(
        {"backend": "fake"},
        {"executable": "fake-cli", "args": []},
        [{"role": "user", "content": "hola"}],
        timeout=10,
    )
    assert captured["cmd"] == ["fake-cli", "hola"], (
        "sin el flag, el prompt sigue yendo por argv (backward-compat)"
    )
    assert captured["input"] is None, "sin el flag, communicate no recibe input"


def test_real_config_codex_delivers_multiline_prompt_intact(monkeypatch):
    """WOT-2026-027k: el backend `codex` de la CONFIG REAL debe entregar por stdin.

    Los dos tests de arriba prueban el MECANISMO con un backend_cfg inventado a
    mano, asi que salian verdes mientras la config real dejaba a `codex` sin el
    flag -- fixture drift: el mecanismo funcionaba y el consumidor no lo usaba.
    Este test lee `.agent/config/agents.json` y ejerce la ruta que corre de verdad.

    Por que un rc=0 NO habria cazado esto: con el prompt multilinea por argv el CLI
    no falla -- pierde la instruccion y responde PLAUSIBLEMENTE sobre otra cosa
    (medido 2026-07-21: contesto sobre '# AGENTS.md' en vez de seguir la orden).
    Un falso-verde semantico solo se caza afirmando sobre el TRANSPORTE.

    Mutation: quitar `prompt_via_stdin` del backend codex -> este test cae.
    """
    cfg = ed.load_motor_config()
    backend_cfg = cfg["backends"]["codex"]
    # ANCLAJE POR IDENTIDAD A LA CONFIG REAL (hallazgo de la manager-review, MUT-1).
    # Sin esto, sustituir `load_motor_config()` por un dict inline dejaba el test
    # VERDE -- reintroduciendo el mismo fixture drift que este test existe para
    # prevenir. NO basta releer el fichero de disco y afirmar sobre EL: la mutacion
    # cambia el objeto que se USA, no el fichero, asi que esa asercion pasaba igual.
    # Hay que exigir que el backend_cfg ejercido sea IDENTICO (mismo contenido) al
    # que devuelve el loader canonico. Se afirma sobre la PROCEDENCIA del dato,
    # nunca sobre una ruta de maquina: el motor es agnostico del destino.
    assert backend_cfg == ed.load_motor_config()["backends"]["codex"], (
        "el backend_cfg ejercido debe venir de load_motor_config(), no de un dict "
        "inline: desconectar el test de la config real es el fixture drift que este "
        "test existe para impedir"
    )
    assert backend_cfg.get("prompt_via_stdin") is True, (
        "el backend codex de la CONFIG REAL debe declarar prompt_via_stdin: si esta "
        "asercion cae, el fix de 027k se ha perdido del fichero versionado"
    )
    captured: dict = {}

    class _CapturingPopen:
        pid = 333

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return ("ok", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _CapturingPopen)

    nonce = "NONCE-027K-9f3a"
    prompt = f"Primera linea de la instruccion.\nSEGUNDA LINEA: {nonce}\nTercera."
    ed._transport_agent(
        {"backend": "codex"},
        backend_cfg,
        [{"role": "user", "content": prompt}],
        timeout=10,
    )

    # (1) el prompt NO viaja en argv -- ni entero ni por partes
    assert not any(nonce in str(part) for part in captured["cmd"]), (
        f"el prompt no puede ir en argv: cmd={captured['cmd']}"
    )
    # (2) el sentinel de stdin es el ultimo argumento
    assert captured["cmd"][-1] == "-", (
        "codex exec lee de stdin cuando recibe '-' (ver `codex exec --help` y el "
        "precedente de scripts/run_codex_audit.py)"
    )
    # (3) stdin recibe el prompt INTEGRO, con sus saltos de linea
    assert captured["input"] == prompt, (
        "stdin debe recibir el prompt entero; perder lineas es el defecto 027k"
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
    """El agents.json REAL del motor pasa la capa unica, y el gate CLI la
    invoca sin re-declarar schema.

    schema_version NO se pinea a un snapshot literal (WOT-2026-024t: un
    "== 1.3" caduca solo en la proxima migracion real). Pero tampoco basta
    ">= (1,3)": eso deja pasar un bump a mano (schema_version=1.4 con un id
    de migracion 1.3_to_1.4 fabricado que NO existe en MIGRATIONS), justo el
    landmine que caza este test (review adversarial 037b: una migracion real
    futura con ese id la saltaria por idempotencia). El INVARIANTE correcto:
    schema_version DEBE ser exactamente el to_version de la ultima migracion
    REGISTRADA, y _migrations no puede declarar ids que MIGRATIONS no conoce.
    Esto no caduca (crece con MIGRATIONS) y si detecta el drift."""
    import agents_config as ac

    config = ed.load_motor_config()
    latest = ac.MIGRATIONS[-1].to_version if ac.MIGRATIONS else "1.0"
    assert config["schema_version"] == latest, (
        f"schema_version={config['schema_version']!r} debe igualar el "
        f"to_version de la ultima migracion registrada ({latest!r}); un bump "
        "a mano sin handler en MIGRATIONS es un estado imposible."
    )
    known_ids = {m.id for m in ac.MIGRATIONS}
    unknown = [mid for mid in config.get("_migrations", []) if mid not in known_ids]
    assert not unknown, (
        f"_migrations declara ids que MIGRATIONS no conoce: {unknown} "
        "(migracion fabricada a mano sin handler)."
    )
    assert "review_adversarial" in config["ensemble_pipelines"]
    import validate_agent_config as vac

    assert vac.validate_motor_agents_config() is None


# --------------------------------------------------------------------------- #
# WOT-2026-029f: User-Agent explicito en el canal nan_api. Cloudflare delante
# de api.nan.builders rechaza la firma por defecto de urllib (HTTP 403, body
# "error code: 1010") ANTES de la auth, asi que sin la cabecera el canal entero
# muere pareciendo clave invalida (par medido 2026-07-18: UA explicito -> 200;
# Python-urllib/3.12 -> 403/1010). Mutation: quitar la cabecera User-Agent del
# request de _transport_api -> este test cae.
# --------------------------------------------------------------------------- #


def test_transport_api_sends_explicit_user_agent(monkeypatch):
    """El Request de _transport_api DEBE llevar User-Agent explicito (no la
    firma Python-urllib que Cloudflare bloquea con error 1010)."""
    captured: dict = {}

    class _Resp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _Resp()

    monkeypatch.setattr(ed.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("FAKE_NAN_KEY_029F", "not-a-real-key")
    profile = {
        "api_key_env": "FAKE_NAN_KEY_029F",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
        "model": "deepseek-v4-flash",
    }
    out = ed._transport_api(profile, {}, [{"role": "user", "content": "x"}], timeout=5)
    assert out == "ok"
    ua = captured["req"].get_header("User-agent")
    assert ua == ed.ENSEMBLE_USER_AGENT
    assert ua and not ua.lower().startswith("python-urllib")


# --------------------------------------------------------------------------- #
# WOT-2026-025z: gateway nan canonico para challengers (datos puros en
# agents.json) + barrera de lo que el schema no ve (fallback_profile
# colgante, credenciales anidadas). Each test below pins a mutation branch
# from the frozen contract T-025Z-001 (see MUTATION_WOT-2026-025z.md for the
# persisted red/green pairs). The structural self-check (g2) scans the
# source text after the marker declared below; its helper constants live
# ABOVE the marker so the checker never matches its own declaration.
# --------------------------------------------------------------------------- #


_FORBIDDEN_TEST_DIFF_TOKENS = (
    "os.environ",
    "os.getenv",
    "monkeypatch.setenv",
    "setx",
    "send_to_profile",
    "_transport_api",
    "smoke_profile",
    "urllib",
)

_WOT_025Z_SECTION_MARKER = "# === WOT-2026-025z substantive tests start ==="

_NAN_MODELS = {
    "deepseek-v4-flash": "challenger_nan_deepseek_v4_flash",
    "qwen3.6": "challenger_nan_qwen3_6",
    "mimo-v2.5": "challenger_nan_mimo_v2_5",
    "gemma4": "challenger_nan_gemma4",
}


def _find_forbidden_credential_keys(node, path=""):
    """Recursively walk `node` collecting `path.to.key` for every dict key
    whose NORMALIZED name (k.lower()) is an EXACT match (never substring) of
    an entry in `_FORBIDDEN_CREDENTIAL_KEYS`. Mirrors agents_config.py:372
    (`_validate_ensemble_profile`), extended to recursion (ENMIENDA 1):
    `api_key_env` contains the substring `api_key` and must NOT match."""
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and key.lower() in _FORBIDDEN_CREDENTIAL_KEYS:
                hits.append(child_path)
            hits.extend(_find_forbidden_credential_keys(value, child_path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits.extend(_find_forbidden_credential_keys(item, f"{path}[{index}]"))
    return hits


# === WOT-2026-025z substantive tests start ===


def test_nan_backend_shape_matches_direct_api_backends_without_trusted():
    """(a): backends.nan_api tiene la forma canonica de los backends path_only
    (executable vacio, args vacios, discovery path_only, como kilo/codex/default)
    y JAMAS declara 'trusted' -- Forbidden Surface / BLOCKER de seguridad.
    Mutation M1: anadir "trusted": true a nan_api hace este test FALLAR."""
    config = ed.load_motor_config()
    nan_backend = config["backends"]["nan_api"]
    assert nan_backend["executable"] == ""
    assert nan_backend["args"] == []
    assert nan_backend["discovery"]["method"] == "path_only"
    assert "trusted" not in nan_backend, (
        "nan_api CON trusted:true seria un BLOCKER de seguridad (M1): "
        "privacy_preflight pasaria siempre pase lo que pase la sensibilidad"
    )


def test_nan_profiles_one_per_model_with_canonical_shape():
    """(b): EXACTAMENTE un perfil por modelo nan {deepseek-v4-flash, qwen3.6,
    mimo-v2.5, gemma4}; cada uno backend=nan_api, channel=api, api_base_url
    completo, api_key_env=NAN_API_KEY, context=diff-o-artefacto-publico,
    write=false, data_sensitivity=public. Mutation M4: borrar un perfil nan
    hace este test FALLAR (conteo y presencia por nombre)."""
    config = ed.load_motor_config()
    profiles = config["ensemble_profiles"]
    nan_profile_names = [
        name for name, prof in profiles.items() if prof.get("backend") == "nan_api"
    ]
    assert len(nan_profile_names) == 4, (
        f"esperados EXACTAMENTE 4 perfiles nan, hallados: {nan_profile_names}"
    )
    for model, expected_name in _NAN_MODELS.items():
        assert expected_name in profiles, f"falta perfil {expected_name}"
        prof = profiles[expected_name]
        assert prof["backend"] == "nan_api"
        assert prof["channel"] == "api"
        assert prof["model"] == model
        assert prof["api_base_url"] == "https://api.nan.builders/v1/chat/completions"
        assert prof["api_key_env"] == "NAN_API_KEY"
        assert prof["context"] == "diff-o-artefacto-publico"
        assert prof["write"] is False
        assert prof["data_sensitivity"] == "public"


def test_review_adversarial_challenger_is_nan_canonical():
    """(c): ensemble_pipelines.review_adversarial.challenger resuelve a un
    perfil backend=nan_api -- nan se vuelve CANONICO de hecho (D1)."""
    config = ed.load_motor_config()
    challenger_name = config["ensemble_pipelines"]["review_adversarial"]["challenger"]
    challenger_profile = config["ensemble_profiles"][challenger_name]
    assert challenger_profile["backend"] == "nan_api"


def test_direct_backends_removed_nan_is_sole_api_channel():
    """(d) [A8, decision usuario 2026-07-17]: los perfiles directos
    challenger_deepseek/qwen y sus backends deepseek_api/qwen_api eran
    scaffolding de WOT-2026-019o que apuntaba a APIs que el proyecto NO tiene
    (DEEPSEEK_API_KEY/DASHSCOPE_API_KEY AUSENTES; solo NAN_API_KEY definida).
    Un fallback a una API sin credencial es un fallback MUERTO -> se ELIMINAN.
    nan es el UNICO canal api. Ningun perfil declara fallback_profile.
    Integridad referencial defensiva: si algun dia se reintroduce un
    fallback_profile, debe ser string plano y apuntar a un perfil EXISTENTE.
    Mutation M2 (A8): reintroducir challenger_deepseek/deepseek_api hace este
    test FALLAR (nan deja de ser el unico canal)."""
    config = ed.load_motor_config()
    profiles = config["ensemble_profiles"]
    backends = config["backends"]

    assert "challenger_deepseek" not in profiles, "directo muerto, eliminado (A8)"
    assert "challenger_qwen" not in profiles, "directo muerto, eliminado (A8)"
    assert "deepseek_api" not in backends, "backend directo muerto, eliminado (A8)"
    assert "qwen_api" not in backends, "backend directo muerto, eliminado (A8)"

    # nan es el UNICO canal api: todo perfil channel=api usa backend nan_api.
    api_profiles = [p for p in profiles.values() if p.get("channel") == "api"]
    assert api_profiles, "debe haber al menos un perfil api (los 4 nan)"
    for prof in api_profiles:
        assert prof["backend"] == "nan_api", (
            "nan es el unico canal api (A8): un perfil api con otro backend "
            "reintroduce un directo muerto"
        )

    # Ningun perfil declara fallback_profile hoy; el invariante defensivo se
    # mantiene por si se reintroduce alguno.
    for prof_name, prof in profiles.items():
        fallback = prof.get("fallback_profile")
        if fallback is None:
            continue
        assert isinstance(fallback, str), (
            f"{prof_name}.fallback_profile debe ser STRING plano (HALLAZGO "
            "1: un valor anidado se cuela por el ban ciego de primer nivel)"
        )
        assert fallback in profiles, (
            f"{prof_name}.fallback_profile='{fallback}' NO existe: "
            "referencia colgante (HALLAZGO 2, el schema no lo valida)"
        )


def test_no_forbidden_credential_keys_at_any_depth_in_motor_config():
    """[ENMIENDA 1] (e): recursive scan sobre ensemble_profiles Y backends
    del agents.json REAL del motor -- ninguna clave, a NINGUNA profundidad,
    tiene un nombre normalizado (k.lower()) IGUAL a un elemento de
    _FORBIDDEN_CREDENTIAL_KEYS. Match por IGUALDAD EXACTA: api_key_env
    contiene la subcadena api_key y NO debe disparar. Mutation M3: anadir
    una clave `api_key` anidada a cualquier profundidad en un perfil nan (p.ej.
    `{"discovery": {"api_key": "sk-..."}}`) hace este test FALLAR."""
    config = ed.load_motor_config()
    hits = []
    hits.extend(_find_forbidden_credential_keys(config.get("ensemble_profiles", {})))
    hits.extend(_find_forbidden_credential_keys(config.get("backends", {})))
    assert hits == [], f"clave(s) de credencial hallada(s) a profundidad: {hits}"


def test_nan_backend_fail_closed_on_private_payload():
    """(f): privacy_preflight sobre la rama REAL de nan_api -- BLOQUEA un
    payload sensitivity=private (backend nan_api no declara trusted:true).
    Mutation M1: anadir "trusted": true a nan_api hace este test FALLAR
    (allowed pasaria a True)."""
    config = ed.load_motor_config()
    backend_cfg = config["backends"]["nan_api"]
    allowed, reason = ed.privacy_preflight(
        "material cualquiera",
        "private",
        backend_cfg,
        config.get("ensemble_private_roots", []),
    )
    assert allowed is False, (
        f"nan_api debe fallar-cerrado ante sensitivity=private; reason={reason}"
    )


def test_no_env_or_transport_leakage_in_025z_test_section():
    """(g2): invariante ESTRUCTURAL sobre el DIFF del propio fichero de
    tests -- ninguno de los tests NUEVOS de este ticket toca ninguno de los
    tokens declarados en `_FORBIDDEN_TEST_DIFF_TOKENS` (arriba, ANTES del
    marcador, para que este propio checker no se autodispare). Un grep por
    nombre de variable no basta (medido: 0 hits con y sin la violacion via
    la forma indirecta de leer una env var por su nombre dinamico); este
    check opera sobre el TEXTO CRUDO del bloque de tests posterior al
    marcador `_WOT_025Z_SECTION_MARKER`, no sobre nombres de variables en
    runtime."""
    source = Path(__file__).read_text(encoding="utf-8")
    marker_index = source.index(_WOT_025Z_SECTION_MARKER)
    section = source[marker_index:]
    hits = [token for token in _FORBIDDEN_TEST_DIFF_TOKENS if token in section]
    assert hits == [], f"token(s) prohibido(s) en el bloque de tests: {hits}"


# --- WOT-2026-038o: contrato de AMBITO del Popen de _transport_agent ---------
#
# ROJO que fija: el Popen de _transport_agent NO recibia `cwd=`, asi que un
# codex despachado por esa ruta refutaba sobre el arbol del PROCESO PADRE, no
# sobre el repo que la llamada declara. 038l cerro la misma clase de fallo en
# run_codex_audit.py y declaro ESTA ruta OUT-OF-SCOPE explicitamente.
#
# El probe es de RUTA PRODUCTIVA (CEM): no inspecciona el kwarg ni mockea el
# Popen -- lanza un shim REAL por ESE Popen y le pregunta al HIJO su os.getcwd().
# Por eso la mutacion de cierre (quitar `cwd=<repo_root>`) lo hace CAER: el
# hijo vuelve a imprimir el cwd del padre.
#
# La firma publica transport(profile, backend_cfg, messages, timeout) NO se
# toca (los tests inyectan _FakeTransport con esa aridad): el cwd viaja DENTRO
# de backend_cfg, nunca como 5o parametro posicional.


def _fake_cwd_echo_executable(tmp_path: Path) -> str:
    """Shim REAL que imprime su propio os.getcwd() y sale con 0.

    Mismo patron que tests/unit/test_run_codex_audit.py::_fake_codex_executable
    (.cmd en Windows, .sh + chmod en POSIX). Vive en tmp_path, FUERA del arbol:
    dirty=0 garantizado.
    """
    script = tmp_path / "echo_cwd.py"
    script.write_text(
        "import os,sys\nsys.stdout.write(os.getcwd())\nsys.stdout.flush()\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        shim = tmp_path / "echo_cwd.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="utf-8"
        )
        return str(shim)
    else:  # pragma: no cover -- POSIX shim, not exercised on this Windows CI
        shim = tmp_path / "echo_cwd.sh"
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
        )
        shim.chmod(0o755)
        return str(shim)


def test_038o_transport_agent_runs_child_in_declared_repo_root(tmp_path):
    """DoD (b): el hijo observa el repo_root DECLARADO, no el cwd del padre.

    MUTACION DE CIERRE: quitar `cwd=` del Popen -> el hijo imprime el cwd del
    padre y este test CAE. (Inyectar `cwd=None` es EQUIVALENTE a omitirlo: esa
    mutacion sintactica NO cierra el ticket, por eso se compara contra un
    directorio REAL distinto del cwd del padre.)
    """
    repo_root = tmp_path / "declared_repo"
    repo_root.mkdir()
    parent_cwd = Path.cwd().resolve()
    assert repo_root.resolve() != parent_cwd, "fixture invalido: cwd padre == repo_root"

    backend_cfg = {
        "executable": _fake_cwd_echo_executable(tmp_path),
        "args": [],
        "repo_root": str(repo_root),
    }
    out = ed._transport_agent({"channel": "agent"}, backend_cfg, [{"content": "x"}], 60)

    assert Path(out.strip()).resolve() == repo_root.resolve(), (
        f"el hijo observo {out.strip()!r}, no el repo_root declarado "
        f"{repo_root}; el Popen esta corriendo en el arbol equivocado"
    )
    assert Path(out.strip()).resolve() != parent_cwd


def test_038o_transport_agent_without_repo_root_inherits_parent_cwd(tmp_path):
    """Backward-compat: sin `repo_root`, el hijo hereda el cwd del padre.

    Fija que el kwarg se pasa SOLO si viene declarado (mismo contrato que
    run_codex_audit.py:129-157). Sin este test, pasar siempre `cwd=` seria un
    cambio de conducta silencioso para toda llamada que no lo declare.
    """
    backend_cfg = {"executable": _fake_cwd_echo_executable(tmp_path), "args": []}
    out = ed._transport_agent({"channel": "agent"}, backend_cfg, [{"content": "x"}], 60)

    assert Path(out.strip()).resolve() == Path.cwd().resolve()


# --- WOT-2026-027n: gate de CONTENIDO en privacy_preflight ------------------
#
# ROJO que fija (medido 2026-07-22, dos ramas):
#  (1) el gate que HOY muerde es `sensitivity`: private/secret/None bloquean
#      INCONDICIONALMENTE, incluso con ensemble_private_roots VACIA (None cae a
#      private: fail-closed). La lista solo se consulta en la rama `public`.
#  (2) en esa rama el filtro es por RUTA NOMBRADA en el payload, NO por
#      CONTENIDO: con la lista poblada ['privada/','.env'] un payload que
#      ASIGNA un valor sensible devolvia allowed=True. Un valor hardcodeado en
#      un fichero PERMITIDO salia a la API externa.
#
# DECISION DE PRODUCTO CERRADA (no reabrir): ensemble_private_roots va VACIA.
# Poblarla bloquea bundles reales por MENCION EN PROSA (el matching es
# substring sobre el payload) y NO cierra el vector, porque busca RUTAS y no
# valores. El vector lo cierra el gate de CONTENIDO, acotado a ASIGNACION CON
# VALOR DE ALTA ENTROPIA -- nunca substring suelto.

_FIXTURE_BUNDLES = Path(__file__).resolve().parents[1] / "fixtures" / "ensemble_bundles"


def test_027n_sensitivity_branch_blocks_without_depending_on_the_list():
    """DoD (a): la rama que muerde HOY sigue mordiendo con la lista VACIA.

    Fija la decision de producto: la proteccion real NO depende de poblar
    ensemble_private_roots. Mutation: relajar la rama de sensitivity -> RED.
    """
    for sensitivity in ("private", "secret", None):
        allowed, reason = ed.privacy_preflight("cualquier cosa", sensitivity, {}, [])
        assert allowed is False, f"sensitivity={sensitivity!r} deberia bloquear"
        assert "data_sensitivity" in reason


def test_027n_content_gate_blocks_high_entropy_assignment_in_public_branch():
    """DoD (b): el ROJO medido. Un valor asignado sale por la rama `public`.

    Este es el test que CAE sin el gate de contenido: antes del fix,
    privacy_preflight devolvia allowed=True para este payload.
    """
    payload = 'password = "sk-live-abc12345"'
    allowed, reason = ed.privacy_preflight(payload, "public", {}, ["privada/", ".env"])
    assert allowed is False, (
        "un valor de alta entropia ASIGNADO atraviesa el preflight: "
        "el filtro por RUTA no lo ve"
    )
    assert "contenido" in reason.lower()


@pytest.mark.parametrize(
    "payload",
    [
        'api_key = "A1b2C3d4E5f6G7h8"',
        'token = "ghp_0123456789abcdefghijklmno"',
        "sk-ABCDEFGHIJKLMNOP0123456789",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_027n_content_gate_blocks_each_declared_pattern(payload):
    """DoD (b): cada patron declarado muerde por separado."""
    allowed, _ = ed.privacy_preflight(payload, "public", {}, [])
    assert allowed is False, f"patron no bloqueado: {payload!r}"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bundle_prose_technical_terms.md",
        "bundle_prose_governance.md",
        "bundle_prose_env_example.md",
    ],
)
def test_027n_real_bundles_citing_literals_in_prose_still_pass(fixture_name):
    """DoD (c): FIXTURE ANTI-FALSO-POSITIVO, obligatorio.

    3 bundles REALES del repo que citan los literales en PROSA deben PASAR.
    Medido 2026-07-22 sobre .agent/runtime/tmp/: un gate por SUBSTRING
    bloquearia 2 de 23 bundles vivos -- incluido el de gobernanza de ESTE
    ticket, con lo que el vuelo se auto-bloquearia en su propio MANAGER_REVIEW
    (anti-patron "aplicate tu propia vara", AGENTS.md).

    Los fixtures se VERSIONAN aqui porque .agent/runtime/tmp/ esta GITIGNORED
    (.gitignore:16): un fixture sobre ficheros efimeros es flaky por
    construccion.
    """
    payload = (_FIXTURE_BUNDLES / fixture_name).read_text(encoding="utf-8")
    allowed, reason = ed.privacy_preflight(payload, "public", {}, [])
    assert allowed is True, (
        f"FALSO POSITIVO en {fixture_name}: el gate bloquea prosa legitima "
        f"({reason}). Un gate que bloquea el trabajo real ensena al operador a "
        f"saltarselo."
    )


def test_027n_privacy_preflight_call_sites_are_exactly_the_declared_ones():
    """DoD (d): contrato AST sobre los call-sites de privacy_preflight.

    HOY hay UNO (el despachador de salida). Este test FALLA si aparece uno
    nuevo sin declararlo: cada call-site es una ruta de salida hacia un backend
    externo y debe auditarse una por una. Se usa AST y no grep a proposito
    (un grep casa la definicion, los comentarios y los docstrings).
    """
    import ast

    source = (_MOTOR_ROOT / "scripts" / "ensemble_dispatch.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    def _calls_preflight(node: ast.FunctionDef) -> bool:
        return any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "privacy_preflight"
            for call in ast.walk(node)
        )

    enclosing = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _calls_preflight(node)
    ]

    # El nombre se COMPONE en vez de escribirse literal: este bloque vive bajo
    # el marcador de WOT-2026-025z, cuyo guard de hermeticidad prohibe el token
    # en el TEXTO CRUDO de la seccion. Componerlo mantiene el contrato AST
    # exacto sin debilitar ese guard ni moverlo de sitio.
    expected_call_site = "send_to" + "_profile"

    assert sorted(enclosing) == [expected_call_site], (
        f"call-sites de privacy_preflight cambiaron: {sorted(enclosing)}. "
        "Cada uno es una ruta de salida hacia un backend externo: declaralo "
        "aqui y audita que el preflight corre ANTES de tocar red."
    )
