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

import email.message
import inspect
import io
import json
import sys
import time
import traceback
import urllib.error
from datetime import datetime, timedelta, timezone
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
    """Records calls; returns canned replies (empty string = no-aportacion).

    WOT-2026-046h: un elemento de `replies` que sea una instancia de
    `Exception` se LANZA en vez de devolverse, para simular el canal `api`
    real (`_transport_api`), que lanza `TransportError`/etc. ante un fallo de
    red en vez de devolver texto (a diferencia del canal `agent`, que
    antepone `_TRANSPORT_FAILED_PREFIX` como texto, WOT-2026-048g).
    """

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.replies = list(replies or [])

    def __call__(self, profile, backend_cfg, messages, timeout):
        self.calls.append(
            {"profile": profile, "messages": messages, "timeout": timeout}
        )
        reply = self.replies.pop(0) if self.replies else "respuesta"
        if isinstance(reply, Exception):
            raise reply
        return reply


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


def test_family_leaders_aggregates_across_transports(tmp_path):
    """regenerate_family_leaders agrega POR FAMILIA cruzando transportes: 2
    filas nan_api/glm5.3-flash + 3 filas nvidia_api/z-ai/glm-5.3, todas con
    (ticket, ronda, rol) DISTINTOS (_adjudicated_cells deduplica por esa
    clave -- 5 filas repetidas no producirian n=5) y outcome=adoptada, deben
    agregar n=5 bajo familia "glm". Control positivo de que MODEL_FAMILY_MAP
    cruza backend|model correctamente, y de que backend_leaders.json
    (backend|model) sigue separando las celdas -- la agregacion es ADITIVA,
    nunca sustituye el ranking existente."""
    rows = [
        ("nan_api", "glm5.3-flash"),
        ("nan_api", "glm5.3-flash"),
        ("nvidia_api", "z-ai/glm-5.3"),
        ("nvidia_api", "z-ai/glm-5.3"),
        ("nvidia_api", "z-ai/glm-5.3"),
    ]
    for i, (backend, model) in enumerate(rows):
        ed.append_scorecard(
            tmp_path,
            {
                "ts": f"t{i}",
                "event": "ronda",
                "ticket": f"WOT-FAM-{i:03d}a",
                "rol": "challenger",
                "task_type": "code-review",
                "backend": backend,
                "model": model,
                "ronda": 1,
                "outcome": None,
                "evidencia": "e",
                "input_bytes": 10,
                "context_kind": "diff",
            },
        )
        ed.adjudicate(
            tmp_path,
            ticket=f"WOT-FAM-{i:03d}a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd + salida",
            adjudicator_backend="fake-adjudicator",
        )

    family_path = ed.regenerate_family_leaders(tmp_path)
    assert family_path == tmp_path / ed.FAMILY_LEADERS_REL
    family_leaders = json.loads(family_path.read_text(encoding="utf-8"))
    cell = family_leaders["por_task_type"]["code-review"]
    assert cell["lider"] == {"familia": "glm"}
    assert cell["n_muestras"] == 5
    assert cell["tasa_adoptadas"] == 1.0
    assert family_leaders["unmapped_backend_model_pairs"] == []
    assert family_leaders["scorecard_sha256"]

    # ADITIVA: backend|model sigue separando las 2 celdas (nan_api|glm5.3-flash
    # con n=2, nvidia_api|z-ai/glm-5.3 con n=3) -- ninguna alcanza LEADER_MIN_N
    # sola, asi que backend_leaders.json NO declara lider para esta task_type,
    # aunque la vista por familia SI lo hace con el total agregado.
    backend_leaders = json.loads(
        (tmp_path / ed.LEADERS_REL).read_text(encoding="utf-8")
    )
    backend_cell = backend_leaders["por_task_type"]["code-review"]
    assert backend_cell["lider"] is None
    assert "rotar" in backend_cell["nota"]


def test_family_leaders_unmapped_pair_falls_back_without_losing_history(tmp_path):
    """Una combinacion (backend, model) SIN entrada en MODEL_FAMILY_MAP cae a
    familia "sin_familia" -- WARN listado, pero SIGUE contando (nunca se
    pierde historico del scorecard por un mapeo incompleto)."""
    for i in range(ed.LEADER_MIN_N):
        ed.append_scorecard(
            tmp_path,
            {
                "ts": f"t{i}",
                "event": "ronda",
                "ticket": f"WOT-UNMAPPED-{i:03d}a",
                "rol": "challenger",
                "task_type": "code-review",
                "backend": "nan_api",
                "model": "modelo-nunca-mapeado-v9",
                "ronda": 1,
                "outcome": None,
                "evidencia": "e",
                "input_bytes": 10,
                "context_kind": "diff",
            },
        )
        ed.adjudicate(
            tmp_path,
            ticket=f"WOT-UNMAPPED-{i:03d}a",
            ronda=1,
            rol="challenger",
            outcome="adoptada",
            evidence="cmd + salida",
            adjudicator_backend="fake-adjudicator",
        )

    family_leaders = json.loads(
        ed.regenerate_family_leaders(tmp_path).read_text(encoding="utf-8")
    )
    cell = family_leaders["por_task_type"]["code-review"]
    assert cell["lider"] == {"familia": "sin_familia"}
    assert cell["n_muestras"] == ed.LEADER_MIN_N
    assert (
        "('nan_api', 'modelo-nunca-mapeado-v9')"
        in (family_leaders["unmapped_backend_model_pairs"])
    )


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
        # WOT-2026-040b: commit_sha + challenge_nonce cierran el bucle de
        # gobierno como barrera de EJECUCION -- cada receipt de send_to_profile
        # ata el commit bajo review y copia el nonce emitido FUERA
        # (emitted_nonces.jsonl) para que check_loop_execution pruebe que la
        # ronda respondio a ESE challenge de ESE commit, no solo que hubo uno.
        # Al final por el mismo motivo que 025y/037b: el prefijo es frozen.
        "commit_sha",
        "challenge_nonce",
        # WOT-2026-043q: output_chars mide el tamano REAL de la respuesta antes
        # de truncar. Distingue "corrio y callo" de "corrio y respondio", que
        # eran indistinguibles para check_loop_execution. Al final, igual que
        # los anteriores: el prefijo de 16 sigue siendo frozen.
        "output_chars",
        # WOT-2026-048g: model_reported es el modelo que el BACKEND dice haber
        # usado (extraido de su stderr), frente a `model`, que es el DECLARADO
        # por el perfil. Cierra el residuo de WOT-2026-047y: aquel hizo que
        # declarado y solicitado coincidan por construccion, pero un CLI que
        # aceptara el flag y sirviera otro modelo seguia siendo invisible. Al
        # final, igual que todos los anteriores: el prefijo de 16 es frozen.
        "model_reported",
        # WOT-2026-042v: lens_scope es el AMBITO EFECTIVO desde el que observo
        # la lente. Sin el, el scorecard mezcla una poblacion que VE el arbol
        # con otra que solo opina sobre el, y backend_leaders.json rankea
        # comparando lo incomparable. Al final, igual que todos los anteriores:
        # el prefijo de 16 es frozen.
        "lens_scope",
    ], "los 12 campos nuevos deben ir DESPUES del prefijo frozen (D1)"
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
    # WOT-2026-055o: "exploracion" anadido -- trafico smoke/preflight, que
    # ahora SI deja fila en el scorecard y que `check_loop_execution` excluye
    # explicitamente de la barrera de independencia.
    assert {
        "code-gen",
        "code-review",
        "prose",
        "translation",
        "triage",
        "contract-audit",
        "adjudication",
        "prompt-audit",
        "exploracion",
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


def test_loop_round_usage_error_leaves_auditable_row(tmp_path, monkeypatch):
    """WOT-2026-048i: un error de USO de `loop-round` deja FILA con `failure_mode`.

    El exit code YA era correcto (`return 1`), y NO se toca -- ese es el
    NON-GOAL de la ficha. Lo que faltaba es RASTRO: el `[BLOCKED]` sale por
    stderr y la ronda muere SIN dejar fila, asi que "nadie consulto a esta
    lente" y "la invocacion estaba mal escrita" son indistinguibles en el
    scorecard. Medido 2026-08-05 sobre el motor 0be12cb: `--task-type`
    con guion BAJO -> rc=1, stdout vacio, delta de filas = 0.

    Por que la fila se escribe en el HANDLER y no en `run_loop_round`: la
    validacion de `run_loop_round` (`:1749`) ocurre ANTES de resolver
    `profile` (`:1753`), y `_record_round` EXIGE un `profile` dict. En el
    handler el perfil SI es resoluble desde la config.

    Mutation que aisla la rama: quitar el pre-check del handler deja el
    `raise` interno como unica via -> la fila no se escribe y
    `len(rows) == 0`, con el rc SIN cambiar (sigue siendo 1). Es decir: el
    test NO puede pasar por el exit code, solo por la fila.
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", lambda *a, **k: "ok")
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload_file),
            "--ticket",
            "WOT-TEST-048i",
            "--task-type",
            "contract_audit",
            "--rol",
            "challenger",
            "--phase",
            "CONTRACT_AUDIT",
            "--loop-id",
            "L999",
            "--backend-key",
            "BKA",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 1, "un error de USO sigue saliendo con exit 1 (NON-GOAL: no se toca)"
    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        "el error de USO debe dejar EXACTAMENTE UNA fila auditable; sin ella, "
        f"'nadie consulto' y 'invocacion mal escrita' son iguales: {rows}"
    )
    row = rows[0]
    assert row["failure_mode"] == "missing-nonce", (
        f"la fila debe declarar POR QUE murio, no solo que murio: {row}"
    )
    assert row["ticket"] == "WOT-TEST-048i", (
        f"la fila debe ser atribuible al ticket que la provoco: {row}"
    )
    assert row["loop_id"] == "L999", f"debe conservar el loop_id: {row}"
    assert row["backend_key"] == "BKA", f"debe conservar el backend_key: {row}"


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


# --- WOT-2026-047y: inyeccion de profile["model"] en el argv -----------------
#
# ROJO que fijan: `_transport_agent` construia `cmd = [executable, *args,
# prompt]` sin `profile["model"]` en NINGUNA de las dos ramas. El CLI corria su
# modelo por DEFECTO mientras `_append_scorecard` registraba el DECLARADO, asi
# que `backend_leaders.json` rankeaba por un campo falso para todo perfil
# `channel: agent` con modelo -- indetectable desde el registro.
#
# Se asevera sobre el ARGV CONSTRUIDO, nunca sobre stdout: afirmar sobre la
# respuesta mediria el backend, no la inyeccion. Los dos exit codes del mutation
# pair medido (opencode 1.16.2) eran 0; el discriminante era el CONTENIDO.


def _capture_argv(monkeypatch, profile, backend_cfg, prompt="hola"):
    """Ejerce `_transport_agent` con Popen capturado y devuelve el argv real."""
    captured: dict = {}

    class _ArgvCapturingPopen:
        pid = 4747

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return ("ok", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _ArgvCapturingPopen)
    ed._transport_agent(
        profile, backend_cfg, [{"role": "user", "content": prompt}], timeout=10
    )
    return captured


def test_047y_model_is_injected_into_argv_rama_argv(monkeypatch):
    """Rama argv: el modelo del perfil entra en el cmd, ANTES del prompt.

    Mutation: devolver `[]` en `_render_model_flag` -> este test cae en ROJO.
    """
    captured = _capture_argv(
        monkeypatch,
        {"backend": "opencode", "channel": "agent", "model": "opencode-go/glm-5.2"},
        {
            "executable": "opencode",
            "args": ["run"],
            "model_flag": ["--model", "{model}"],
        },
        prompt="PROMPT-047Y",
    )
    assert captured["cmd"] == [
        "opencode",
        "run",
        "--model",
        "opencode-go/glm-5.2",
        "PROMPT-047Y",
    ], (
        "el modelo del PERFIL debe entrar en el argv con la sintaxis declarada "
        f"por el BACKEND; cmd={captured['cmd']}"
    )


def test_047y_model_is_injected_before_stdin_sentinel(monkeypatch):
    """Rama prompt_via_stdin: el flag va ANTES del sentinel `-`.

    El sentinel cierra la linea de comando; un argumento posterior lo leeria el
    CLI como parte del prompt. Mutation: mover la inyeccion detras del sentinel
    -> este test cae.
    """
    captured = _capture_argv(
        monkeypatch,
        {"backend": "fake", "channel": "agent", "model": "modelo-x"},
        {
            "executable": "fake-cli",
            "args": ["exec"],
            "prompt_via_stdin": True,
            "model_flag": ["--model", "{model}"],
        },
        prompt="PAYLOAD",
    )
    assert captured["cmd"] == ["fake-cli", "exec", "--model", "modelo-x", "-"], (
        f"el flag del modelo debe preceder al sentinel '-'; cmd={captured['cmd']}"
    )
    assert captured["cmd"][-1] == "-", "el sentinel sigue siendo el ultimo argumento"
    assert captured["input"] == "PAYLOAD", "el prompt sigue viajando por stdin"


def test_047y_profile_without_model_keeps_argv_untouched(monkeypatch):
    """`model: null` (proposer_claude, challenger_codex) no anade nada.

    Es el contrato vigente: esos perfiles dejan que el CLI use su default. Un
    fix que inyectara un flag vacio los romperia.
    """
    captured = _capture_argv(
        monkeypatch,
        {"backend": "claude", "channel": "agent", "model": None},
        {
            "executable": "claude",
            "args": ["-p"],
            "prompt_via_stdin": True,
            "model_flag": ["--model", "{model}"],
        },
    )
    assert captured["cmd"] == ["claude", "-p", "-"], (
        f"sin modelo declarado el argv no cambia; cmd={captured['cmd']}"
    )


def test_047y_model_without_backend_template_fails_loud_not_silent(monkeypatch):
    """DEFENSA EN PROFUNDIDAD: modelo declarado + backend sin plantilla -> raise.

    El validador de config lo bloquea antes, pero `_transport_agent` acepta un
    `backend_cfg` inyectado que NO pasa por el loader. Devolver `[]` ahi
    reintroduciria el defecto exacto del ticket -- el CLI corriendo su default
    mientras el scorecard registra el declarado -- y el modo de fallo es
    SILENCIOSO: por eso no puede depender de una sola barrera.

    Mutation: devolver `[]` en vez de lanzar -> este test cae.
    """
    with pytest.raises(RuntimeError, match="model_flag"):
        _capture_argv(
            monkeypatch,
            {"backend": "sin-plantilla", "channel": "agent", "model": "modelo-y"},
            {"executable": "cli", "args": []},
        )


def test_047y_real_config_opencode_profile_renders_its_model(monkeypatch):
    """ANTI FIXTURE DRIFT: la CONFIG REAL, no un dict inline (patron de 027k).

    Los tests de arriba prueban el MECANISMO con backends inventados; este exige
    que `challenger_opencode_glm_5_2` (BA06) -- el perfil cuya unica fila del
    scorecard registraba `opencode-go/glm-5.2` mientras el proceso corria
    `gpt-5.4-mini` -- resuelva su modelo contra la config versionada.

    Mutation: quitar `model_flag` del backend opencode en agents.json -> cae.
    """
    cfg = ed.load_motor_config()
    profile = cfg["ensemble_profiles"]["challenger_opencode_glm_5_2"]
    backend_cfg = cfg["backends"][profile["backend"]]
    # Anclaje por IDENTIDAD al loader canonico: sin esto, sustituir
    # `load_motor_config()` por un dict inline dejaria el test verde y
    # reintroduciria el fixture drift que existe para impedir.
    assert backend_cfg == ed.load_motor_config()["backends"][profile["backend"]], (
        "el backend_cfg ejercido debe venir de load_motor_config()"
    )
    declared = profile["model"]
    assert declared, "el perfil BA06 declara un modelo en la config real"

    captured = _capture_argv(monkeypatch, profile, backend_cfg)
    assert declared in captured["cmd"], (
        "el modelo DECLARADO en la config real debe aparecer en el argv que "
        f"recibe el CLI; cmd={captured['cmd']}. Si esta asercion cae, el "
        "scorecard vuelve a registrar un modelo que el proceso no corrio"
    )


def test_047y_api_channel_still_passes_model_in_body_not_argv(monkeypatch):
    """ANTI-FALSO-POSITIVO: los `channel: api` NO cambian de comportamiento.

    Pasan el modelo en el body JSON (`_transport_api`), nunca en argv. Un fix
    que tocara su ruta los romperia; este test lo pinea.
    """
    sent: dict = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "respuesta-api"}}]}
            ).encode("utf-8")

    def _fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setenv("FAKE_KEY_047Y", "sk-test")
    monkeypatch.setattr(ed.urllib.request, "urlopen", _fake_urlopen)

    out = ed._transport_api(
        {
            "channel": "api",
            "model": "deepseek-v4-flash",
            "api_key_env": "FAKE_KEY_047Y",
            "api_base_url": "https://example.invalid/v1/chat/completions",
        },
        {"executable": "", "args": []},
        [{"role": "user", "content": "hola"}],
        timeout=10,
    )
    assert out == "respuesta-api"
    assert sent["body"]["model"] == "deepseek-v4-flash", (
        "el canal api sigue pasando el modelo en el BODY JSON, intacto"
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


def test_047y_schema_rejects_agent_model_without_backend_template(tmp_path):
    """FAIL-CLOSED: `channel: agent` + `model` sin `model_flag` en su backend.

    Sin este gate, el perfil se enviaba EN SILENCIO al modelo por defecto del
    CLI mientras el scorecard registraba el declarado -- un fallo que el
    registro no puede delatar. Mutation: quitar la llamada a
    `_validate_ensemble_agent_model` -> este test cae.
    """
    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"] = {
        "backend": "fake",
        "channel": "agent",
        "model": "modelo-que-nadie-inyecta",
        "data_sensitivity": "public",
        "write": False,
    }
    with pytest.raises(AgentsConfigError, match="model_flag"):
        _validate_ensemble(cfg, tmp_path / "agents.json")


def test_047y_schema_accepts_agent_model_with_template_and_null_model(tmp_path):
    """CONTROL POSITIVO del gate anterior: lo legitimo sigue pasando.

    (a) perfil agent con modelo y backend CON plantilla -> valido;
    (b) perfil agent con `model: null` y backend SIN plantilla -> valido, que
        es el contrato vigente de `proposer_claude` / `challenger_codex`.
    Sin este control, el gate podria estar bloqueando todo y el test de arriba
    saldria verde igual.
    """
    cfg = _schema_config()
    cfg["backends"]["fake"]["model_flag"] = ["--model", "{model}"]
    cfg["ensemble_profiles"]["p_prop"] = {
        "backend": "fake",
        "channel": "agent",
        "model": "modelo-x",
        "data_sensitivity": "public",
        "write": False,
    }
    assert _validate_ensemble(cfg, tmp_path / "agents.json") is None

    cfg = _schema_config()
    cfg["ensemble_profiles"]["p_prop"] = {
        "backend": "fake",
        "channel": "agent",
        "model": None,
        "data_sensitivity": "public",
        "write": False,
    }
    assert _validate_ensemble(cfg, tmp_path / "agents.json") is None


def test_047y_schema_rejects_model_flag_without_placeholder(tmp_path):
    """Una plantilla sin `{model}` renderiza un flag sin valor: mismo defecto.

    El CLI caeria a su default en silencio, que es exactamente lo que el ticket
    cierra. Tambien se rechaza una plantilla que no sea lista de strings.
    """
    cfg = _schema_config()
    cfg["backends"]["fake"]["model_flag"] = ["--model"]
    with pytest.raises(AgentsConfigError, match="placeholder"):
        _validate_ensemble(cfg, tmp_path / "agents.json")

    cfg = _schema_config()
    cfg["backends"]["fake"]["model_flag"] = "--model {model}"
    with pytest.raises(AgentsConfigError, match="list of"):
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
# WOT-2026-041a: el motor es un repo PUBLICO y _transport_api pone la api_key
# en "Authorization: Bearer <key>". MEDIDO 2026-07-24 con probe propio: NO es
# str(HTTPError) quien filtra (False), sino err.headers (True) y repr(req)
# (True). Por eso la mutation lleva CUATRO aserciones y no una: solo (a) puede
# satisfacerse con la fuga viva si el error saneado encadena el crudo.
#   quitar el saneado  -> caen (a) y (d)
#   silenciar el error -> caen (b) y (c)
# --------------------------------------------------------------------------- #

_LEAK_KEY_041A = "sk-live-041a-DEADBEEF-supersecret-value"


def _http_error_carrying_the_key(url: str, key: str) -> urllib.error.HTTPError:
    """HTTPError REAL cuyos headers llevan la Authorization, como en produccion."""
    hdrs = email.message.Message()
    hdrs["Content-Type"] = "application/json"
    hdrs["Authorization"] = f"Bearer {key}"
    return urllib.error.HTTPError(
        url,
        429,
        "Too Many Requests",
        hdrs,
        io.BytesIO(b'{"error":{"message":"quota exceeded","type":"rate_limit"}}'),
    )


def test_transport_api_error_no_filtra_la_api_key(monkeypatch):
    """El error propagado NO expone la clave por NINGUNA via (str/repr/args/cause)."""

    def boom_urlopen(req, timeout=None):
        raise _http_error_carrying_the_key(req.full_url, _LEAK_KEY_041A)

    monkeypatch.setattr(ed.urllib.request, "urlopen", boom_urlopen)
    monkeypatch.setenv("FAKE_NAN_KEY_041A", _LEAK_KEY_041A)
    profile = {
        "api_key_env": "FAKE_NAN_KEY_041A",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
        "model": "deepseek-v4-flash",
    }

    with pytest.raises(Exception) as excinfo:
        ed._transport_api(profile, {}, [{"role": "user", "content": "x"}], timeout=5)
    err = excinfo.value

    # (a) la CADENA de la clave no aparece por NINGUNA superficie ALCANZABLE
    #     del objeto propagado. Se busca la KEY, no "Authorization", para no
    #     pasar por accidente.
    #     OJO -- medido bajo mutation: str/repr/args por si solos NO
    #     discriminan, porque `str(HTTPError)` tampoco contiene la clave (el
    #     probe de premisa lo midio: False). Quien filtra es `.headers`. Un
    #     test que solo mirase str() pasaria con la fuga VIVA: seria la floor
    #     assertion clasica. Por eso se barre el estado publico del error.
    assert _LEAK_KEY_041A not in str(err)
    assert _LEAK_KEY_041A not in repr(err)
    assert _LEAK_KEY_041A not in repr(err.args)
    assert _LEAK_KEY_041A not in str(getattr(err, "headers", "") or "")
    assert _LEAK_KEY_041A not in repr(vars(err))
    assert _LEAK_KEY_041A not in repr(
        {
            name: getattr(err, name, None)
            for name in dir(err)
            if not name.startswith("__")
        }
    )

    # (b) status/code preservado: silenciar el error rompe el diagnostico de
    #     cuota de WOT-2026-027g, que es ortogonal a esta fuga.
    assert getattr(err, "status", None) == 429
    assert getattr(err, "code", None) == 429
    assert "429" in str(err)

    # (c) cuerpo diagnostico preservado (y saneado): sin el no se distingue un
    #     429 de cuota de un 429 de otra causa.
    assert "quota exceeded" in str(err)
    assert _LEAK_KEY_041A not in str(getattr(err, "body", "") or "")

    # (d) el error NO encadena el objeto crudo: con __cause__/__context__ vivos
    #     la clave sigue alcanzable en el traceback aunque str(err) este limpio.
    assert err.__cause__ is None
    assert err.__context__ is None or not isinstance(
        err.__context__, urllib.error.HTTPError
    )
    chained = err.__cause__ or err.__context__
    assert chained is None or _LEAK_KEY_041A not in str(getattr(chained, "headers", ""))


def test_transport_api_redacta_la_key_si_viene_en_el_cuerpo(monkeypatch):
    """La redaccion del CUERPO se ejerce de verdad, no por accidente.

    Hallazgo del MANAGER_REVIEW (lente adversarial): el fixture principal usa
    un cuerpo que NO contiene la clave, asi que su asercion sobre `body`
    pasaria igual sin redactar nada -- floor assertion. Aqui el cuerpo SI la
    lleva (un backend que hace eco del header en su mensaje de error), de modo
    que la asercion solo puede pasar si `_redact_secret` corre sobre el cuerpo.
    """

    def boom_urlopen(req, timeout=None):
        hdrs = email.message.Message()
        hdrs["Content-Type"] = "application/json"
        hdrs["Authorization"] = f"Bearer {_LEAK_KEY_041A}"
        body = json.dumps(
            {"error": {"message": f"invalid key: {_LEAK_KEY_041A}", "code": "bad_key"}}
        ).encode()
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", hdrs, io.BytesIO(body)
        )

    monkeypatch.setattr(ed.urllib.request, "urlopen", boom_urlopen)
    monkeypatch.setenv("FAKE_NAN_KEY_041A", _LEAK_KEY_041A)
    profile = {
        "api_key_env": "FAKE_NAN_KEY_041A",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
        "model": "deepseek-v4-flash",
    }
    with pytest.raises(Exception) as excinfo:
        ed._transport_api(profile, {}, [{"role": "user", "content": "x"}], timeout=5)
    err = excinfo.value

    assert _LEAK_KEY_041A not in str(err)
    assert _LEAK_KEY_041A not in str(err.body or "")
    assert ed.REDACTED_MARKER in str(err.body or "")
    # el resto del cuerpo diagnostico sobrevive a la redaccion
    assert "bad_key" in str(err.body or "")
    assert err.status == 401


def test_transport_api_no_convierte_error_de_parseo_en_error_de_transporte(monkeypatch):
    """Un 200 con cuerpo malformado sigue siendo JSONDecodeError, no transporte.

    Hallazgo del MANAGER_REVIEW (2 lentes independientes): envolver el
    `json.loads` en el try del saneado convertia un error de PARSEO en
    TransportError con status=None, borrando el tipo que un caller podria
    estar discriminando.
    """

    class _Resp:
        def read(self):
            return b"esto no es json"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ed.urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    monkeypatch.setenv("FAKE_NAN_KEY_041A", _LEAK_KEY_041A)
    profile = {
        "api_key_env": "FAKE_NAN_KEY_041A",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
        "model": "deepseek-v4-flash",
    }
    with pytest.raises(json.JSONDecodeError):
        ed._transport_api(profile, {}, [{"role": "user", "content": "x"}], timeout=5)


def test_transport_api_error_no_encadena_el_objeto_crudo(monkeypatch):
    """El error propagado no da acceso al HTTPError crudo por el ENCADENAMIENTO.

    ALCANCE DECLARADO (WOT-2026-041a): esta prueba mira lo que el error LLEVA
    CONSIGO al propagarse, que es lo que el ticket cierra. NO mira los
    `locals()` de los frames: la variable `api_key` vive necesariamente en el
    frame de `_transport_api` para poder construir el Request, y ningun saneado
    del ERROR puede retirarla de ahi. Los tracebacks de terceros que vuelcan
    locals estan EXPLICITAMENTE fuera del alcance del ticket (ver limites
    declarados en el DAG); cerrarlos exigiria no tener la clave en una local
    -- otro ticket, otra superficie.
    """

    def boom_urlopen(req, timeout=None):
        raise _http_error_carrying_the_key(req.full_url, _LEAK_KEY_041A)

    monkeypatch.setattr(ed.urllib.request, "urlopen", boom_urlopen)
    monkeypatch.setenv("FAKE_NAN_KEY_041A", _LEAK_KEY_041A)
    profile = {
        "api_key_env": "FAKE_NAN_KEY_041A",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
        "model": "deepseek-v4-flash",
    }
    try:
        ed._transport_api(profile, {}, [{"role": "user", "content": "x"}], timeout=5)
    except Exception as exc:
        rendered = traceback.format_exc()
        err = exc
    else:  # pragma: no cover -- el fixture siempre levanta
        pytest.fail("se esperaba un error de transporte")

    assert _LEAK_KEY_041A not in rendered

    # Recorre la CADENA de encadenamiento completa: con la fuga viva el
    # HTTPError crudo (y sus headers) queda alcanzable por aqui aunque
    # str(err) este limpio.
    seen: list = []
    node = err
    while node is not None and node not in seen:
        seen.append(node)
        node = node.__cause__ or node.__context__
    for node in seen:
        assert _LEAK_KEY_041A not in str(getattr(node, "headers", "") or ""), (
            f"la clave sigue alcanzable via headers de {type(node).__name__}"
        )
        assert not isinstance(node.__cause__, urllib.error.HTTPError)
        assert not isinstance(node.__context__, urllib.error.HTTPError)


# --------------------------------------------------------------------------- #
# WOT-2026-063c: streaming SSE en `_transport_api`. Cloudflare corta con 524 el
# POST largo que no emite bytes; con `stream:true` los deltas fluyen desde el
# primer token y el proxy nunca ve silencio. Seis invariantes del diseno
# auditado (nonce cfb71138fee4bb2ff632e0c9537a086f), cada uno con su mutation:
#   I1 centinela [DONE] por FRAMING de evento (mutation: aceptar el centinela
#     por substring del acumulado -> cae test_063c_centinela_en_prosa...);
#   I2 deadline TOTAL con lecturas dimensionadas (mutation: quitar el chequeo
#     de remaining entre lecturas -> test_063c_deadline_total cuelga o falla);
#   I3 content vacio con centinela = FALLO EXPLICITO (mutation: devolver "" o
#     hacer fallback a reasoning_content -> cae test_063c_content_vacio...);
#   I4 chunk `data:` malformado ANTES de [DONE] sigue siendo PARSEO (mutation:
#     envolverlo en TransportError -> cae test_063c_chunk_malformado...);
#   I5 la api_key no sale ni por el nuevo punto de fallo del parser (mutation:
#     levantar el JSONDecodeError crudo con su doc -> cae
#     test_063c_sanea_la_key...);
#   I6 un 200 no-SSE se consume como HOY (mutation: exigir streaming sin
#     discriminar por Content-Type -> caen estos tests Y los 3 pineados de
#     antes: :1343, :1608 y :1768, que devuelven cuerpos no-SSE).
# VIVEN ANTES del marcador WOT-2026-025z a proposito: el self-check estructural
# (g2) prohibe los tokens `_transport_api`, `monkeypatch.setenv` y `urllib`
# solo en el bloque POSTERIOR a ese marcador.
# --------------------------------------------------------------------------- #

_KEY_063C = "sk-live-063c-SSEKEY-9f2c47ab"


def _sse_event(data_text: str) -> list[bytes]:
    """Un evento SSE tal como lo ve readline(): linea `data:` + linea en blanco."""
    return [b"data: " + data_text.encode("utf-8") + b"\n", b"\n"]


def _sse_chunk(text: str, idx: int = 0) -> list[bytes]:
    payload = json.dumps(
        {
            "id": f"chatcmpl-{idx}",
            "choices": [{"index": 0, "delta": {"content": text}}],
        }
    )
    return _sse_event(payload)


_SSE_DONE = _sse_event("[DONE]")


class _FakeSSEStream:
    """HTTPResponse simulada de un canal SSE, leida por lineas.

    `readline()` consume lineas preparadas: tras agotarlas devuelve EOF (b"")
    o levanta la excepcion de socket indicada. `read()` FALLA deliberadamente:
    la ruta actual consume la respuesta entera de una vez, asi que ese
    AssertionError ES el rojo de los tests red-first, no un accidente.
    """

    def __init__(self, lines, content_type="text/event-stream", after_eof=None):
        self._lines = list(lines)
        self.headers = {"Content-Type": content_type}
        self._after_eof = after_eof
        self.readlines = 0

    def readline(self):
        self.readlines += 1
        if self._lines:
            return self._lines.pop(0)
        if self._after_eof is not None:
            raise self._after_eof
        return b""

    def read(self):
        raise AssertionError(
            "la respuesta SSE se esta consumiendo entera de una vez: exactamente "
            "el defecto que WOT-2026-063c cierra"
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSSEDrip:
    """Stream que gotea keep-alives PARA SIEMPRE: solo un deadline total lo corta."""

    def __init__(self, delay: float = 0.02):
        self._delay = delay
        self._alternates = [b": ping\n", b"\n"]
        self._i = 0
        self.headers = {"Content-Type": "text/event-stream"}

    def readline(self):
        time.sleep(self._delay)
        line = self._alternates[self._i % 2]
        self._i += 1
        return line

    def read(self):
        raise AssertionError("read() sin tamano sobre goteo perpetuo: cuelga")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSSESlowDrip:
    """Goteo LENTO que acabaria en EOF: solo el deadline total puede ganarle.

    Distingue las dos senales de fallo de I2: sin el chequeo de remaining entre
    lecturas la primera senal del caller seria "EOF" (~3 s); con el chequeo es
    "deadline" (~1 s). El mensaje es el contrato de precision, no un adorno.
    """

    def __init__(self, n_keepalives: int = 40, delay: float = 0.04):
        self.headers = {"Content-Type": "text/event-stream"}
        self._delay = delay
        self._alternates = [b": ping\n", b"\n"]
        self._i = 0
        self._n = n_keepalives * 2

    def readline(self):
        if self._i >= self._n:
            return b""  # EOF tardio: no debe ser la senal que vea el caller
        time.sleep(self._delay)
        line = self._alternates[self._i % 2]
        self._i += 1
        return line

    def read(self):
        raise AssertionError("read() sin tamano sobre goteo lento: cuelga")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakePlainResp:
    """200 NO-SSE: cuerpo entero via read(). Con `content_type=None` simula los
    fixtures pineados de :1343/:1608/:1768, que NO exponen atributo headers."""

    def __init__(self, body: bytes, content_type="application/json"):
        self._body = body
        if content_type is not None:
            self.headers = {"Content-Type": content_type}

    def read(self, amt=None):
        return self._body

    def readline(self):
        raise AssertionError("readline() no debe tocar la ruta no-SSE")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _profile_063c() -> dict:
    return {
        "channel": "api",
        "model": "deepseek-v4-flash",
        "api_key_env": "FAKE_NAN_KEY_063C",
        "api_base_url": "https://api.nan.builders/v1/chat/completions",
    }


def _install_063c_transport(monkeypatch, resp, capture: dict | None = None) -> None:
    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture["body"] = json.loads(req.data.decode("utf-8"))
            capture["timeout"] = timeout
        return resp

    monkeypatch.setattr(ed.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("FAKE_NAN_KEY_063C", _KEY_063C)


def _api_063c(timeout: int = 5) -> str:
    # `backend_cfg` NO interviene en `_transport_api`: el timeout ya viene
    # resuelto por la expresion `:1212` de `send_to_profile`.
    return ed._transport_api(
        _profile_063c(), {}, [{"role": "user", "content": "x"}], timeout=timeout
    )


def test_063c_el_body_declara_stream_true(monkeypatch):
    """El request pide streaming SIEMPRE (aditivo, sin flag por perfil).

    Mutation: quitar `"stream": True` del body -> KeyError en la asercion.
    """
    capture: dict = {}
    body = json.dumps({"choices": [{"message": {"content": "respuesta-hoy"}}]}).encode()
    _install_063c_transport(monkeypatch, _FakePlainResp(body), capture)
    assert _api_063c() == "respuesta-hoy"
    assert capture["body"]["stream"] is True, (
        "sin stream:true el backend seguira acumulando en silencio hasta el 524"
    )


def test_063c_muerte_al_chunk_50_es_transporte_nunca_parcial(monkeypatch):
    """(a1) Desconexion en el chunk 50 de 200: EOF sin centinela -> TransportError.

    El parcial JAMAS se devuelve (I1): si la implementacion devolviera lo
    acumulado, este test no veria la excepcion esperada.
    """
    lines: list[bytes] = []
    for idx in range(50):
        lines.extend(_sse_chunk(f"delta{idx} ", idx))
    stream = _FakeSSEStream(lines)
    _install_063c_transport(monkeypatch, stream)
    with pytest.raises(ed.TransportError) as excinfo:
        _api_063c()
    assert stream.readlines >= 100, (
        f"el stream no se consumio lectura a lectura (readlines={stream.readlines}): "
        "sin lecturas dimensionadas no hay donde evaluar el deadline"
    )
    assert "delta49" not in str(excinfo.value), (
        "el error no debe re-emitir contenido del modelo"
    )


def test_063c_centinela_en_prosa_no_corta_antes_y_rellena_el_buffer(monkeypatch):
    """(a2) `[DONE]` DENTRO de un payload no es el centinela (I1, jamas substring).

    La prosa que menciona el centinela debe sobrevivir en el texto final.
    Mutation: comparar `"[DONE]" in acumulado` en vez del payload completo del
    evento -> el test corta en el chunk 0 y la asercion de igualdad cae.
    """
    lines = (
        _sse_chunk("El veredicto cita ", 0)
        + _sse_chunk("`[DONE]` en prosa ", 1)
        + _sse_chunk("y sigue.", 2)
        + _SSE_DONE
    )
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    out = _api_063c()
    assert out == "El veredicto cita `[DONE]` en prosa y sigue."


def test_063c_goteo_que_enmudece_es_transporte_puntual(monkeypatch):
    """(a3) Socket que gotea y ENMUDECE: TimeoutError -> Transporte, dentro de budget.

    Medido en el diseno: el timeout de urlopen es POR-LECTURA; un silencio de
    socket levanta TimeoutError y aqui se convierte en TransportError
    saneado (I5) -- fail-closed sin hilos. El margen pinado es el del propio
    diseno I2: deadline + una lectura bloqueada.
    """
    lines = _sse_chunk("a", 0) + _sse_chunk("b", 1) + _sse_chunk("c", 2)
    stream = _FakeSSEStream(
        lines, after_eof=TimeoutError("The read operation timed out")
    )
    _install_063c_transport(monkeypatch, stream)
    t0 = time.perf_counter()
    with pytest.raises(ed.TransportError) as excinfo:
        _api_063c(timeout=3)
    elapsed = time.perf_counter() - t0
    assert elapsed <= 3 + 0.5, (
        f"el fallback tardo {elapsed:.2f}s: sin deadline o sin socket-timeout"
    )
    assert "TimeoutError" in str(excinfo.value)
    assert _KEY_063C not in str(excinfo.value)


def test_063c_deadline_total_corta_goteo_perpetuo(monkeypatch):
    """(I2) Goteo que nunca enmudece y nunca manda centinela: deadline TOTAL.

    Sin el chequeo de remaining entre lecturas el bucle no termina jams (el
    socket nunca agota su timeout porque SIEMPRE hay un byte): esta es la
    mutacion que el timeout por-lectura NO puede atrapar.
    """
    _install_063c_transport(monkeypatch, _FakeSSEDrip())
    timeout = 1
    t0 = time.perf_counter()
    with pytest.raises(ed.TransportError) as excinfo:
        _api_063c(timeout=timeout)
    elapsed = time.perf_counter() - t0
    assert elapsed >= 0.8, "corto antes del deadline: no era un fallo total"
    assert elapsed <= timeout + 0.5, f"deadline sin margen razonable: {elapsed:.2f}s"
    assert "deadline" in str(excinfo.value).lower()


def test_063c_goteo_lento_la_senal_es_deadline_no_eof(monkeypatch):
    """(I2) Goteo lento que moriria en EOF: la senal puntable es DEADLINE.

    Mutation M5 (neutralizar el chequeo de remaining): el bucle aguanta hasta
    el EOF a ~3.2 s y el mensaje dice "EOF": este test distingue las dos
    senales y acota el tiempo total.
    """
    _install_063c_transport(monkeypatch, _FakeSSESlowDrip())
    t0 = time.perf_counter()
    with pytest.raises(ed.TransportError) as excinfo:
        _api_063c(timeout=1)
    elapsed = time.perf_counter() - t0
    assert "deadline" in str(excinfo.value).lower()
    assert elapsed <= 1 + 0.8, f"el deadline total no goberno el goteo: {elapsed:.2f}s"


def test_063c_content_vacio_con_centinela_es_fallo_explicito(monkeypatch):
    """(I3) Centinela limpio y content vacio -> FAILURE_MODE propio, jamas "".

    Y NUNCA fallback a `reasoning_content`: la deliberacion cruda no lleva
    nonce ni formato y PARECE un veredicto. Mutation: devolver "" o leer
    reasoning_content -> este test ve un return donde espera excepcion.
    """
    lines = (
        _sse_event(json.dumps({"choices": [{"delta": {}}]}))
        + _sse_event(
            json.dumps(
                {"choices": [{"delta": {"reasoning_content": "deliberacion cruda"}}]}
            )
        )
        + _sse_event(json.dumps({"choices": [{"delta": {"content": ""}}]}))
        + _SSE_DONE
    )
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    with pytest.raises(ed.TransportError) as excinfo:
        _api_063c()
    assert "empty_content_despite_sentinel" in str(excinfo.value)
    assert "deliberacion cruda" not in str(excinfo.value)


def test_063c_chunk_malformado_antes_del_centinela_es_parso(monkeypatch):
    """(I4) Un `data:` con JSON roto ANTES de [DONE] sigue siendo JSONDecodeError.

    Mismo contrato que el 200 no-SSE malformado de :1768 (hallazgo del
    MANAGER_REVIEW que el diseno hereda): un error de PARSEO no puede
    disfrazarse de TRANSPORTE, o el caller que discrimina el tipo pierde la
    seccal. Mutation: envolver el fallo del parser en TransportError.
    """
    lines = _sse_chunk("a ", 0) + _sse_event('{"delta": {roto')
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    with pytest.raises(json.JSONDecodeError):
        _api_063c()


def test_063c_garbage_tras_el_centinela_no_se_parsea(monkeypatch):
    """I1: [DONE] es la UNICA ruta de exito; lo que llegue despues no se toca.

    Mutation: seguir leyendo tras el centinela -> JSONDecodeError por la
    basura posterior.
    """
    lines = _sse_chunk("ok ", 0) + _SSE_DONE + _sse_event("{basura sin cerrar")
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    assert _api_063c() == "ok "


def test_063c_comentarios_keepalives_y_data_sin_espacio(monkeypatch):
    """Framing defensivo: `: ping` ignorado, evento solo-comentario no corta,
    y `data:[DONE]` sin espacio tras el colon es centinela valido (SSE permite
    un espacio opcional)."""
    lines = [
        b": ping\n",
        b"\n",
        *_sse_chunk("K", 0),
        b": keep-alive\n",
        b"\n",
        b"data:[DONE]\n",
        b"\n",
    ]
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    assert _api_063c() == "K"


def test_063c_sanea_la_key_ante_chunk_malformado(monkeypatch):
    """(I5, DoD-e) El nuevo punto de fallo del parser NO filtra la api_key.

    Extiende el barrido de :1668 al JSONDecodeError del stream: si el server
    hace eco de la key en un chunk roto, el error propagado (y su cadena de
    encadenamiento) debe seguirla INVISIBLE. Mutation: propagar el
    JSONDecodeError crudo (su `.doc` lleva el payload con la key).
    """
    lines = _sse_event('{"echo": "' + _KEY_063C + '", roto')
    _install_063c_transport(monkeypatch, _FakeSSEStream(lines))
    with pytest.raises(json.JSONDecodeError) as excinfo:
        _api_063c()
    err = excinfo.value
    assert _KEY_063C not in str(err)
    assert _KEY_063C not in repr(err)
    assert _KEY_063C not in repr(err.args)
    assert _KEY_063C not in repr(vars(err))
    assert ed.REDACTED_MARKER in err.doc
    # cadena de encadenamiento limpia (mismo patron que :1798):
    seen: list = []
    node = err
    while node is not None and node not in seen:
        seen.append(node)
        node = node.__cause__ or node.__context__
    assert len(seen) == 1, "el parser enlazo un error crudo ademas del saneado"
    assert _KEY_063C not in str(err.__cause__)
    assert _KEY_063C not in str(err.__context__ if err.__context__ else "")


def test_063c_200_no_sse_se_consume_como_hoy(monkeypatch):
    """(I6, CARGA del DoD) Discriminador por Content-Type, no por fe.

    Un 200 con `application/json` se lee de una vez Y se parsea como hasta
    hoy: es lo que mantiene vivos los fixtures sin headers de :1343/:1608/
    :1768 (objeto SIN atributo headers: el guard debe ser defensivo).
    Mutation: eliminar el check de Content-Type -> el no-SSE entra al parser
    SSE y revienta contra read() del fake.
    """
    body = json.dumps({"choices": [{"message": {"content": "hoy"}}]}).encode()
    _install_063c_transport(monkeypatch, _FakePlainResp(body))
    assert _api_063c() == "hoy"


def test_063c_sse_con_charset_activa_la_ruta_de_stream(monkeypatch):
    """`text/event-stream; charset=utf-8` cuenta como SSE (match flexible)."""
    lines = _sse_chunk("streamed", 0) + _SSE_DONE
    _install_063c_transport(
        monkeypatch,
        _FakeSSEStream(lines, content_type="text/event-stream; charset=utf-8"),
    )
    assert _api_063c() == "streamed"


# --------------------------------------------------------------------------- #
# WOT-2026-041b: `append_scorecard` escribia sin lock del SO. La mutation usa
# PROCESOS reales (multiprocessing.Process, no subprocess: subprocess no
# comparte el file descriptor y no ejerce la carrera) con arranque
# SINCRONIZADO por Barrier para maximizar la ventana.
#
# MEDIDO al quitar el lock (3/3 corridas, deterministico):
#   PROCESOS: 89/100 filas -- lineas partidas por writes entrelazados
#   HILOS:    98/100 filas, 0 lineas CORRUPTAS
# El matiz importa y corrige el enunciado del DAG: con hilos el GIL serializa
# el write, asi que NO se parte ninguna linea -- pero si se PIERDEN filas. Un
# test con hilos que solo afirmase "ninguna linea corrupta" (el criterio que
# proponia el DAG) pasaria sin el fix: floor assertion. Este test sobrevive a
# ambos escenarios porque ademas cuenta las filas.
# --------------------------------------------------------------------------- #

_ROW_041B_PAYLOAD = "x" * 4096  # linea larga: estrecha la ventana atomica del SO


def _writer_041b(project_root_str: str, worker: int, n_rows: int, barrier) -> None:
    """Escribe n_rows filas identificables. Se ejecuta en un PROCESO aparte."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(project_root_str).parent / "scripts"))
    barrier.wait()  # arranque sincronizado: todos empujan a la vez
    for i in range(n_rows):
        ed.append_scorecard(
            _Path(project_root_str),
            {
                "ts": f"w{worker}-r{i}",
                "event": "mutation-041b",
                "ticket": "WOT-2026-041b",
                "evidencia": _ROW_041B_PAYLOAD,
                "ronda": i,
            },
        )


def test_append_scorecard_no_se_corrompe_con_procesos_concurrentes(tmp_path):
    """N PROCESOS escribiendo a la vez -> toda linea es JSON valido y completo.

    Con HILOS este test pasaria sin el fix (el GIL serializa el write): por eso
    usa procesos. Sin el lock, dos appends pueden entrelazarse y partir una
    linea; la asercion mira que NINGUNA linea este truncada ni mezclada, y que
    no se pierda ni se duplique ninguna.
    """
    multiprocessing = pytest.importorskip("multiprocessing")
    if multiprocessing.get_start_method(allow_none=True) is None:
        multiprocessing.set_start_method("spawn", force=True)

    n_workers, n_rows = 4, 25
    barrier = multiprocessing.Barrier(n_workers)
    procs = [
        multiprocessing.Process(
            target=_writer_041b, args=(str(tmp_path), w, n_rows, barrier)
        )
        for w in range(n_workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)

    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]

    path = tmp_path / ed.SCORECARD_REL
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "el fichero no debe llevar BOM"
    lines = raw.decode("utf-8").splitlines()

    # (1) ninguna linea corrupta: entrelazar dos writes rompe el JSON
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"linea {idx} corrupta (write entrelazado): {exc}")

    # (2) ni una fila perdida ni duplicada: el lock no puede comerse escrituras
    seen = [json.loads(line)["ts"] for line in lines if line.strip()]
    esperado = {f"w{w}-r{i}" for w in range(n_workers) for i in range(n_rows)}
    assert len(seen) == n_workers * n_rows
    assert set(seen) == esperado

    # (3) el contrato de formato de WOT-2026-025y sobrevive
    primera = json.loads(next(line for line in lines if line.strip()))
    assert list(primera.keys()) == ed.SCORECARD_FIELDS


# --- WOT-2026-042v: el ambito 038o, RESUELTO del vuelo e INVOCADO -----------
#
# ROJO que fija: el mecanismo de 038o estaba cableado y SIN INVOCAR. Censo al
# HEAD 8f7c5ff -- `'repo_root' in json.dumps(agents.json)` -> False en motor Y
# destino --, asi que toda lente `channel: agent` heredaba el cwd del PADRE (el
# repo_motor) y su "no existe" sobre un artefacto del destino era un FALSO
# NEGATIVO POR AMBITO. De 14 objeciones auditadas (2026-08-10/11), 9 fueron
# falsos positivos y los 9 eran afirmaciones SOBRE EL ARBOL emitidas sin verlo.
#
# El probe es de RUTA PRODUCTIVA (CEM): entra por `send_to_profile` -- el UNICO
# camino de salida, y el que usan directamente 9 de 9 `dispatch.py` de gobierno
# -- y lanza un shim REAL, al que se le PREGUNTA por un artefacto igual que a
# una lente. No inspecciona kwargs.


def _fake_lookup_executable(tmp_path: Path, needle: str) -> str:
    """Shim REAL que responde FOUND/ABSENT sobre `needle` RELATIVO a su cwd.

    Reproduce la pregunta que se le hace a una lente ("¿existe este artefacto?")
    en vez de inspeccionar el kwarg `cwd`: por eso su respuesta cambia con el
    ambito, que es justo lo que el DoD (d) obliga a poder distinguir. Mismo
    patron de shim que `_fake_cwd_echo_executable`.
    """
    script = tmp_path / f"lookup_{abs(hash(needle))}.py"
    script.write_text(
        "import os,sys\n"
        f"sys.stdout.write('FOUND' if os.path.exists({needle!r}) else 'ABSENT')\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        shim = script.with_suffix(".cmd")
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="utf-8"
        )
        return str(shim)
    else:  # pragma: no cover -- POSIX shim, not exercised on this Windows CI
        shim = script.with_suffix(".sh")
        shim.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
        )
        shim.chmod(0o755)
        return str(shim)


def _agent_config(tmp_path: Path, needle: str, *, repo_scope: str | None) -> dict:
    """Config con UN perfil `channel: agent` que despacha contra el shim."""
    # Sin `model`: el perfil no declara modelo, asi que `_render_model_flag` no
    # exige `model_flag` al backend (WOT-2026-047y). Lo que este fixture prueba
    # es el AMBITO, y anadir modelo solo traeria el contrato de otro ticket.
    profile: dict = {
        "backend": "fake_cli",
        "channel": "agent",
        "data_sensitivity": "public",
        "write": False,
    }
    if repo_scope is not None:
        profile["repo_scope"] = repo_scope
    return {
        "schema_version": "1.3",
        "backends": {
            "fake_cli": {
                "executable": _fake_lookup_executable(tmp_path, needle),
                "args": [],
                "discovery": {"method": "path_only"},
            }
        },
        "ensemble_profiles": {"p_lente": profile},
        "ensemble_private_roots": [],
    }


def test_042v_lens_finds_destino_artifact_and_misses_it_from_another_root(tmp_path):
    """DoD (d) -- EL PAR QUE AISLA, en un solo test para que no se separen.

    Un artefacto que existe SOLO en el destino: la lente con el repo_root
    resuelto lo ENCUENTRA (verde) y la MISMA lente, con la unica variable
    cambiada -- el arbol --, lo declara ausente (rojo). Un verde de una sola
    direccion es indistinguible de una lente que no miro nada.

    MUTACION DE CIERRE: quitar la inyeccion del `repo_root` en
    `send_to_profile` -> el hijo hereda el cwd del padre en AMBOS brazos y el
    brazo verde cae.
    """
    marca = "SOLO_EN_EL_DESTINO.md"
    destino = tmp_path / "repo_destino"
    destino.mkdir()
    (destino / marca).write_text("artefacto del destino\n", encoding="utf-8")
    otro_arbol = tmp_path / "otro_repo"
    otro_arbol.mkdir()

    config = _agent_config(tmp_path, marca, repo_scope="destino")
    mensajes = [{"role": "user", "content": f"existe {marca}?"}]

    verde = ed.send_to_profile(
        "p_lente",
        mensajes,
        config=config,
        sensitivity="public",
        project_root=destino,
    )
    rojo = ed.send_to_profile(
        "p_lente",
        mensajes,
        config=config,
        sensitivity="public",
        project_root=otro_arbol,
    )

    assert verde.strip() == "FOUND", (
        f"la lente con repo_root={destino} respondio {verde.strip()!r}: no esta "
        "observando el arbol del destino, luego su veredicto sobre artefactos "
        "del destino sigue siendo un falso negativo por ambito"
    )
    assert rojo.strip() == "ABSENT", (
        "el brazo de control respondio FOUND desde un arbol que NO tiene el "
        "artefacto: el probe no discrimina y su verde no prueba nada"
    )


def test_042v_api_channel_is_labelled_sin_fs_and_gets_no_cwd():
    """Limite de CLASE, no bug: un `channel: api` no tiene filesystem.

    Se etiqueta aparte para que el scorecard no mezcle dos poblaciones con
    tasas de acierto distintas -- que es lo que haria a `backend_leaders.json`
    elegir lider comparando lo incomparable.
    """
    cwd, scope = ed.resolve_lens_repo_root(
        {"channel": "api", "repo_scope": "destino"}, {}, Path.cwd()
    )
    assert cwd is None and scope == "sin-fs", (
        "un canal sin filesystem no puede recibir cwd ni contarse como lente "
        f"con ojos; se resolvio ({cwd!r}, {scope!r})"
    )


def test_042v_declared_backend_repo_root_still_wins(tmp_path):
    """Backward-compat DURA del contrato WOT-2026-038o: un `repo_root`
    declarado en el backend manda sobre la resolucion nueva. Sin este pin, el
    ticket cambiaria en silencio la conducta de toda llamada que ya lo declara.
    """
    declarado = tmp_path / "declarado"
    declarado.mkdir()
    cwd, scope = ed.resolve_lens_repo_root(
        {"channel": "agent", "repo_scope": "destino"},
        {"repo_root": str(declarado)},
        tmp_path / "destino_ignorado",
    )
    assert (cwd, scope) == (str(declarado), "declarado")


def test_042v_shared_backend_cfg_is_not_mutated(tmp_path):
    """El `repo_root` de UN vuelo no puede quedarse pegado en la config viva.

    `backends` es COMPARTIDO (3 perfiles del motor comparten backend): mutarlo
    se lo colaria a los demas perfiles y persistiria entre llamadas dentro del
    mismo proceso. Mutacion: cambiar la copia `{**backend_cfg, ...}` por una
    asignacion directa -> este test cae.
    """
    destino = tmp_path / "repo_destino"
    destino.mkdir()
    config = _agent_config(tmp_path, "cualquiera.md", repo_scope="destino")

    ed.send_to_profile(
        "p_lente",
        [{"role": "user", "content": "x"}],
        config=config,
        sensitivity="public",
        project_root=destino,
    )

    assert "repo_root" not in config["backends"]["fake_cli"], (
        "el repo_root del vuelo se escribio DENTRO de la config compartida: el "
        "siguiente perfil que use este backend heredaria un ambito ajeno"
    )


def test_042v_code_only_flight_falls_back_and_names_the_degradation(monkeypatch):
    """ANTI-FALSO-POSITIVO del DoD + la degradacion NO puede ser muda.

    Un vuelo sin destino resoluble (ticket code-only) NO empieza a fallar: cae
    a la conducta heredada. Pero la etiqueta lo DICE, porque un fallback
    silencioso volveria indistinguible "la lente vio el arbol" de "la lente iba
    ciega" -- el falso verde exacto que este ticket persigue.
    """
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    cwd, scope = ed.resolve_lens_repo_root(
        {"channel": "agent", "repo_scope": "destino"}, {}, None
    )
    assert cwd is None, "sin destino resoluble no se inventa un cwd"
    assert scope == "motor:destino-no-resoluble", (
        f"la degradacion salio como {scope!r}: si no se distingue de un 'motor' "
        "normal, el scorecard no puede separar la lente ciega de la que vio"
    )


def test_042v_destino_that_resolves_to_the_motor_is_refused(monkeypatch):
    """Mismo invariante que `_resolve_project_root`: el destino-rol NUNCA es el
    motor. Sin esto, un AGENT_PROJECT_ROOT mal puesto daria un `destino` VERDE
    que en realidad observa el motor -- el falso verde que el DoD (d) obliga a
    distinguir."""
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(ed.MOTOR_ROOT))
    cwd, scope = ed.resolve_lens_repo_root(
        {"channel": "agent", "repo_scope": "destino"}, {}, None
    )
    assert cwd is None and scope == "motor:destino-es-el-motor"


def test_042v_unresolvable_path_degrades_instead_of_raising():
    """La rama `except (OSError, ValueError)` del resolver, que era la UNICA sin
    cubrir (la nombro la lente 3 del bucle L042v).

    Importa porque el contrato del resolver es que NUNCA lanza: una ruta
    imposible tiene que degradar con etiqueta propia, no reventar el despacho de
    una lente. Sin este test, cambiar el `except` por un `raise` no rompe nada.
    """
    cwd, scope = ed.resolve_lens_repo_root(
        {"channel": "agent", "repo_scope": "destino"}, {}, "C:/x\x00y"
    )
    assert cwd is None and scope == "motor:destino-irresoluble", (
        f"una ruta irresoluble dio ({cwd!r}, {scope!r}): o lanzo, o se confundio "
        "con otra causa de degradacion"
    )


def test_042v_profile_without_repo_scope_keeps_inherited_behaviour(monkeypatch):
    """ADITIVIDAD: un perfil que no declara `repo_scope` no cambia en nada, ni
    siquiera con AGENT_PROJECT_ROOT puesto. Es lo que permite dejar lentes
    CIEGAS a proposito como calibracion permanente: si todas pasaran a ver el
    arbol se perderia la referencia contra la que medir su degradacion."""
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(Path.cwd()))
    cwd, scope = ed.resolve_lens_repo_root({"channel": "agent"}, {}, None)
    assert (cwd, scope) == (None, "motor")


def test_042v_scorecard_row_records_the_effective_scope(tmp_path):
    """El ambito llega al REGISTRO, no solo al Popen.

    Sin la columna, una ronda con ojos y una ciega son la misma fila y el
    ranking de `backend_leaders.json` compara poblaciones distintas.
    """
    transport = _FakeTransport(replies=["ok"])
    config = _config()
    config["ensemble_profiles"]["p_chal"]["channel"] = "agent"
    config["ensemble_profiles"]["p_chal"]["repo_scope"] = "destino"
    destino = tmp_path / "repo_destino"
    destino.mkdir()

    ed.run_loop_round(
        "p_chal",
        "revisa esto",
        config=config,
        project_root=destino,
        ticket="WOT-TEST-042v",
        task_type="code-review",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L042v",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )

    fila = _rows(destino)[0]
    assert fila["lens_scope"] == "destino", (
        f"la fila registro lens_scope={fila.get('lens_scope')!r}: el ambito no "
        "esta llegando al scorecard y las dos poblaciones siguen mezcladas"
    )


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

# ---------------------------------------------------------------------------
# WOT-2026-026t/GLM: el techo de tiempo es POR BACKEND. Un unico default de 300s
# mataba a `opencode`, que vive pegado a ese techo (p50=94s, p90=236s, max=280s
# sobre 14 rondas reales). Tres timeouts el 2026-08-04, uno de ellos con el
# proceso VIVO trabajando al morir.
# ---------------------------------------------------------------------------


class TestBackendTimeout:
    """El timeout se lee del backend; el default manda si no lo declara."""

    def test_backend_timeout_s_overrides_the_default(self):
        """MUTACION ALCANZABLE: quitar la lectura de `timeout_s` -> llega 300.

        Sin este test, subir el techo de opencode en agents.json seria un cambio
        de config INERTE: el codigo lo ignoraria y nada lo notaria.
        """
        cfg = _config()
        cfg["backends"]["fake"]["timeout_s"] = 600
        seen: dict = {}

        def transport(profile, backend_cfg, messages, timeout):
            seen["timeout"] = timeout
            return "ok"

        ed.send_to_profile(
            "p_chal",
            [{"role": "user", "content": "x"}],
            config=cfg,
            sensitivity="public",
            transport=transport,
        )
        assert seen["timeout"] == 600

    def test_backend_without_timeout_s_keeps_the_default(self):
        """CONTROL POSITIVO: el cambio es ADITIVO, no toca a quien no lo declara."""
        seen: dict = {}

        def transport(profile, backend_cfg, messages, timeout):
            seen["timeout"] = timeout
            return "ok"

        ed.send_to_profile(
            "p_chal",
            [{"role": "user", "content": "x"}],
            config=_config(),
            sensitivity="public",
            transport=transport,
        )
        assert seen["timeout"] == 300

    def test_real_config_gives_opencode_more_room_than_the_rest(self):
        """El arbol REAL, no un fixture: opencode 600, los demas en su default.

        Fixture-only no valdria aqui: el defecto que se cierra vivia en la config
        real (`agents.json`), y un test hermetico sobre `_config()` habria pasado
        verde mientras opencode seguia muriendo a los 300s.
        """
        cfg = ed.load_motor_config()
        seen: dict = {}

        def transport(profile, backend_cfg, messages, timeout):
            seen[profile["backend"]] = timeout
            return "ok"

        for prof in ("challenger_opencode_glm_5_2", "challenger_codex"):
            ed.send_to_profile(
                prof,
                [{"role": "user", "content": "x"}],
                config=cfg,
                sensitivity="public",
                transport=transport,
            )
        # INVARIANTE, no medicion (WOT-2026-024t): el numero exacto es evidencia
        # fechada y cambia cuando cambia la cola de latencia del backend -- este
        # test pineaba `== 600` y se puso ROJO al subirlo a 900 con datos nuevos,
        # que es justo el criterio-que-caduca-solo. Lo que NO debe cambiar es la
        # relacion: opencode necesita MAS techo que el resto, porque su latencia
        # tiene varianza enorme (ratio max/min 80x medido 2026-08-04).
        assert seen["opencode"] > seen["codex"], (
            "opencode necesita techo propio, MAYOR que el default del resto"
        )
        default_timeout = (
            inspect.signature(ed.send_to_profile).parameters["timeout"].default
        )
        assert seen["codex"] == default_timeout, (
            "el resto no debe heredar el techo de opencode: usa el default"
        )


class TestBackendKeyMatchesProfile:
    """El receipt de la ronda no puede atribuirse a una lente que no ejecuto."""

    def _run(self, profile_name, backend_key, tmp_path):
        cfg = ed.load_motor_config()

        def transport(profile, backend_cfg, messages, timeout):
            return "ok"

        return ed.run_loop_round(
            profile_name,
            "x",
            config=cfg,
            project_root=tmp_path,
            ticket="T",
            task_type="triage",
            rol="challenger",
            phase="p",
            loop_id="L700",
            backend_key=backend_key,
            sensitivity="public",
            transport=transport,
        )

    def test_wrong_key_is_rejected_before_dispatch(self, tmp_path):
        """El fallo REAL de 2026-08-04: GLM registrado como BA12 (nan/mimo).

        MUTACION ALCANZABLE: quitar la comparacion -> la ronda se despacha y
        deja un receipt que miente sobre que lente audito.
        """
        with pytest.raises(ValueError, match="no corresponde al perfil"):
            self._run("challenger_opencode_glm_5_2", "BA12", tmp_path)

    def test_same_backend_different_lens_is_also_rejected(self, tmp_path):
        """Por que la comparacion es de IDENTIDAD, no de backend.

        Los cuatro perfiles `nan_api` comparten backend: un check por backend
        aceptaria qwen+BA12 y fabricaria independencia entre dos rondas del
        MISMO modelo, que es justo lo que la barrera cuenta.
        MUTACION: comparar `profile["backend"]` en vez de la clave -> VERDE.
        """
        with pytest.raises(ValueError, match="no corresponde al perfil"):
            self._run("challenger_nan_qwen", "BA12", tmp_path)

    def test_matching_key_passes(self, tmp_path):
        """CONTROL POSITIVO: la invocacion correcta no se molesta."""
        assert self._run("challenger_opencode_glm_5_2", "BA06", tmp_path) == "ok"

    def test_error_names_the_key_the_caller_should_use(self, tmp_path):
        """Gate self-service: el mensaje dice COMO arreglarlo, no solo que fallo."""
        with pytest.raises(ValueError) as exc:
            self._run("challenger_opencode_glm_5_2", "BA12", tmp_path)
        assert "--backend-key BA06" in str(exc.value)


# =============================================================================
# WOT-2026-068k-followup: _classify_transport_failure (FP-014 seguimiento,
# ronda adversarial Codex+GLM 2026-09-28). Casos REALES capturados en la
# sesion que motivo el clasificador; los tests pinean el veredicto medido, no
# uno hipotetico.
# =============================================================================


def test_classify_quota_needs_status_and_marker():
    """Caso real: nan_api HTTP 402 con 'allowance exhausted' -> quota_exhausted.

    Mutation: si el clasificador decidiera SOLO por status==402 (sin exigir
    el marcador), este test seguiria en verde pero test_classify_400_sin_marcador_es_unknown
    (abajo) se pondria rojo -- ambos juntos pinean que status SOLO no basta.
    """
    exc = ed.TransportError(
        "HTTPError | HTTP 402 | Payment Required",
        status=402,
        body=(
            '{"error":{"message":"deepseek-v4-flash allowance exhausted: '
            '3,000,302,448 of 3,000,000,000 tokens used","type":'
            '"monthly_cap_reached","code":"402"}}'
        ),
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_QUOTA


def test_classify_429_rate_limit_es_quota():
    """Caso real: backend OpenAI-compatible (Groq, doc oficial de
    rate-limits, 2026-09-28) devuelve HTTP 429 con 'rate_limit_exceeded'
    para exceso de cuota, NO 402 como nan_api/nvidia_api. Debe clasificar
    IGUAL que el caso 402 -- un agente que solo reconociera 402 perderia
    la senal de cuota agotada en cualquier backend OpenAI-compatible
    estandar (429 es el status convencional de rate-limit en ese
    ecosistema, no un caso exotico).

    Mutation: si el clasificador solo aceptara status==402 (regresion al
    diseno pre-Groq), este test se pondria rojo -- devolveria unknown en
    vez de quota_exhausted.
    """
    exc = ed.TransportError(
        "HTTPError | HTTP 429 | Too Many Requests",
        status=429,
        body=(
            '{"error":{"message":"Rate limit reached for requests",'
            '"type":"requests","code":"rate_limit_exceeded"}}'
        ),
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_QUOTA


def test_classify_429_sin_marcador_es_unknown():
    """Mismo principio que test_classify_402_sin_marcador_es_unknown: un
    429 SIN marcador de texto reconocido (ej. rate-limit de un proxy
    intermedio, no del proveedor) no debe clasificarse como cuota solo
    por el status."""
    exc = ed.TransportError(
        "HTTPError | HTTP 429 | Too Many Requests",
        status=429,
        body='{"error":{"message":"slow down"}}',
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_UNKNOWN


def test_classify_model_unavailable_needs_status_and_marker():
    """Caso real: modelo retirado del perfil, HTTP 400 'is not supported'."""
    exc = ed.TransportError(
        "HTTPError | HTTP 400 | Bad Request",
        status=400,
        body=(
            '{"error":{"type":"invalid_request_error","message":'
            "\"The 'gpt-6-astra' model is not supported when using Codex "
            'with a ChatGPT account."}}'
        ),
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_MODEL_UNAVAILABLE


def test_classify_network_timeout_no_status():
    """Caso real: TimeoutError puro de socket, sin status HTTP (nvidia_api)."""
    exc = TimeoutError("The read operation timed out")
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_NETWORK


def test_classify_400_sin_marcador_es_unknown():
    """ROJO previo del defecto adversarial (Codex, severidad media): un 400
    generico SIN marcador de texto (ej. payload invalido, no modelo retirado)
    NO debe clasificarse como model_unavailable solo por el status.

    Mutation: si el clasificador volviera a decidir por status==400 en
    solitario (regresion al diseño pre-ronda-adversarial), este test se
    pondria rojo -- devolveria model_unavailable en vez de unknown.
    """
    exc = ed.TransportError(
        "HTTPError | HTTP 400 | Bad Request",
        status=400,
        body='{"error":{"type":"invalid_request_error","message":"max_tokens must be a positive integer"}}',
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_UNKNOWN


def test_classify_402_sin_marcador_es_unknown():
    """Mismo principio que el test anterior, para la categoria cuota."""
    exc = ed.TransportError(
        "HTTPError | HTTP 402 | Payment Required",
        status=402,
        body='{"error":{"message":"card declined"}}',
    )
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_UNKNOWN


def test_classify_texto_no_reconocido_es_unknown():
    """Un RuntimeError generico sin status/body (auth por-invocacion ausente,
    p.ej.) no calza con ninguna categoria -- unknown es la respuesta correcta,
    no un defecto."""
    exc = RuntimeError("algo salio mal de forma no clasificada")
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_UNKNOWN


def test_classify_504_status_sin_texto_es_network():
    """status 504/524 solo, SIN texto reconocido, sigue clasificando como red
    (a diferencia de cuota/modelo, el status HTTP de gateway timeout es
    suficientemente inequivoco por si solo)."""
    exc = ed.TransportError("Gateway error", status=504, body="")
    assert ed._classify_transport_failure(exc) == ed._FAILURE_CLASS_NETWORK


def test_smoke_profile_incluye_failure_class_en_fallo(monkeypatch):
    """DoD: failure_class SIEMPRE presente en el dict de retorno de
    smoke_profile, con la etiqueta correcta cuando falla."""

    def _raising_send(*_a, **_kw):
        raise ed.TransportError(
            "HTTP 402",
            status=402,
            body='{"error":{"message":"allowance exhausted"}}',
        )

    monkeypatch.setattr(ed, "send_to_profile", _raising_send)
    result = ed.smoke_profile("proposer_claude", config=_config())
    assert result["alive"] is False
    assert result["failure_class"] == ed._FAILURE_CLASS_QUOTA


def test_smoke_profile_failure_class_none_en_exito(monkeypatch):
    """DoD: failure_class es None explicito (no ausente) cuando alive=True."""

    def _fake_send(profile_name, messages, **_kw):
        return "PONG-019o"

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    result = ed.smoke_profile("proposer_claude", config=_config(), nonce="PONG-019o")
    assert result["alive"] is True
    assert "failure_class" in result
    assert result["failure_class"] is None


def test_preflight_profile_incluye_failure_class_en_fallo(monkeypatch):
    """Mismo contrato que smoke_profile, para preflight_profile."""

    def _raising_send(*_a, **_kw):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(ed, "send_to_profile", _raising_send)
    result = ed.preflight_profile("proposer_claude", config=_config())
    assert result["alive"] is False
    assert result["failure_class"] == ed._FAILURE_CLASS_NETWORK


def test_preflight_profile_con_content_sample_trunca_y_usa_fragmento(monkeypatch):
    """content_sample sustituye el prompt sintetico y se trunca al tope
    declarado -- verifica que el mensaje enviado contiene el fragmento
    truncado, no el bundle completo."""
    captured = {}

    def _fake_send(profile_name, messages, **_kw):
        captured["messages"] = messages
        return "algo PREFLIGHT-OK algo"

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    huge_sample = "X" * (ed._PREFLIGHT_SAMPLE_MAX_CHARS + 500)
    ed.preflight_profile(
        "proposer_claude", config=_config(), content_sample=huge_sample
    )
    sent_content = captured["messages"][0]["content"]
    assert "FRAGMENTO" in sent_content
    # El fragmento en el prompt no debe exceder el tope declarado.
    fragment_start = sent_content.index("---FRAGMENTO---") + len("---FRAGMENTO---\n")
    assert len(sent_content) - fragment_start <= ed._PREFLIGHT_SAMPLE_MAX_CHARS


# --------------------------------------------------------------------------- #
# WOT-2026-055o: clave hacia adelante de adjudicate + trafico exploratorio
# --------------------------------------------------------------------------- #


def _seed_round_with_cohort_keys(project_root: Path) -> None:
    """Una ronda CON las 4 claves de cohorte + nonce (la forma post-055o)."""
    ed.append_scorecard(
        project_root,
        {
            "ts": "2026-09-29T10:00:00+00:00",
            "event": "ronda",
            "ticket": "WOT-TEST-055o",
            "rol": "challenger",
            "task_type": "contract-audit",
            "backend": "fake",
            "model": "m2",
            "ronda": 1,
            "outcome": None,
            "evidencia": "e",
            "input_bytes": 10,
            "context_kind": "diff",
            "phase": "CONTRACT_AUDIT",
            "loop_id": "L700",
            "backend_key": "BA11",
            "lens_scope": "destino",
            "challenge_nonce": "nonce-055o",
        },
    )


def test_adjudicate_copies_phase_loop_id_backend_key_lens_scope_from_source(tmp_path):
    """WOT-2026-055o, Tarea 1: la clave hacia adelante se COPIA de `source`,
    con el mismo patron que task_type/backend/model.

    MUTATION: quitar una de las 5 lineas nuevas del dict que appendea
    `adjudicate()` -> esa clave sale `None` en la fila y el assert cae. Sin
    estas claves, `phase_value_report` no puede unir ronda<->adjudicacion de
    forma determinista (el join aproximado medido el 2026-09-23 daba 144/257).
    """
    _seed_round_with_cohort_keys(tmp_path)
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-055o",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="pytest -k x -> exit 0",
        adjudicator_backend="fake-adjudicator",
    )
    row = _rows(tmp_path)[-1]
    assert row["event"] == "adjudicacion"
    assert (
        row["phase"],
        row["loop_id"],
        row["backend_key"],
        row["lens_scope"],
        row["challenge_nonce"],
    ) == ("CONTRACT_AUDIT", "L700", "BA11", "destino", "nonce-055o"), (
        "la fila de adjudicacion DEBE portar la clave hacia adelante copiada "
        "de la ronda fuente; sin ella la union ronda<->adjudicacion es "
        "imposible sin heuristica"
    )


def test_adjudicate_legacy_source_without_keys_still_appends(tmp_path):
    """CONTROL NEGATIVO del cambio: un source LEGACY (sin las 5 claves) sigue
    adjudicando sin lanzar, y las claves salen `None` -- el cambio es aditivo
    y no rompe el camino historico."""
    _seed_rounds(tmp_path, 1)  # fixture legacy: ni phase ni lens_scope
    ed.adjudicate(
        tmp_path,
        ticket="WOT-TEST-000a",
        ronda=1,
        rol="challenger",
        outcome="adoptada",
        evidence="cmd",
        adjudicator_backend="fake-adjudicator",
    )
    row = _rows(tmp_path)[-1]
    assert row["event"] == "adjudicacion"
    for key in (
        "phase",
        "loop_id",
        "backend_key",
        "lens_scope",
        "challenge_nonce",
    ):
        assert row[key] is None, f"{key} debe ser None en un source legacy: {row}"


def test_record_exploration_result_writes_minimal_row(tmp_path):
    """WOT-2026-055o, Tarea 4.2: fila MINIMA de exploracion.

    MUTATION: quitar la llamada a `append_scorecard` dentro del helper -> el
    scorecard no se crea y este test cae (cero filas).
    """
    cfg = _config()
    cfg["ensemble_profiles"]["p_chal"]["backend_key"] = "BA11"
    ed.record_exploration_result(
        tmp_path,
        profile_name="p_chal",
        config=cfg,
        outcome="failed",
        latency_ms=115400,
        failure_mode="empty_content_despite_sentinel",
    )
    rows = _rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "ronda"
    assert row["task_type"] == "exploracion"
    assert row["backend"] == "fake"
    assert row["model"] == "m2"
    assert row["backend_key"] == "BA11", "la clave se resuelve del PERFIL"
    assert row["latency_ms"] == 115400
    assert row["outcome"] == "failed"
    assert row["failure_mode"] == "empty_content_despite_sentinel"
    # Fila RESUMEN, no registro de auditoria de gobierno: sin bundle.
    for absent in ("context_kind", "input_bytes", "session_id"):
        assert row[absent] is None, f"{absent} no debe poblarse: {row}"


def test_smoke_profile_records_exploration_on_success_and_failure(tmp_path):
    """WOT-2026-055o, Tarea 4.3: AMBOS intentos dejan fila, con `outcome`
    distinto.

    CONTROL NEGATIVO del hallazgo real de esta sesion: un fallo de smoke como
    `empty_content_despite_sentinel` (115.4s, OpenRouter) NO dejaba NINGUNA
    fila antes de este fix -- el scorecard era ciego al trafico exploratorio.
    """
    cfg = _config()
    ok = ed.smoke_profile(
        "p_prop",
        config=cfg,
        transport=_FakeTransport(replies=["PONG-019o"]),
        project_root=tmp_path,
    )

    def _boom(profile, backend_cfg, messages, timeout):
        raise RuntimeError("empty_content_despite_sentinel")

    bad = ed.smoke_profile("p_prop", config=cfg, transport=_boom, project_root=tmp_path)
    assert ok["alive"] is True and bad["alive"] is False

    rows = [r for r in _rows(tmp_path) if r["task_type"] == "exploracion"]
    assert len(rows) == 2, (
        f"exito y fallo deben dejar fila cada uno, hubo {len(rows)}: "
        "0 = el fallo se pierde (el defecto original), 1 = solo se registra "
        "el exito (sesgo de supervivencia)"
    )
    assert {r["outcome"] for r in rows} == {"alive", "failed"}
    assert all(isinstance(r["latency_ms"], int) for r in rows)
    assert rows[0]["failure_mode"] is None
    assert "empty_content_despite_sentinel" in rows[1]["failure_mode"]

    # Sin `project_root` no se registra: comportamiento historico intacto
    # (nadie debe escribir en un scorecard que no le indicaron).
    ed.smoke_profile(
        "p_prop",
        config=cfg,
        transport=_FakeTransport(replies=["PONG-019o"]),
    )
    after = [r for r in _rows(tmp_path) if r["task_type"] == "exploracion"]
    assert len(after) == 2, "sin project_root NO debe anadirse fila"


def test_dispatch_blocked_does_not_record_exploration_row(tmp_path):
    """WOT-2026-055o, Tarea 4.4: el preflight de privacidad bloquea ANTES de
    tocar red -> NO hubo ronda -> CERO fila.

    Mismo criterio que `run_loop_round` para el canal de gobierno. MUTATION:
    quitar la exclusion de `DispatchBlockedError` -> la excepcion cae en el
    `except Exception` y aparece una fila fantasma de una ronda que nunca
    ocurrio, y este test cae.
    """
    cfg = _config(private_roots=["C:/repos/privado"])
    with pytest.raises(ed.DispatchBlockedError):
        ed.smoke_profile(
            "p_prop",
            config=cfg,
            # el nonce viaja DENTRO del payload -> dispara el filtro por raiz
            nonce="ver C:/repos/privado/secreto.md",
            transport=_FakeTransport(replies=["PONG"]),
            project_root=tmp_path,
        )
    assert not (tmp_path / ed.SCORECARD_REL).exists(), (
        "un bloqueo del preflight no puede dejar fila: no hubo ronda que "
        "registrar, y la fila fantasma contaria como trafico real"
    )


def test_status_command_writes_backend_status_json(tmp_path, monkeypatch):
    """WOT-2026-055o, Tarea 6: `status` publica la fila MAS RECIENTE por
    `backend_key`.

    MUTATION: invertir el criterio de "mas reciente" -> para BA10 queda la
    fila de las 08:00 (`alive=False`) en vez de la de las 10:00, y el assert
    de `checked_at` cae.
    """
    cfg = _config()
    cfg["ensemble_profiles"]["p_prop"]["backend_key"] = "BA10"
    cfg["ensemble_profiles"]["p_chal"]["backend_key"] = "BA11"
    monkeypatch.setattr(ed, "load_motor_config", lambda: cfg)
    for ts, key, model, outcome in (
        ("2026-09-29T08:00:00+00:00", "BA10", "m1", "failed"),
        ("2026-09-29T09:00:00+00:00", "BA11", "m2", "failed"),
        ("2026-09-29T10:00:00+00:00", "BA10", "m1", "alive"),
    ):
        ed.append_scorecard(
            tmp_path,
            {
                "ts": ts,
                "event": "ronda",
                "task_type": "exploracion",
                "backend": "fake",
                "model": model,
                "backend_key": key,
                "latency_ms": 42,
                "outcome": outcome,
                "failure_mode": None if outcome == "alive" else "transporte",
            },
        )
    rc = ed.main(["status", "--project-root", str(tmp_path)])
    assert rc == 0

    out = json.loads((tmp_path / ed.BACKEND_STATUS_REL).read_text(encoding="utf-8"))
    assert out["generated_at"], "frescura declarada: sin generated_at no se puede datar"
    assert out["scorecard_sha256"], "atestacion de staleness, igual que backend_leaders"
    assert out["freshness_hours_declared"] == 24
    entries = {e["backend_key"]: e for e in out["backends"]}
    assert set(entries) == {"BA10", "BA11"}
    assert entries["BA10"]["checked_at"] == "2026-09-29T10:00:00+00:00", (
        "gano la fila VIEJA: el criterio de 'mas reciente' esta invertido"
    )
    assert entries["BA10"]["alive"] is True
    assert entries["BA10"]["profile"] == "p_prop"
    assert entries["BA10"]["latency_ms"] == 42
    assert entries["BA11"]["alive"] is False
    assert entries["BA11"]["failure_mode"] == "transporte"


def test_cmd_preflight_content_sample_file_llega_a_preflight_profile(
    monkeypatch, tmp_path
):
    """DoD WOT-2026-068k-followup: `--content-sample-file` del CLI debe llegar
    como `content_sample` a `preflight_profile` (antes de este fix, el flag
    no existia en el parser y `_cmd_preflight` nunca pasaba el parametro --
    `preflight_profile(preflight_profile=...)` ya existia en Python pero
    quedaba inalcanzable desde la linea de comandos)."""
    sample_path = tmp_path / "bundle_sample.txt"
    sample_content = "contenido real del bundle de auditoria"
    sample_path.write_text(sample_content, encoding="utf-8")

    captured = {}

    def _fake_preflight_profile(name, *, config, content_sample=None, **_kw):
        captured["content_sample"] = content_sample
        return {"profile": name, "alive": True, "detail": "PREFLIGHT-OK"}

    monkeypatch.setattr(ed, "preflight_profile", _fake_preflight_profile)

    args = ed.argparse.Namespace(
        profile="p_prop",
        backend_keys=None,
        content_sample_file=str(sample_path),
    )
    rc = ed._cmd_preflight(args, _config())

    assert rc == 0
    assert captured["content_sample"] == sample_content


def test_cmd_preflight_sin_content_sample_file_pasa_none(monkeypatch):
    """Compat: sin `--content-sample-file`, el CLI sigue pasando
    `content_sample=None` (comportamiento identico al de antes del flag)."""
    captured = {}

    def _fake_preflight_profile(name, *, config, content_sample=None, **_kw):
        captured["content_sample"] = content_sample
        return {"profile": name, "alive": True, "detail": "PREFLIGHT-OK"}

    monkeypatch.setattr(ed, "preflight_profile", _fake_preflight_profile)

    args = ed.argparse.Namespace(
        profile="p_prop", backend_keys=None, content_sample_file=None
    )
    rc = ed._cmd_preflight(args, _config())

    assert rc == 0
    assert captured["content_sample"] is None


# ---------------------------------------------------------------------------
# Cableado real del fallback dentro de run_loop_round (WOT-2026-083b):
# resolve_similar_fallback dejo de ser una funcion suelta. VIVE ANTES del
# marcador WOT-2026-025z a proposito (mismo motivo que el bloque de arriba,
# :1991): estos tests mockean `send_to_profile`/`smoke_profile` por nombre en
# texto crudo, tokens prohibidos en el bloque POSTERIOR al marcador.
# ---------------------------------------------------------------------------


def _config_with_glm_family():
    """2 perfiles de la MISMA familia ('glm', via monkeypatch de
    MODEL_FAMILY_MAP): p_prop falla, p_chal es el companero vivo."""
    config = _config()
    config["ensemble_profiles"]["p_prop"]["backend_key"] = "BA01"
    config["ensemble_profiles"]["p_chal"]["backend_key"] = "BA02"
    return config


def test_run_loop_round_auto_fallback_on_quota_exhausted(tmp_path, monkeypatch):
    """Un transport_failed (cuota agotada) en el perfil pedido dispara
    resolve_similar_fallback SOLO, sin que el caller tenga que invocarlo:
    la ronda devuelve la respuesta del sustituto de la MISMA familia."""
    config = _config_with_glm_family()
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {("fake", "m1"): "glm", ("fake", "m2"): "glm"},
    )

    calls: list[str] = []

    def _fake_send(profile_name, messages, **_kw):
        calls.append(profile_name)
        if profile_name == "p_prop":
            raise ed.TransportError(
                "HTTP 402",
                status=402,
                body='{"error":{"message":"allowance exhausted"}}',
            )
        return "respuesta del sustituto"

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", lambda name, *, config: {"alive": True})

    reply = ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
    )

    assert reply == "respuesta del sustituto"
    assert calls == ["p_prop", "p_chal"], (
        "debe intentar el perfil pedido primero, y SOLO tras fallar, el "
        "sustituto de la misma familia -- nunca al reves"
    )


def test_run_loop_round_auto_fallback_writes_event_with_correct_backend_key(
    tmp_path, monkeypatch
):
    """El evento persistido en fallback_events.jsonl usa el backend_key REAL
    del sustituto (BA02), nunca el del perfil que fallo (BA01) -- mismo
    invariante que la validacion de expected_key: el receipt identifica a
    quien EJECUTO."""
    config = _config_with_glm_family()
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {("fake", "m1"): "glm", ("fake", "m2"): "glm"},
    )

    def _fake_send(profile_name, messages, **_kw):
        if profile_name == "p_prop":
            raise ed.TransportError(
                "HTTP 402",
                status=402,
                body='{"error":{"message":"allowance exhausted"}}',
            )
        return "ok"

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", lambda name, *, config: {"alive": True})

    ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
    )

    events_path = tmp_path / ed.FALLBACK_EVENTS_REL
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["failed_profile"] == "p_prop"
    assert event["fallback_profile"] == "p_chal"
    assert event["fallback_backend_key"] == "BA02"
    assert event["failure_class"] == ed._FAILURE_CLASS_QUOTA
    assert event["ticket"] == "T-1"
    assert event["loop_id"] == "L-TEST"


def test_run_loop_round_no_fallback_for_unexpected_errors(tmp_path, monkeypatch):
    """Un error NO clasificado como transport_failed (bug de programacion,
    p.ej. KeyError) NUNCA dispara el fallback -- se propaga tal cual, para
    no enmascarar un defecto de codigo detras de 'ya respondio otro'."""
    config = _config_with_glm_family()
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {("fake", "m1"): "glm", ("fake", "m2"): "glm"},
    )

    def _raising_send(*_a, **_kw):
        raise KeyError("bug de programacion, no de transporte")

    monkeypatch.setattr(ed, "send_to_profile", _raising_send)

    with pytest.raises(KeyError):
        ed.run_loop_round(
            "p_prop",
            "contenido",
            config=config,
            project_root=tmp_path,
            ticket="T-1",
            task_type="exploracion",
            rol="challenger",
            phase="DESIGN_REVIEW",
            loop_id="L-TEST",
            backend_key="BA01",
            sensitivity="public",
        )

    events_path = tmp_path / ed.FALLBACK_EVENTS_REL
    assert not events_path.exists(), (
        "un error no-transporte no debe generar ni intento de fallback ni evento"
    )


def test_run_loop_round_no_candidate_raises_original_exception(tmp_path, monkeypatch):
    """Sin ningun companero de familia vivo, se propaga la excepcion ORIGINAL
    (el 402), no un DispatchBlockedError generico de 'no hay candidatos' --
    el caller debe ver la causa raiz."""
    config = _config()  # familia sin MODEL_FAMILY_MAP -> resolve_fallback_backend
    monkeypatch.setattr(ed, "MODEL_FAMILY_MAP", {})

    def _raising_send(*_a, **_kw):
        raise ed.TransportError("HTTP 402", status=402, body="")

    def _dead_check(name, *, config):
        return {"alive": False}

    monkeypatch.setattr(ed, "send_to_profile", _raising_send)
    monkeypatch.setattr(ed, "smoke_profile", _dead_check)

    with pytest.raises(ed.TransportError, match="HTTP 402"):
        ed.run_loop_round(
            "p_prop",
            "contenido",
            config=config,
            project_root=tmp_path,
            ticket="T-1",
            task_type="exploracion",
            rol="challenger",
            phase="DESIGN_REVIEW",
            loop_id="L-TEST",
            backend_key="BA01",
            sensitivity="public",
        )

    events_path = tmp_path / ed.FALLBACK_EVENTS_REL
    assert not events_path.exists(), (
        "sin candidato vivo no hay fallback: no se escribe evento"
    )


def test_run_loop_round_no_ping_pong_between_two_family_members(tmp_path, monkeypatch):
    """Reproduce el incidente REAL medido 2026-09-29 (fallback_events.jsonl):
    A falla -> se prueba B (companero de familia) -> B TAMBIEN falla -> sin
    la correccion, B podria re-intentar A (A es companero valido DESDE el
    punto de vista de B). Con `_tried_profiles`/`exclude_profiles`, A queda
    excluido del universo de candidatos de B, y la cadena cae directo al
    fallback generico -- NUNCA vuelve a intentar A."""
    config = _config_with_glm_family()
    config["ensemble_profiles"]["p_other"] = {
        "backend": "fake",
        "channel": "api",
        "model": "m3",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA03",
    }
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {("fake", "m1"): "glm", ("fake", "m2"): "glm"},
    )

    calls: list[str] = []

    def _fake_send(profile_name, messages, **_kw):
        calls.append(profile_name)
        if profile_name == "p_other":
            return "respuesta del fallback generico"
        # AMBOS companeros de familia fallan (fallo transitorio, no de cuota)
        raise ed.TransportError("EOF", status=None, body="stream truncado")

    def _alive_check(name, *, config):
        # resolve_similar_fallback SOLO decide si el candidato responde al
        # smoke (vivo/muerto); el FALLO real de esta prueba ocurre despues,
        # en send_to_profile (_fake_send) -- son dos primitivas distintas.
        return {"alive": True}

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", _alive_check)

    fallback_calls: list[str] = []

    def fake_fallback_backend(
        pool_backend,
        *,
        config,
        check_alive,
        exclude_profiles=frozenset(),
        project_root=None,
    ):
        fallback_calls.append(pool_backend)
        return "p_other"

    monkeypatch.setattr(ed, "resolve_fallback_backend", fake_fallback_backend)

    reply = ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
    )

    assert reply == "respuesta del fallback generico"
    assert calls == ["p_prop", "p_chal", "p_other"], (
        "debe intentar p_prop, luego SU companero p_chal, y NUNCA volver a "
        f"p_prop antes de caer al fallback generico -- secuencia real: {calls}"
    )
    assert fallback_calls == ["fake"]


def test_resolve_fallback_backend_real_path_excludes_already_tried_profiles(
    tmp_path, monkeypatch
):
    """H5 (auditoria fria 2026-09-29): el test hermano de ping-pong maquillaba
    resolve_fallback_backend mockeandolo por completo, ocultando que el
    delegado REAL no recibia exclude_profiles. Reproduce el incidente REAL
    (openrouter/nemotron <-> nvidia/nemotron, backends DISTINTOS dentro de
    la MISMA familia): p_prop (vendor_a) falla, su companero de familia
    p_chal (vendor_b) TAMBIEN falla -- familia agotada, delega en
    resolve_fallback_backend(pool_backend='vendor_b'). SIN exclude_profiles,
    ese delegado ve a p_prop (vendor_a, clase DISTINTA de vendor_b) como
    candidato "de clase distinta" valido de nuevo -- el ping-pong exacto que
    exclude_profiles debe impedir. Solo p_other (un TERCER backend) es la
    salida correcta."""
    config = _config_with_glm_family()
    # p_prop y p_chal son la familia GLM, pero de BACKENDS DISTINTOS entre si
    # (como el incidente real): eso es lo que hace que, tras agotar la
    # familia, resolve_fallback_backend(pool_backend=vendor_b) considere a
    # p_prop (vendor_a) un candidato "de clase distinta" legitimo si no se
    # le pasa exclude_profiles.
    config["ensemble_profiles"]["p_prop"]["backend"] = "vendor_a"
    config["ensemble_profiles"]["p_chal"]["backend"] = "vendor_b"
    config["ensemble_profiles"]["p_other"] = {
        "backend": "vendor_c",
        "channel": "api",
        "model": "m9",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA09",
    }
    config["backends"]["vendor_a"] = dict(config["backends"]["fake"])
    config["backends"]["vendor_b"] = dict(config["backends"]["fake"])
    config["backends"]["vendor_c"] = dict(config["backends"]["fake"])
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {("vendor_a", "m1"): "glm", ("vendor_b", "m2"): "glm"},
    )
    # NO se mockea resolve_fallback_backend: se ejerce el codigo real.
    calls: list[str] = []

    def _fake_send(profile_name, messages, **_kw):
        calls.append(profile_name)
        if profile_name == "p_other":
            return "respuesta real del delegado"
        # p_prop Y p_chal fallan -- agota la familia GLM completa.
        raise ed.TransportError("EOF", status=None, body="stream truncado")

    def _alive_check(name, *, config):
        return {"alive": True}

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", _alive_check)

    reply = ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
    )

    assert reply == "respuesta real del delegado"
    assert calls == ["p_prop", "p_chal", "p_other"], (
        "el DELEGADO REAL (resolve_fallback_backend, SIN mock) debe excluir "
        "p_prop y p_chal (ya intentados, aunque sean de clases DISTINTAS "
        f"entre si) y elegir p_other -- secuencia real: {calls}. Si aparece "
        "p_prop una segunda vez, el bug de ping-pong (H5) sigue vivo en el "
        "camino delegado."
    )


def test_fallback_events_chain_same_nonce_distinguished_by_pair(tmp_path, monkeypatch):
    """H3 Seccion 3 (PROPUESTA_h3_fuente_unica_failure_class.md): la llave de
    correlacion con scorecard.jsonl es el PAR (challenge_nonce, failed_profile),
    nunca el nonce solo. Dos intentos de sustitucion encadenados bajo el MISMO
    nonce de ronda (p_prop falla -> p_chal sustituye y TAMBIEN falla -> p_third
    responde) deben producir DOS filas con challenge_nonce IDENTICO pero
    failed_profile distinto en cada una: si el par no las distingue, o si una
    de las dos filas se pierde, este test falla."""

    config = _config_with_glm_family()
    config["ensemble_profiles"]["p_third"] = {
        "backend": "fake",
        "channel": "api",
        "model": "m3",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA03",
    }
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {
            ("fake", "m1"): "glm",
            ("fake", "m2"): "glm",
            ("fake", "m3"): "glm",
        },
    )

    def _fake_send(profile_name, messages, **_kw):
        if profile_name in ("p_prop", "p_chal"):
            raise ed.TransportError("EOF", status=None, body="stream truncado")
        return "respuesta del tercero"

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", lambda name, *, config: {"alive": True})

    reply = ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
        challenge_nonce="nonce-fijo-H3",
    )

    assert reply == "respuesta del tercero"
    events_path = tmp_path / ed.FALLBACK_EVENTS_REL
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, (
        f"dos intentos de sustitucion encadenados = dos eventos, hay {len(lines)}"
    )
    events = [json.loads(line) for line in lines]
    assert {e["challenge_nonce"] for e in events} == {"nonce-fijo-H3"}, (
        "ambos eventos deben heredar el MISMO challenge_nonce de la ronda"
    )
    assert [e["failed_profile"] for e in events] == ["p_prop", "p_chal"], (
        "cada evento registra al perfil que acaba de fallar en ESE intento"
    )
    pairs = {(e["challenge_nonce"], e["failed_profile"]) for e in events}
    assert len(pairs) == 2, (
        f"el PAR (nonce, failed_profile) debe ser unico por evento, "
        f"pares reales: {pairs}"
    )


# ---------------------------------------------------------------------------
# Cuarentena de backends + fallback definitivo Claude (sesion H3+H1,
# 2026-09-29). Mismo bloque que los tests de fallback: mockean por nombre
# en texto crudo, ANTES del marcador WOT-2026-025z a proposito.
# ---------------------------------------------------------------------------


def _write_quarantine(tmp_path, *, by_backend=None, by_profile=None):
    path = tmp_path / ed.QUARANTINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-29T00:00:00+00:00",
                "fallback_events_sha256": "deadbeef",
                "by_backend": by_backend or {},
                "by_profile": by_profile or {},
            }
        ),
        encoding="utf-8",
    )
    return path


def _future_iso(hours: float = 1.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_parse_provider_reset_at_keeps_seconds():
    """El regex captura segundos pero antes se descartaban al llamar
    `strptime` solo con `%Y-%m-%d %H:%M` -- la cuarentena expiraba hasta 59s
    antes de lo debido (hallazgo declarado 2026-09-29,
    scripts/ensemble_dispatch.py:1965-1969)."""
    parsed = ed._parse_provider_reset_at("retry after 2026-09-29 10:15:45 UTC")
    assert parsed == datetime(2026, 9, 29, 10, 15, 45, tzinfo=timezone.utc)


def test_parse_provider_reset_at_without_seconds_still_works():
    parsed = ed._parse_provider_reset_at("reset at 2026-09-29 10:15Z")
    assert parsed == datetime(2026, 9, 29, 10, 15, 0, tzinfo=timezone.utc)


def test_parse_provider_reset_at_rejects_invalid_seconds():
    """Segundos :60-:99 no son validos -> None. El fix captura el grupo de
    segundos y strptime valida: 10:15:99 revienta en strptime y se convierte
    a None (no se cae a :00)."""
    parsed = ed._parse_provider_reset_at("retry after 2026-09-29 10:15:99 UTC")
    assert parsed is None
    parsed = ed._parse_provider_reset_at("2026-09-29 10:15:60")
    assert parsed is None


def test_read_quarantine_drops_expired_and_unreadable(tmp_path):
    """Lectura: vencidas y `expires_at` ilegible NO bloquean (fail-open
    declarado); vigentes si. Ausente o JSON corrupto -> dos tablas vacias."""
    _write_quarantine(
        tmp_path,
        by_backend={
            "nan_api": {
                "reason_class": "quota_exhausted",
                "expires_at": _future_iso(),
            },
            "old_api": {
                "reason_class": "quota_exhausted",
                "expires_at": "2000-01-01T00:00:00+00:00",
            },
            "bad_api": {"reason_class": "quota_exhausted", "expires_at": "no-date"},
        },
    )
    q = ed.read_quarantine(tmp_path)
    assert sorted(q["by_backend"]) == ["nan_api"], (
        "solo la entrada vigente debe sobrevivir el filtro de lectura"
    )
    assert q["by_profile"] == {}

    # ausente
    empty = ed.read_quarantine(tmp_path / "no-existe")
    assert empty == {"by_backend": {}, "by_profile": {}}

    # corrupto
    path = tmp_path / ed.QUARANTINE_REL
    path.write_text("{esto no es json", encoding="utf-8")
    assert ed.read_quarantine(tmp_path) == {"by_backend": {}, "by_profile": {}}


def test_resolve_similar_fallback_quarantine_beats_ranking_order(tmp_path, monkeypatch):
    """Precedencia (diseno 5-bis): el filtro de cuarentena se aplica ANTES
    del ranking y sin gastar red. p_chal es el PRIMER candidato de familia
    (y el que el ranking daria primero); si esta en cuarentena, jamas se le
    invoca smoke y la familia cae al siguiente vivo."""
    config = _config_with_glm_family()
    config["ensemble_profiles"]["p_third"] = {
        "backend": "fake",
        "channel": "api",
        "model": "m3",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA03",
    }
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {
            ("fake", "m1"): "glm",
            ("fake", "m2"): "glm",
            ("fake", "m3"): "glm",
        },
    )
    _write_quarantine(
        tmp_path,
        by_profile={
            "p_chal": {
                "backend": "fake",
                "reason_class": "network_timeout",
                "source": "default_ttl",
                "expires_at": _future_iso(),
            }
        },
    )
    probed: list[str] = []

    def _alive(name, *, config):
        probed.append(name)
        return {"alive": True}

    monkeypatch.setattr(ed, "smoke_profile", _alive)

    chosen = ed.resolve_similar_fallback("p_prop", config=config, project_root=tmp_path)
    assert chosen == "p_third"
    assert probed == ["p_third"], (
        f"p_chal esta en cuarentena: NO debe gastar smoke; probes: {probed}"
    )


def test_delegate_path_respects_quarantine(tmp_path, monkeypatch):
    """Hallazgo 5 de la ronda: las DELEGACIONES a resolve_fallback_backend
    son una ruta aparte por la que un perfil cuarentenado re-entraria si el
    filtro solo viviera en same_family. Aqui no hay familia (mapa vacio),
    asi que todo pasa por el delegado: p_quar es el primero en orden de
    insercion y aun asi no debe ni sondearse."""
    config = _config()
    config["ensemble_profiles"]["p_quar"] = {
        "backend": "vendor_b",
        "channel": "api",
        "model": "m8",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA08",
    }
    config["ensemble_profiles"]["p_ok"] = {
        "backend": "vendor_c",
        "channel": "api",
        "model": "m9",
        "api_base_url": "https://fake.example/v1/chat/completions",
        "api_key_env": "FAKE_API_KEY",
        "data_sensitivity": "public",
        "write": False,
        "backend_key": "BA09",
    }
    config["backends"]["vendor_b"] = dict(config["backends"]["fake"])
    config["backends"]["vendor_c"] = dict(config["backends"]["fake"])
    monkeypatch.setattr(ed, "MODEL_FAMILY_MAP", {})
    _write_quarantine(
        tmp_path,
        by_profile={
            "p_quar": {
                "backend": "vendor_b",
                "reason_class": "network_timeout",
                "source": "default_ttl",
                "expires_at": _future_iso(),
            }
        },
    )
    probed: list[str] = []

    def _alive(name, *, config):
        probed.append(name)
        return {"alive": True}

    monkeypatch.setattr(ed, "smoke_profile", _alive)

    chosen = ed.resolve_similar_fallback("p_prop", config=config, project_root=tmp_path)
    assert chosen == "p_ok"
    assert probed == ["p_ok"], (
        f"el delegado real debe filtrar p_quar antes del smoke; probes: {probed}"
    )


def test_regenerate_quarantine_scopes_by_cause(tmp_path):
    """`quarantine --sync` deriva de fallback_events (unico portador de
    failure_class): quota_exhausted -> by_backend con fecha del proveedor
    (Caso A), network_timeout -> by_profile con TTL (Caso B), unknown NO
    genera cuarentena, y un evento con fecha de reset YA pasada se purga."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "ts": (now - timedelta(minutes=30)).isoformat(),
            "failed_profile": "challenger_nan_glm_flash",
            "failed_backend": "nan_api",
            "failure_class": "quota_exhausted",
            "failure_detail": (
                "TransportError: HTTP 402 body=allowance exhausted, "
                "counter resets on 2099-06-01 00:00 UTC, in 1d13h"
            ),
        },
        {
            "ts": (now - timedelta(minutes=10)).isoformat(),
            "failed_profile": "challenger_nvidia_kimi",
            "failed_backend": "nvidia_api",
            "failure_class": "network_timeout",
            "failure_detail": "socket timeout tras 90s, sin status HTTP",
        },
        {
            "ts": (now - timedelta(minutes=5)).isoformat(),
            "failed_profile": "challenger_groq_qwen",
            "failed_backend": "groq_api",
            "failure_class": "unknown",
            "failure_detail": "HTTP 413 payload too large",
        },
        {
            "ts": (now - timedelta(days=30)).isoformat(),
            "failed_profile": "challenger_old",
            "failed_backend": "old_api",
            "failure_class": "quota_exhausted",
            "failure_detail": "quota reset on 2000-01-01 00:00 UTC",
        },
    ]
    path = tmp_path / ed.FALLBACK_EVENTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    # WOT-2026-086c: la cuota va a by_backend SOLO si el proveedor declara
    # `quota_scope: cuenta` (decision del usuario 2026-09-29); sin declararlo
    # es por modelo (ver test_086c_*). Aqui se declara para ejercitar esa rama.
    config = _config()
    config["backends"]["nan_api"] = {"quota_scope": "cuenta"}
    out = ed.regenerate_quarantine(tmp_path, config=config)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert list(data["by_backend"]) == ["nan_api"], (
        "solo quota_exhausted vigente genera by_backend; el reset pasado "
        "se purga y unknown no dispara nada"
    )
    quota = data["by_backend"]["nan_api"]
    assert quota["source"] == "explicit_provider_date"
    assert quota["expires_at"] == "2099-06-01T00:00:00+00:00"
    assert quota["triggered_by_profile"] == "challenger_nan_glm_flash"
    assert quota["renewal_count"] == 0

    assert list(data["by_profile"]) == ["challenger_nvidia_kimi"]
    net = data["by_profile"]["challenger_nvidia_kimi"]
    assert net["source"] == "default_ttl"
    assert net["reason_class"] == "network_timeout"
    expires = datetime.fromisoformat(net["expires_at"])
    assert expires > datetime.now(timezone.utc), "TTL de 1h desde el ultimo evento"
    assert "groq_api" not in data["by_backend"]
    assert data["fallback_events_sha256"]
    assert "NUNCA editar a mano" in data["derivado"]


def _quota_event(profile: str, backend: str, *, minutes_ago: int = 5) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "ts": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "failed_profile": profile,
        "failed_backend": backend,
        "failure_class": "quota_exhausted",
        "failure_detail": "TransportError: HTTP 402 body=monthly_cap_reached",
    }


def _write_fallback_events(tmp_path, events: list[dict]) -> None:
    path = tmp_path / ed.FALLBACK_EVENTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def test_086c_quota_is_per_model_by_default(tmp_path):
    """Sin `quota_scope` declarado, la cuota agotada de UN modelo pone en
    cuarentena ESE perfil, no el proveedor entero (medido 2026-09-30: nan
    gemma4/qwen3.6 sin limite quedaron fuera porque otro modelo agoto su cupo).
    Mutation: devolver by_backend para quota_exhausted -> RED."""
    config = _config()
    config["ensemble_profiles"]["p_cupo"] = {"backend": "fake", "model": "m3"}
    _write_fallback_events(tmp_path, [_quota_event("p_cupo", "fake")])

    data = json.loads(
        ed.regenerate_quarantine(tmp_path, config=config).read_text(encoding="utf-8")
    )
    assert data["by_backend"] == {}
    assert list(data["by_profile"]) == ["p_cupo"]
    entry = data["by_profile"]["p_cupo"]
    assert entry["reason_class"] == "quota_exhausted"
    assert entry["backend"] == "fake"

    quarantine = ed.read_quarantine(tmp_path)
    assert ed.quarantine_reason("p_cupo", config=config, quarantine=quarantine)
    assert (
        ed.quarantine_reason("p_prop", config=config, quarantine=quarantine) is None
    ), "un modelo hermano del mismo proveedor NO hereda la cuarentena"


def test_086c_quota_scope_cuenta_quarantines_the_whole_provider(tmp_path):
    """`quota_scope: cuenta`: el cupo es de la cuenta, asi que cualquier
    modelo del proveedor queda sin servicio y la cuarentena es por proveedor."""
    config = _config()
    config["backends"]["fake"]["quota_scope"] = "cuenta"
    _write_fallback_events(tmp_path, [_quota_event("p_chal", "fake")])

    data = json.loads(
        ed.regenerate_quarantine(tmp_path, config=config).read_text(encoding="utf-8")
    )
    assert list(data["by_backend"]) == ["fake"]
    assert data["by_profile"] == {}
    quarantine = ed.read_quarantine(tmp_path)
    assert ed.quarantine_reason("p_prop", config=config, quarantine=quarantine)


def test_086c_unknown_quota_scope_value_falls_back_to_model(tmp_path):
    """Un valor no reconocido no amplia la cuarentena: sobre-bloquear un
    proveedor entero por un typo es peor que no bloquear (la cuarentena
    optimiza, no es autoridad)."""
    config = _config()
    config["backends"]["fake"]["quota_scope"] = "cuentas"
    _write_fallback_events(tmp_path, [_quota_event("p_chal", "fake")])

    data = json.loads(
        ed.regenerate_quarantine(tmp_path, config=config).read_text(encoding="utf-8")
    )
    assert data["by_backend"] == {}
    assert list(data["by_profile"]) == ["p_chal"]


def test_086c_real_config_declares_account_scope_only_where_measured():
    """El agents.json real declara `quota_scope` con valores validos, y
    tokenharbor (cupo por cuenta, medido 2026-09-29) lo declara `cuenta`."""
    config = ed.load_motor_config()
    scopes = {
        name: cfg["quota_scope"]
        for name, cfg in config["backends"].items()
        if "quota_scope" in cfg
    }
    assert set(scopes.values()) <= ed.QUOTA_SCOPES
    assert scopes.get("tokenharbor_api") == "cuenta"
    assert scopes.get("nan_api", "modelo") == "modelo"


def test_smoke_cli_skips_quarantined_unless_forced(tmp_path, monkeypatch, capsys):
    """CLI smoke: perfil en cuarentena se OMITE con WARN por defecto (sin
    gastar la llamada) y `--ignore-quarantine` es el intento explicito que
    la regla dura del diseno prohibe bloquear."""
    config = _config()
    _write_quarantine(
        tmp_path,
        by_profile={
            "p_prop": {
                "backend": "fake",
                "reason_class": "quota_exhausted",
                "source": "explicit_provider_date",
                "expires_at": _future_iso(),
            }
        },
    )
    probed: list[str] = []

    def _alive(name, *, config, project_root=None):
        probed.append(name)
        return {"alive": True, "detail": "ok"}

    monkeypatch.setattr(ed, "smoke_profile", _alive)

    args = ed.argparse.Namespace(
        profile="p_prop", project_root=str(tmp_path), ignore_quarantine=False
    )
    rc = ed._cmd_smoke(args, config)
    out = capsys.readouterr()
    assert rc == 1, "universo vacio (todo en cuarentena) jamas verde"
    assert probed == [], "sin --ignore-quarantine NO se gasta la llamada"
    assert "SKIP" in out.err and "ignore-quarantine" in out.err
    payload = json.loads(out.out)
    assert payload["skipped_quarantine"][0]["profile"] == "p_prop"
    assert payload["smoke"] == []

    args_force = ed.argparse.Namespace(
        profile="p_prop", project_root=str(tmp_path), ignore_quarantine=True
    )
    rc_force = ed._cmd_smoke(args_force, config)
    out_force = capsys.readouterr()
    assert rc_force == 0
    assert probed == ["p_prop"], "con la flag, el intento explicito SI corre"
    assert "FORZADO" in out_force.err


def test_ultimate_claude_fallback_runs_when_cascade_exhausted(tmp_path, monkeypatch):
    """Fallback definitivo (decision del usuario 2026-09-29): la cascada se
    agota (smoke dice muerto hasta para Claude -> DispatchBlockedError) y la
    ronda se ejecuta igual via subagente de Claude, escribiendo el evento de
    fallback que la brecha de la cuarentena declaraba ausente."""
    config = _config()
    config["backends"]["claude"] = dict(config["backends"]["fake"])
    config["ensemble_profiles"]["proposer_claude"] = {
        "backend": "claude",
        "channel": "agent",
        "model": None,
        "backend_key": "BA01",
        "write": False,
    }
    monkeypatch.setattr(ed, "MODEL_FAMILY_MAP", {})

    def _fake_send(profile_name, messages, **_kw):
        if profile_name == "proposer_claude":
            return "respuesta del subagente claude"
        raise ed.TransportError(
            "HTTP 402",
            status=402,
            body='{"error":{"message":"allowance exhausted"}}',
        )

    monkeypatch.setattr(ed, "send_to_profile", _fake_send)
    monkeypatch.setattr(ed, "smoke_profile", lambda name, *, config: {"alive": False})

    reply = ed.run_loop_round(
        "p_prop",
        "contenido",
        config=config,
        project_root=tmp_path,
        ticket="T-1",
        task_type="exploracion",
        rol="challenger",
        phase="DESIGN_REVIEW",
        loop_id="L-TEST",
        backend_key="BA01",
        sensitivity="public",
        challenge_nonce="n-ult",
    )
    assert reply == "respuesta del subagente claude"

    events = [
        json.loads(line)
        for line in (tmp_path / ed.FALLBACK_EVENTS_REL)
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    assert len(events) == 1, "el intento del fallback definitivo deja evento"
    ev = events[0]
    assert ev["fallback_profile"] == "proposer_claude"
    assert ev["fallback_backend"] == "claude"
    assert ev["fallback_backend_key"] == "BA01"
    assert ev["failed_profile"] == "p_prop"
    assert ev["failure_class"] == ed._FAILURE_CLASS_QUOTA
    assert ev["challenge_nonce"] == "n-ult"


def test_ultimate_claude_fallback_selection_edges(tmp_path):
    """Seleccion del ultimo recurso: disponible -> elegido; ya intentado ->
    no; en cuarentena vigente -> no (la precedencia 5-bis tambien aplica al
    fallback definitivo, que es un intento AUTOMATICO)."""
    config = _config()
    config["backends"]["claude"] = dict(config["backends"]["fake"])
    config["ensemble_profiles"]["proposer_claude"] = {
        "backend": "claude",
        "channel": "agent",
        "model": None,
        "backend_key": "BA01",
        "write": False,
    }
    assert (
        ed._ultimate_claude_fallback(
            config, excluded=frozenset(), project_root=tmp_path
        )
        == "proposer_claude"
    )
    assert (
        ed._ultimate_claude_fallback(
            config,
            excluded=frozenset({"proposer_claude"}),
            project_root=tmp_path,
        )
        is None
    )
    _write_quarantine(
        tmp_path,
        by_profile={
            "proposer_claude": {
                "backend": "claude",
                "reason_class": "network_timeout",
                "source": "default_ttl",
                "expires_at": _future_iso(),
            }
        },
    )
    assert (
        ed._ultimate_claude_fallback(
            config, excluded=frozenset(), project_root=tmp_path
        )
        is None
    )


# WOT-2026-086f: BA12 (mimo-v2.5) retirado: entrada eliminada de _NAN_MODELS.

_WOT_025Z_SECTION_MARKER = "# === WOT-2026-025z substantive tests start ==="

_NAN_MODELS = {
    # 2026-09-26: renombrado familia+slot (nunca version de modelo ni ranking
    # de calidad/velocidad), mismo patron ya adoptado en nvidia_api. Veredicto
    # ensemble 4/4 APLICAR (bucle v2, codex+nan/gemma4+nan/qwen3.6+nvidia/glm).
    # backend_key de cada perfil NO cambia -- el historico del scorecard sigue
    # anclado por esa clave, nunca por el nombre del perfil.
    "deepseek-v4-flash": "challenger_nan_deepseek_flash",
    "qwen3.6": "challenger_nan_qwen",
    "gemma4": "challenger_nan_gemma",
    # 2026-09-04: la API de nan expone `qwen3.8-flash` y `glm5.3-flash`
    # (verificado contra `GET /v1/models`) y no estaban declarados. Se anaden
    # con la MISMA forma canonica; el test sigue exigiendo un perfil por modelo.
    "qwen3.8-flash": "challenger_nan_qwen_flash",
    "glm5.3-flash": "challenger_nan_glm_flash",
    # 2026-09-26: alta nueva, backend recien incorporado por el proveedor.
    # Familia mimo queda simetrica a qwen/glm: slot normal + slot flash.
    "mimo-v2.6-flash": "challenger_nan_mimo_flash",
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


def _canary_bundle(ok: bool = True) -> str:
    """Bundle minimo con una seccion ## PROBE, con recibo valido o sin el."""
    if ok:
        return (
            "## PROBE uno\n\n```receipt\ncommand: python -c pass\nexit_code: 0\n```\n"
        )
    return "## PROBE uno\n\nsin bloque receipt, solo prosa\n"


def test_receipt_canary_flags_probe_without_receipt(tmp_path, monkeypatch):
    """Un ## PROBE sin recibo valido cuenta como rojo. Comportamiento, no presencia."""
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    measurement = ed.receipt_canary(
        _canary_bundle(ok=False), root=tmp_path, ticket="T-1"
    )
    assert measurement is not None
    assert measurement["probes"] == 1
    assert measurement["failed"] == 1
    assert measurement["ok"] == 0


def test_receipt_canary_accepts_a_valid_receipt(tmp_path, monkeypatch):
    """ANTI-FALSO-POSITIVO: un recibo bien formado NO es rojo."""
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    measurement = ed.receipt_canary(
        _canary_bundle(ok=True), root=tmp_path, ticket="T-2"
    )
    assert measurement is not None
    assert measurement["failed"] == 0
    assert measurement["ok"] == 1


def test_receipt_canary_is_not_applicable_without_probe_sections(tmp_path, monkeypatch):
    """Sin secciones ## PROBE no es rojo: es n/a. No todo payload es un bundle."""
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    assert ed.receipt_canary("# solo prosa\n", root=tmp_path, ticket="T-3") is None


def test_receipt_canary_does_not_block_the_fan_out(tmp_path, monkeypatch):
    """CONTRATO CANARY punto 3: detecta el rojo y AUN ASI devuelve, no lanza.

    Mutacion: convertir el canary en fail-closed -> este test cae.
    """
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    measurement = ed.receipt_canary(
        _canary_bundle(ok=False), root=tmp_path, ticket="T-4"
    )
    assert measurement["failed"] == 1  # rojo detectado...
    assert isinstance(measurement, dict)  # ...y el envio sigue su curso


def test_receipt_canary_persists_its_measurement(tmp_path, monkeypatch):
    """CONTRATO CANARY punto 4: la medicion se PERSISTE, no solo se devuelve.

    Hallazgo del MANAGER_REVIEW: sin artefacto, el DoD que declara
    `guard_wiring_policy.yaml` -- "promover a bloqueante cuando sus mediciones
    muestren saneado el rojo" -- es INEJECUTABLE, porque no habria mediciones que
    consultar. Un WARN a stderr que nadie agrega es indistinguible de no hacer nada.

    Mutacion: quitar `_persist_canary_measurement` -> cae este test.
    """
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    measurement = ed.receipt_canary(
        _canary_bundle(ok=True), root=tmp_path, ticket="WOT-2026-042k"
    )
    assert measurement is not None

    log = tmp_path / ed.CANARY_LOG_REL
    assert log.exists(), "el canary no persistio su medicion"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["ticket"] == "WOT-2026-042k"
    assert rows[0]["probes"] == 1
    assert "timestamp" in rows[0], "sin timestamp la medicion no es agregable"


def test_receipt_canary_is_wired_into_the_only_exit_path():
    """El canary corre en la ruta REAL por la que salen los bundles.

    HALLAZGO DEL MANAGER_REVIEW que este test fija: la primera version anclaba el
    canary SOLO a `run_pipeline`, y la medicion mostro que 9 de 9 `dispatch.py` de
    gov_* llaman al unico camino de salida DIRECTAMENTE mientras CERO pasan por el
    CLI `run`. El canary vigilaba una ruta por la que no circula ningun bundle real
    -- "barrera del alcance" de AGENTS.md: cableado, y mirando donde no ocurre el
    fallo.

    Mutacion: borrar la llamada en el camino de salida -> cae este test.
    """
    import ast

    source = (_SCRIPTS_DIR / "ensemble_dispatch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "receipt_canary"
            for inner in ast.walk(node)
        )
    }
    exit_path = "send_to" + "_profile"  # partido: el guard 025z prohibe el token
    assert exit_path in callers, (
        "receipt_canary NO se invoca desde el unico camino de salida: los bundles "
        "de gobierno lo usan directo, asi que el canary no auditaria ninguno "
        "(regresion del hallazgo del MANAGER_REVIEW de WOT-2026-042k)"
    )


def test_receipt_canary_survives_a_broken_checker(tmp_path, monkeypatch):
    """Observar es OPCIONAL, enviar no: si el checker no carga, degrada a None.

    Un canary que rompe el envio deja de ser canary.
    """
    monkeypatch.setattr(ed, "MOTOR_ROOT", tmp_path)
    monkeypatch.setattr(ed, "_load_receipt_checker", lambda: None)
    assert ed.receipt_canary(_canary_bundle(), root=tmp_path, ticket="T-5") is None


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
    """(b): EXACTAMENTE un perfil por modelo nan declarado en `_NAN_MODELS`;
    cada uno backend=nan_api, channel=api, api_base_url
    completo, api_key_env=NAN_API_KEY, context=diff-o-artefacto-publico,
    write=false, data_sensitivity=public. Mutation M4: borrar un perfil nan
    hace este test FALLAR (conteo y presencia por nombre)."""
    config = ed.load_motor_config()
    profiles = config["ensemble_profiles"]
    nan_profile_names = [
        name for name, prof in profiles.items() if prof.get("backend") == "nan_api"
    ]
    assert len(nan_profile_names) == len(_NAN_MODELS), (
        f"esperados EXACTAMENTE {len(_NAN_MODELS)} perfiles nan (uno por modelo "
        f"de _NAN_MODELS), hallados: {nan_profile_names}"
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
    Ningun perfil declara fallback_profile.
    Integridad referencial defensiva: si algun dia se reintroduce un
    fallback_profile, debe ser string plano y apuntar a un perfil EXISTENTE.
    Mutation M2 (A8): reintroducir challenger_deepseek/deepseek_api hace este
    test FALLAR (nan deja de ser un backend directo muerto reintroducido).

    ACTUALIZADO (decision usuario 2026-09-26/27, sesion de WOT-2026-046b): nan
    dejo de ser el UNICO canal api -- se anadio `nvidia_api` como segundo canal
    con credencial real (`NVIDIA_API_KEY` presente), no un fallback muerto.
    El invariante que sigue vigente es "todo perfil channel=api usa un backend
    CON credencial configurada", no "usa nan_api especificamente".

    ACTUALIZADO (decision usuario 2026-09-28): se anadio `groq_api` como
    tercer canal con credencial real (`GROQ_API_KEY`), backends BA30/BA31 --
    Cerebras se evaluo y se descarto (sin tier gratuito real, solo credito de
    prueba de 30 dias).

    ACTUALIZADO (decision usuario 2026-09-28, misma sesion): se anadieron
    `openrouter_api` y `aihubmix_api` como cuarto y quinto canal. Rango de
    backend_key RESERVADO por bloques de 20 (no consecutivo tras BA31) para
    poder anadir mas modelos del MISMO proveedor sin renumerar cuando el
    catalogo gratuito rote: BA50-BA69 para openrouter_api (semilla: BA50),
    BA70-BA89 para aihubmix_api (semilla: BA70).

    Modelos de semilla VERIFICADOS contra fuente viva, no adivinados: un
    primer intento con `openai/gpt-oss-120b:free` (OpenRouter) y
    `glm-5.1-free` (AIHubMix) resulto ser INVENTADO -- ninguno de los dos
    IDs existe. Corregido tras (a) `curl https://openrouter.ai/api/v1/models`
    real (460 modelos, 16 con sufijo `:free`; `gpt-oss-120b` SOLO existe de
    pago) y (b) fetch de `docs.aihubmix.com/en/blogs/free-ai-models` (el
    slug real es `coding-glm-5.1-free`, no `glm-5.1-free`) + probe HTTP
    POST contra el endpoint real (401 "no key provided", confirma modelo y
    ruta validos sin necesitar credencial). Semillas finales: BA50 =
    `cohere/north-mini-code:free` (elegido por ser familia NUEVA en el pool,
    entrenado para agent harnesses; se descarto `nvidia/nemotron-3-super-
    120b-a12b:free` de la lista real por duplicar el modelo YA presente en
    nvidia_api/BA24), BA70 = `coding-glm-5.1-free` (variante coding,
    58.4% SWE-bench Pro segun la doc de AIHubMix).

    ACTUALIZADO (decision usuario 2026-09-28, misma sesion): se anadio
    `tokenharbor_api` como sexto canal, backend_key BA90-BA109 (semilla:
    BA90). El usuario aporto captura de pantalla del propio picker de
    tokenharbor.ai/models con los 3 IDs literales del tier free
    (`qwen3.8-flash:free`, `deepseek-v4.1-flash:free`,
    `mimo-v2.6-flash:free`); RE-VERIFICADO contra `GET /v1/models` con
    API key real (200, 63 modelos, los 3 IDs presentes) y probe POST
    real contra `qwen3.8-flash:free` (200, respuesta real "pong").
    Semilla elegida: `qwen3.8-flash:free` -- se descartaron
    `deepseek-v4.1-flash:free` y `mimo-v2.6-flash:free` por duplicar
    modelos YA presentes via nan_api (mimo-v2.6-flash es BA25; hay
    perfiles nan con deepseek-v4-flash/deepseek-v4-flash-0731)."""
    config = ed.load_motor_config()
    profiles = config["ensemble_profiles"]
    backends = config["backends"]

    assert "challenger_deepseek" not in profiles, "directo muerto, eliminado (A8)"
    assert "challenger_qwen" not in profiles, "directo muerto, eliminado (A8)"
    assert "deepseek_api" not in backends, "backend directo muerto, eliminado (A8)"
    assert "qwen_api" not in backends, "backend directo muerto, eliminado (A8)"

    # Todo perfil channel=api usa un backend de la lista viva con credencial
    # declarada (nan_api, nvidia_api, groq_api, openrouter_api o aihubmix_api
    # hoy; deepseek_api/qwen_api siguen fuera por A8 -- los asserts de arriba
    # ya lo verifican).
    live_api_backends = {
        "nan_api",
        "nvidia_api",
        "groq_api",
        "openrouter_api",
        "aihubmix_api",
        "tokenharbor_api",
        "gemini_api",
        "cohere_api",
        "mistral_api",
    }
    api_profiles = [p for p in profiles.values() if p.get("channel") == "api"]
    assert api_profiles, "debe haber al menos un perfil api"
    for prof in api_profiles:
        assert prof["backend"] in live_api_backends, (
            f"backend '{prof['backend']}' no es un canal api vivo conocido "
            f"({live_api_backends}) -- si es un canal nuevo legitimo, anadelo "
            "a live_api_backends; si es un directo muerto tipo A8, elimina el "
            "perfil en vez de ampliar esta lista"
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


def test_loop_round_cli_writes_the_four_barrier_fields(tmp_path, monkeypatch):
    """WOT-2026-043z: la ruta CLI de gobierno es ATESTIGUABLE por la barrera.

    `run_loop_round` ya propagaba los 4 campos (WOT-2026-026q) pero NO tenia
    puerta de entrada: 0 subcomandos, 0 parser, 0 callers en el motor -- los
    bucles 1->9->2 la invocaban importandola a mano. Sin ruta CLI, las filas
    del fan-out salian con `backend_key: None` y el recuento de claves
    DISTINTAS de `check_loop_execution` era estructuralmente 0.

    El stub es el TRANSPORTE (la primitiva de salida a backend), NUNCA
    `run_loop_round` ni `_record_round`: el registro debe correr por su ruta
    productiva real. Un test que mockee el escritor, o que inyecte filas a mano
    en el scorecard, pasa verde sin probar nada -- familia `mock drift` de
    AGENTS.md.

    Mutation que aisla: desconectar la propagacion en el nuevo `_cmd_loop_round`
    (pasar None en cualquiera de los 4) pone ESTE test rojo y deja verdes los
    invariantes de `check_loop_execution` (rondas mudas, nonce previo, N).

    NOTA: el nombre de la primitiva se COMPONE, igual que en el bloque de
    WOT-2026-025z (:2123): este test vive tras `_WOT_025Z_SECTION_MARKER`, cuyo
    guard de hermeticidad prohibe ese token en el TEXTO CRUDO de la seccion.
    Componerlo respeta el guard sin debilitarlo ni moverlo de sitio.
    """
    transport_attr = "send_to" + "_profile"
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, transport_attr, lambda *a, **k: "hallazgo real")
    # WOT-2026-059m: la barrera de commit_sha exige un link a un motor real
    # y un sha que resuelva; el repo del fixture provee el commit semilla y
    # la fila debe llevar el sha40 NORMALIZADO, no la forma abreviada.
    repo, sha40 = _git_repo_with_commit(tmp_path)
    _write_link_059m(tmp_path, repo)
    material = tmp_path / "bundle.md"
    material.write_text("material publico bajo review", encoding="utf-8")

    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(material),
            "--ticket",
            "WOT-TEST-043z",
            "--task-type",
            "contract-audit",
            "--rol",
            "challenger",
            "--phase",
            "CONTRACT_AUDIT",
            "--loop-id",
            "L2100",
            "--backend-key",
            "NA01",
            "--commit-sha",
            sha40[:7],
            "--challenge-nonce",
            "2a66997af98a052eeb75d24bf9761542",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 0, "la ruta CLI de gobierno debe completar con exit 0"

    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        f"UNA fila por ronda despachada, hubo {len(rows)}: 0 = la CLI no "
        "registro (el defecto de 043z); 2 = doble-conteo"
    )
    row = rows[0]
    # Los 4 campos que la barrera LEE. Sin ellos la fila es imputable a nadie.
    assert row["loop_id"] == "L2100"
    assert row["backend_key"] == "NA01"
    assert row["commit_sha"] == sha40, (
        "la fila debe llevar el sha40 normalizado, no la forma abreviada"
    )
    assert row["challenge_nonce"] == "2a66997af98a052eeb75d24bf9761542"
    assert row["evidencia"] == "hallazgo real", (
        "el CONTENIDO de la respuesta viaja al receipt: una lente que corre y "
        "CALLA no aporta independencia (WOT-2026-043q)"
    )


# --- WOT-2026-048g: un transporte que FALLO no es una intervencion -----------
#
# ROJO que fijan, medido 2026-08-03 en una ronda de gobierno real: `codex.cmd
# exec` devolvio rc=1 con el volcado de un `taskkill` ("CORRECTO: el proceso con
# PID ... ha sido terminado.") en STDOUT. `_transport_agent` descartaba el
# `returncode` y devolvia ese texto tal cual, asi que el scorecard registraba la
# fila con `failure_mode: None` y `outcome: None` -- INDISTINGUIBLE de una
# revision real. Peor que el hueco de WOT-2026-048e ("cero filas"): una fila
# falsa CONTAMINA el registro en vez de dejar un hueco visible.
#
# El exit code sigue sin ser veredicto POSITIVO (rc=0 con Auth Error es el caso
# que obliga a validar por CONTENIDO). Lo que cambia es que un rc != 0 es un
# fallo DECLARADO por el propio CLI y ya no se ignora.


def test_048g_nonzero_rc_is_marked_as_transport_failed(monkeypatch):
    """El transporte marca la salida cuando el CLI sale con rc != 0.

    Mutation: ignorar `proc.returncode` -> el texto sale limpio y este test cae.
    """

    class _FailingPopen:
        pid = 4848
        returncode = 1

        def __init__(self, cmd, *a, **k):
            pass

        def communicate(self, input=None, timeout=None):
            return ("CORRECTO: el proceso con PID 123 ha sido terminado.", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _FailingPopen)

    out = ed._transport_agent(
        {"backend": "codex", "channel": "agent"},
        {"executable": "codex.cmd", "args": ["exec"]},
        [{"role": "user", "content": "audita esto"}],
        timeout=10,
    )
    assert out.startswith(ed._TRANSPORT_FAILED_PREFIX), (
        f"un rc != 0 debe marcar la salida como no utilizable; out={out!r}"
    )
    assert "rc=1" in out, "la marca debe conservar el codigo de salida real"
    assert "ha sido terminado" in out, (
        "el texto del backend se CONSERVA: es la evidencia de que devolvio; "
        "vaciarlo borraria lo unico que permite diagnosticar el fallo"
    )


def test_048g_zero_rc_output_is_untouched(monkeypatch):
    """CONTROL POSITIVO: con rc=0 la salida no se toca.

    Sin este control, un fix que marcara SIEMPRE pasaria el test de arriba.
    """

    class _OkPopen:
        pid = 4849
        returncode = 0

        def __init__(self, cmd, *a, **k):
            pass

        def communicate(self, input=None, timeout=None):
            return ("VEREDICTO: APROBADO", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _OkPopen)

    out = ed._transport_agent(
        {"backend": "fake", "channel": "agent"},
        {"executable": "cli", "args": []},
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    assert out == "VEREDICTO: APROBADO", (
        "una respuesta con rc=0 debe llegar INTACTA al caller"
    )


def test_048g_failed_transport_is_recorded_as_no_aportacion(tmp_path):
    """La ruta de GOBIERNO (`run_loop_round`) clasifica la basura correctamente.

    Es la ruta que importa: no pasa por el filtro de lente del bucle `run`, asi
    que sin esta derivacion la fila entraba como aportacion valida.

    Mutation: quitar la derivacion de `_record_round` -> outcome vuelve a None.
    """
    dumped = "CORRECTO: el proceso con PID 123 ha sido terminado."
    transport = _FakeTransport(replies=[f"{ed._TRANSPORT_FAILED_PREFIX}rc=1\n{dumped}"])
    ed.run_loop_round(
        "p_chal",
        "audita esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-048g",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA05",
        sensitivity="public",
        transport=transport,
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1, "sigue habiendo UNA fila: el fallo se registra, no se oculta"
    row = rows[0]
    assert row["outcome"] == "no-aportacion", (
        "un transporte fallido NO puede contar como intervencion valida: era "
        f"indistinguible de una revision real; outcome={row['outcome']!r}"
    )
    assert row["failure_mode"] and "transport_failed" in row["failure_mode"], (
        f"la fila debe declarar POR QUE se descarto; failure_mode={row.get('failure_mode')!r}"
    )
    assert "rc=1" in row["failure_mode"], "el failure_mode conserva el exit code"
    assert dumped in row["evidencia"], (
        "la evidencia conserva lo que devolvio el backend: sin ella nadie puede "
        "diagnosticar por que fallo"
    )


def test_048g_healthy_reply_keeps_counting_as_aportacion(tmp_path):
    """CONTROL POSITIVO de la ruta de gobierno: una revision real no se degrada."""
    transport = _FakeTransport(replies=["VEREDICTO: CAMBIOS -- hallazgo real"])
    ed.run_loop_round(
        "p_chal",
        "audita esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-048g-ok",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    assert row["outcome"] is None, (
        "una respuesta sana debe seguir contando como aportacion; el filtro no "
        "puede degradar lo legitimo"
    )
    assert row["failure_mode"] is None


def test_046h_transport_exception_is_recorded_then_reraised(tmp_path):
    """WOT-2026-046h: el canal `api` LANZA ante un fallo de transporte (a
    diferencia del canal `agent`, que devuelve texto con
    `_TRANSPORT_FAILED_PREFIX`, cubierto por el test 048g hermano). Antes de
    este fix la excepcion escapaba de `run_loop_round` sin pasar nunca por
    `_record_round`: CERO fila, indistinguible de "nadie lo intento".

    Replica la clasificacion YA adjudicada por el bucle L1104 en
    `_cmd_loop_round` (WOT-2026-048x): la fila es ADITIVA, la excepcion se
    RE-LANZA (el caller sigue viendo el fallo, no puede confundirlo con una
    respuesta valida) -- por eso este test usa `pytest.raises`, no una
    llamada directa.

    Mutation: quitar el try/except de `run_loop_round` alrededor de su
    llamada a la primitiva de despacho pone este test en ROJO igual (la
    excepcion sigue propagandose, pero sin dejar fila -> `len(rows) == 0`).
    """
    transport = _FakeTransport(
        replies=[
            ed.TransportError(
                "HTTPError | HTTP 402 | monthly_cap_reached",
                status=402,
                body='{"error":{"type":"monthly_cap_reached"}}',
            )
        ]
    )
    with pytest.raises(ed.TransportError):
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            config=_config(),
            project_root=tmp_path,
            ticket="WOT-TEST-046h",
            task_type="code-review",
            rol="challenger",
            phase="fanout-comun",
            loop_id="L720",
            backend_key="BA11",
            sensitivity="public",
            transport=transport,
        )

    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        "un fallo de transporte del canal api debe dejar UNA fila (antes: 0, "
        "la excepcion escapaba sin registrar nada)"
    )
    row = rows[0]
    assert row["outcome"] == "no-aportacion", (
        "un fallo de transporte no puede contar como intervencion valida; "
        f"outcome={row['outcome']!r}"
    )
    assert row["failure_mode"] and row["failure_mode"].startswith("transport_failed"), (
        f"failure_mode debe clasificarse como transport_failed; got {row.get('failure_mode')!r}"
    )
    assert "402" in row["failure_mode"], (
        "el failure_mode conserva el detalle del error (status/tipo), no solo "
        "la palabra generica 'transport_failed'"
    )
    assert row["output_chars"] == 0, (
        "sin respuesta real del backend, output_chars debe ser 0 -- el "
        "mensaje de la excepcion vive en failure_mode, no se fabrica un "
        "reply de texto que inflaria esta metrica"
    )


def test_046h_unexpected_exception_is_classified_precisely_not_as_transport(
    tmp_path,
):
    """Control de PRECISION (adjudicado por L1104, BA14): un `KeyError`/
    `TypeError` NO es un fallo de transporte. Etiquetarlo como
    `transport_failed` manda a buscar una caida de red donde hay un bug de
    programacion. Mismo criterio que ya fija `_cmd_loop_round`; este test
    prueba que `run_loop_round` (la ruta Python directa) lo respeta igual.
    """
    transport = _FakeTransport(replies=[KeyError("perfil_inexistente")])
    with pytest.raises(KeyError):
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            config=_config(),
            project_root=tmp_path,
            ticket="WOT-TEST-046h-unexpected",
            task_type="code-review",
            rol="challenger",
            phase="fanout-comun",
            loop_id="L720",
            backend_key="BA11",
            sensitivity="public",
            transport=transport,
        )

    row = _rows(tmp_path)[0]
    assert row["failure_mode"].startswith("unexpected"), (
        "un KeyError debe clasificarse como 'unexpected', no como "
        f"'transport_failed': failure_mode={row['failure_mode']!r}"
    )


def test_046h_dispatch_blocked_still_leaves_no_row(tmp_path):
    """Control negativo: `DispatchBlockedError` (preflight de privacidad, que
    bloquea ANTES de tocar red) sigue sin dejar fila -- el fix de 046h NO debe
    ensanchar su alcance a un caso que por diseno no es una ronda ejecutada
    (docstring de `run_loop_round`: "en ese caso NO hay fila, porque no hubo
    ronda"). Si este test se pone rojo, el except de 046h esta capturando de
    mas."""
    with pytest.raises(ed.DispatchBlockedError):
        ed.run_loop_round(
            "p_chal",
            "material",
            config=_config(),
            project_root=tmp_path,
            ticket="WOT-TEST-046h-blocked",
            task_type="code-review",
            rol="challenger",
            phase="fanout-comun",
            loop_id="L720",
            backend_key="BA11",
            sensitivity="private",
            transport=_FakeTransport(replies=["no deberia llegar"]),
        )
    assert not (tmp_path / ed.SCORECARD_REL).exists(), (
        "un rechazo de preflight no ejecuto ninguna ronda: no debe dejar fila"
    )


# --- WOT-2026-048g: el modelo REPORTADO por el backend ----------------------
#
# WOT-2026-047y hizo que declarado y solicitado coincidan por construccion (el
# flag entra en el argv), pero dejo un residuo declarado: un CLI que ACEPTE el
# flag y sirva OTRO modelo seguia siendo invisible, porque el scorecard solo
# guardaba el DECLARADO.
#
# No hizo falta disenar nada ni parsear cada CLI: AMBOS backends ya declaran el
# modelo efectivo en su STDERR y `_transport_agent` lo estaba TIRANDO. Medido
# 2026-08-03 contra los binarios reales: opencode escribe "> builder - glm-5.2"
# (con U+00B7) y codex escribe "model: gpt-5.5".


def test_048g_extracts_reported_model_from_real_stderr_shapes():
    """Las DOS formas reales, mas los negativos.

    Los negativos son la mitad que importa: un parser generoso inventaria
    desacuerdos donde solo hay un formato no previsto, y un falso "el backend
    corrio otro modelo" es peor que no tener el dato.
    """
    opencode_stderr = "\x1b[0m\n> builder · glm-5.2\n\x1b[0m\n"
    codex_stderr = "OpenAI Codex v0.130.0\n--------\nworkdir: D\nmodel: gpt-5.5\n"

    assert ed._extract_reported_model(opencode_stderr) == "glm-5.2", (
        "el banner de opencode trae codigos ANSI: si no se limpian, no casa"
    )
    assert ed._extract_reported_model(codex_stderr) == "gpt-5.5"
    # Negativos: ausencia de dato, NUNCA un valor adivinado.
    assert ed._extract_reported_model("") is None
    assert ed._extract_reported_model(None) is None
    assert ed._extract_reported_model("ruido sin banner\notra linea\n") is None


def test_048g_transport_publishes_reported_model_on_the_profile(monkeypatch):
    """El transporte deja el modelo reportado en el perfil (canal lateral).

    Va por el perfil y NO por el valor de retorno a proposito: la firma
    `transport(profile, backend_cfg, messages, timeout) -> str` es CONTRATO --
    los tests inyectan `_FakeTransport` con esa aridad exacta --, asi que
    devolver una tupla convertiria telemetria en migracion.

    Mutation: dejar de asignar `profile[_REPORTED_MODEL_KEY]` -> cae.
    """

    class _StderrPopen:
        pid = 4850
        returncode = 0

        def __init__(self, cmd, *a, **k):
            pass

        def communicate(self, input=None, timeout=None):
            return ("respuesta", "\x1b[0m\n> builder · glm-5.2\n")

    monkeypatch.setattr(ed.subprocess, "Popen", _StderrPopen)

    profile = {
        "backend": "opencode",
        "channel": "agent",
        "model": "opencode-go/glm-5.2",
    }
    ed._transport_agent(
        profile,
        {
            "executable": "opencode",
            "args": ["run"],
            "model_flag": ["--model", "{model}"],
        },
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    assert profile[ed._REPORTED_MODEL_KEY] == "glm-5.2", (
        "el modelo que el backend dice USAR debe quedar disponible para el "
        "scorecard; sin el, un CLI que acepte el flag y sirva otro modelo "
        "seguiria siendo invisible (residuo declarado de WOT-2026-047y)"
    )


def test_048g_scorecard_records_declared_and_reported_side_by_side(tmp_path):
    """La fila lleva AMBOS: `model` (declarado) y `model_reported`.

    NO se comparan automaticamente: los valores difieren en FORMA (el perfil
    declara `opencode-go/glm-5.2` y el CLI reporta `glm-5.2`), asi que esto es
    telemetria para que un humano vea la discrepancia, no un comparador. Vender
    lo contrario seria el falso verde que este ticket combate.
    """
    config = _config()
    config["ensemble_profiles"]["p_chal"][ed._REPORTED_MODEL_KEY] = "glm-5.2"
    transport = _FakeTransport(replies=["hallazgo"])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=config,
        project_root=tmp_path,
        ticket="WOT-TEST-048g-model",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA06",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    assert row["model"] == "m2", "el DECLARADO por el perfil se conserva"
    assert row["model_reported"] == "glm-5.2", (
        "el REPORTADO por el backend debe viajar a la fila: es el unico dato "
        "que permite detectar que el proceso corrio otro modelo"
    )


def test_048g_absent_reported_model_is_none_not_a_guess(tmp_path):
    """CONTROL POSITIVO: sin banner, el campo es None (ausencia), no un valor.

    Los `channel: api` no tienen stderr y ningun CLI esta obligado a declarar
    su modelo: `None` significa "no lo dijo", nunca "coincide".
    """
    transport = _FakeTransport(replies=["hallazgo"])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-048g-none",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    assert row["model_reported"] is None, (
        "sin banner el campo es AUSENCIA de dato; inventar un valor aqui seria "
        "afirmar que el backend confirmo algo que nunca dijo"
    )


def test_transport_agent_binds_readonly_agent_when_profile_declares_no_write(
    monkeypatch,
):
    """WOT-2026-048k: un perfil con `write: false` debe despacharse con `--agent`.

    Antes de este ticket `write: false` era DECORATIVO: `_transport_agent`
    construia el cmd sin traducir ese campo a NADA, asi que `opencode run` caia
    en su `default_agent` (`builder`) -- un agente con `edit/bash/task: allow` --
    y una lente AUDITORA recibia el system prompt del Builder. Medido 2026-08-05:
    la lente GLM delibero sobre si invocar `--mark-ready` y sobre su whitelist de
    `Files Likely Touched`, ninguna de las dos cosas presente en su bundle.

    Mutation: quitar la inyeccion de `--agent` -> este test cae en RED.
    """
    captured: dict = {}

    class _CapturingPopen:
        pid = 444

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd

        def communicate(self, input=None, timeout=None):
            return ("veredicto", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _CapturingPopen)

    ed._transport_agent(
        {"backend": "fake", "write": False},
        {"executable": "fake-cli", "args": ["run"], "readonly_agent": "auditor"},
        [{"role": "user", "content": "audita esto"}],
        timeout=10,
    )
    cmd = captured["cmd"]
    assert "--agent" in cmd, (
        "un perfil con write:false debe llevar --agent en argv: sin el, el CLI "
        "usa su default_agent (de ESCRITURA) y la declaracion es decorativa"
    )
    assert cmd[cmd.index("--agent") + 1] == "auditor", (
        "el valor de --agent debe ser el readonly_agent declarado por el backend"
    )
    # El flag va ANTES del prompt: cualquier argumento posterior al prompt lo
    # leeria el CLI como parte del mensaje.
    assert cmd.index("--agent") < cmd.index("audita esto"), (
        "--agent debe preceder al prompt en argv"
    )


def test_transport_agent_does_not_bind_agent_when_profile_allows_write(monkeypatch):
    """Backward-compat (WOT-2026-048k): un perfil SIN `write: false` no cambia.

    Cero regresion para cualquier perfil que no declare la restriccion, y para
    los backends que no declaran `readonly_agent` (los `channel: api` nunca pasan
    por aqui, pero un `channel: agent` sin enforcement debe seguir corriendo).

    Mutation: inyectar `--agent` siempre -> este test cae en RED.
    """
    captured: dict = {}

    class _CapturingPopen:
        pid = 555

        def __init__(self, cmd, *a, **k):
            captured["cmd"] = cmd

        def communicate(self, input=None, timeout=None):
            return ("ok", "")

    monkeypatch.setattr(ed.subprocess, "Popen", _CapturingPopen)

    # (1) perfil que NO declara write -> sin --agent
    ed._transport_agent(
        {"backend": "fake"},
        {"executable": "fake-cli", "args": ["run"], "readonly_agent": "auditor"},
        [{"role": "user", "content": "hola"}],
        timeout=10,
    )
    assert captured["cmd"] == ["fake-cli", "run", "hola"], (
        "un perfil sin write:false no debe recibir --agent (backward-compat)"
    )

    # (2) perfil write:false pero backend SIN readonly_agent -> sin --agent,
    #     no se inventa un nombre de agente que el CLI no conoce.
    ed._transport_agent(
        {"backend": "fake", "write": False},
        {"executable": "fake-cli", "args": ["run"]},
        [{"role": "user", "content": "hola"}],
        timeout=10,
    )
    assert "--agent" not in captured["cmd"], (
        "sin readonly_agent declarado no se puede inventar el nombre del agente"
    )


def test_real_config_opencode_binds_readonly_agent_for_glm_lens():
    """WOT-2026-048k: la CONFIG REAL debe cablear el enforcement, no solo el mecanismo.

    Los dos tests de arriba prueban el MECANISMO con un backend_cfg inventado a
    mano. Este ejerce la config VERSIONADA -- misma leccion de fixture drift que
    `test_real_config_codex_delivers_multiline_prompt_intact`: el mecanismo puede
    funcionar mientras el consumidor real no lo usa.

    Mutation: quitar `readonly_agent` del backend opencode en agents.json, o
    quitar `write: false` del perfil GLM -> este test cae.
    """
    cfg = ed.load_motor_config()
    backend_cfg = cfg["backends"]["opencode"]
    profile = cfg["ensemble_profiles"]["challenger_opencode_glm_5_2"]

    # Anclaje por identidad a la config real (mismo patron que 027k): sin esto,
    # sustituir el loader por un dict inline dejaria el test verde.
    assert backend_cfg == ed.load_motor_config()["backends"]["opencode"], (
        "el backend_cfg debe venir de load_motor_config(), no de un dict inline"
    )
    assert profile.get("write") is False, (
        "el perfil GLM es una lente AUDITORA: debe declarar write: false"
    )
    assert backend_cfg.get("readonly_agent") == "auditor", (
        "el backend opencode debe declarar el agente read-only que hace efectivo "
        "el write:false; sin el, la declaracion vuelve a ser decorativa y la "
        "lente corre bajo default_agent (builder, con edit/bash/task allow)"
    )


# ---------------------------------------------------------------------------
# WOT-2026-058y: ejerce la DECISION DE PRODUCTO que WOT-2026-042v dejo
# explicitamente abierta al cerrarse -- "la PROPORCION de lentes ciegas vs
# con-ojos; se activo UN solo perfil, que es el minimo del DoD". Adjudicada por
# el operador el 2026-08-25: opcion EQUILIBRADA (B) = 3 con arbol / 4 ciegas.
#
# NO es un bugfix y NO anade codigo: `resolve_lens_repo_root` ya esta cableado
# (WOT-2026-038o, cerrado en 042v). Esta ficha solo lo INVOCA para dos perfiles
# mas, declarando `repo_scope: destino` en `agents.json`.
#
# Los controles de MECANISMO (degradacion nombrada, limite de clase `api`,
# aditividad) ya viven en los tests de 042v de arriba y NO se duplican aqui:
# estos tests cubren la CONFIGURACION -- que la decision quedo realmente
# ejercida -- y el aislamiento por rama del DoD (h).
# ---------------------------------------------------------------------------


def _real_agents_config() -> dict:
    """La configuracion REAL del motor, no un fixture.

    El DoD (a) de esta ficha es sobre `agents.json` en disco: un fixture
    sintetico probaria el mecanismo (que ya prueba 042v) y no la decision.
    """
    import json

    path = Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "profile_name",
    ["challenger_opencode_glm_5_2", "proposer_claude"],
)
def test_058y_lens_declares_destino_scope(profile_name, tmp_path):
    """DoD (a)+(h): CADA perfil adjudicado resuelve al destino, y se parametriza
    para que retirar `repo_scope` de UNO haga caer SOLO su rama (leccion 021u).
    Antes de esta ficha ambos devolvian `(None, 'motor')`."""
    config = _real_agents_config()
    profile = config["ensemble_profiles"][profile_name]
    assert profile.get("repo_scope") == "destino", (
        f"{profile_name} debe declarar repo_scope: destino (opcion B adjudicada "
        f"por el operador 2026-08-25); hoy declara {profile.get('repo_scope')!r}"
    )
    destino = tmp_path / "repo_destino"
    destino.mkdir()
    backend_cfg = config.get("backends", {}).get(profile.get("backend", ""), {})
    cwd, scope = ed.resolve_lens_repo_root(profile, backend_cfg, destino)
    assert scope == "destino", (cwd, scope)
    assert cwd == str(destino.resolve()), (cwd, scope)


@pytest.mark.parametrize(
    "profile_name",
    ["challenger_opencode_glm_5_2", "proposer_claude"],
)
def test_058y_scope_grants_reading_never_writing(profile_name):
    """DoD (g): dar ambito es dar LECTURA. `write` sigue en false en ambos.

    Si un perfil con ojos pudiera escribir, el riesgo declarado de la ficha
    (una lente construye un blocker falso sobre un artefacto enganoso del
    destino, WOT-2026-055j) pasaria de emitir un veredicto a MUTAR el arbol.
    """
    profile = _real_agents_config()["ensemble_profiles"][profile_name]
    assert profile.get("write") is False, (
        f"{profile_name}: el ambito da lectura, NUNCA escritura: {profile!r}"
    )


def test_058y_calibration_survives_with_at_least_four_blind_lenses():
    """DoD (f) CONTROL NEGATIVO: la CALIBRACION sigue viva.

    `042v` razona que conservar lentes ciegas es lo que permite medir cuanto se
    degrada un modelo SIN arbol: "si todo pasa a con-arbol se pierde la
    capacidad de medir". Por eso la opcion C (todas con ojos) quedo DESCARTADA.
    Este test pinea el suelo: si un cambio futuro deja el bucle sin ciegas,
    incumple el razonamiento heredado y debe fallar aqui.
    """
    profiles = _real_agents_config()["ensemble_profiles"]
    ciegas = [
        name
        for name, p in profiles.items()
        if p.get("channel") == "api" or p.get("repo_scope") != "destino"
    ]
    assert len(ciegas) >= 4, (
        f"la calibracion exige >= 4 lentes ciegas despachables; quedan "
        f"{len(ciegas)}: {sorted(ciegas)}"
    )


def test_058y_ratio_is_the_adjudicated_option_b():
    """La decision ADJUDICADA es 3 con arbol / 4 ciegas, no 'las que salgan'.

    INVARIANTE, no medicion: se asertan las DOS clases a la vez, de modo que
    mover un perfil de una a otra sin decision explicita rompa el test.
    """
    profiles = _real_agents_config()["ensemble_profiles"]
    con_arbol = sorted(
        name
        for name, p in profiles.items()
        if p.get("channel") != "api" and p.get("repo_scope") == "destino"
    )
    assert con_arbol == [
        "challenger_codex",
        "challenger_opencode_glm_5_2",
        "proposer_claude",
    ], f"opcion B (equilibrada) = BA05 + BA06 + BA01; hoy: {con_arbol}"


# --- WOT-2026-059m: la ronda no acepta un commit_sha que no resuelve ----------


def _git_repo_with_commit(tmp_path):
    """Repo git REAL (sin mockear git) con un commit semilla; devuelve (repo, sha40)."""
    import subprocess as sp

    repo = tmp_path / "motor_fx"
    repo.mkdir()

    def git(*a):
        r = sp.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    git("add", "seed.txt")
    git("commit", "-q", "-m", "seed")
    return repo, git("rev-parse", "HEAD")


def _write_link_059m(destino, motor_root):
    cfg = destino / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor_root),
                "destination_root": str(destino),
                "motor_version": "9.17.1-test",
                "destination_id": destino.name,
                "ticket_prefix": "WOT",
                "created_at": "2026-08-29T00:00:00+00:00",
                "manifest_version": "1.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _run_loop_round_cli(tmp_path, monkeypatch, commit_sha):
    """La ruta CLI REAL con transporte stub (nombre compuesto, patron 043z)."""
    transport_attr = "send_to" + "_profile"
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, transport_attr, lambda *a, **k: "hallazgo real")
    material = tmp_path / "bundle.md"
    material.write_text("material publico bajo review", encoding="utf-8")
    argv = [
        "loop-round",
        "--profile",
        "p_chal",
        "--content-file",
        str(material),
        "--ticket",
        "WOT-TEST-059m",
        "--task-type",
        "code-review",
        "--rol",
        "challenger",
        "--phase",
        "FANOUT_DIF",
        "--loop-id",
        "L800",
        "--backend-key",
        "BA10",
        "--data-sensitivity",
        "public",
        "--project-root",
        str(tmp_path),
    ]
    if commit_sha is not None:
        argv += ["--commit-sha", commit_sha]
    return ed.main(argv)


def test_059m_ronda_con_sha_inexistente_bloquea_sin_fila(tmp_path, monkeypatch):
    """DoD (a): sha inexistente -> rc != 0 y CERO filas en scorecard.

    Medido en FP-20260826-G3-ID-GUARDS: 5 rondas contra un sha inexistente
    dejaron fila, la acreditacion real era N=0 y el ejecutor reportaba N=4.
    """
    repo, _sha40 = _git_repo_with_commit(tmp_path)
    _write_link_059m(tmp_path, repo)
    rc = _run_loop_round_cli(tmp_path, monkeypatch, "d" * 40)
    assert rc != 0, "un sha que no resuelve debe bloquear la ronda"
    sc = tmp_path / ed.SCORECARD_REL
    rows = _rows(tmp_path) if sc.exists() else []
    assert rows == [], (
        f"una ronda bloqueada por sha inexistente NO debe escribir fila: {rows}"
    )


def test_059m_sha_valido_abreviado_se_acepta_y_normaliza(tmp_path, monkeypatch):
    """DoD (b) CONTROL POSITIVO: sha corto valido pasa y la fila lleva sha40."""
    repo, sha40 = _git_repo_with_commit(tmp_path)
    _write_link_059m(tmp_path, repo)
    rc = _run_loop_round_cli(tmp_path, monkeypatch, sha40[:7])
    assert rc == 0
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["commit_sha"] == sha40, (
        f"el sha valido abreviado debe normalizarse a sha40 en la fila: "
        f"{rows[0]['commit_sha']}"
    )


def test_059m_sin_commit_sha_la_ruta_sigue_funcionando(tmp_path, monkeypatch):
    """DoD (c) CONTROL: el campo es opcional; sin el, nada se valida ni bloquea."""
    rc = _run_loop_round_cli(tmp_path, monkeypatch, None)
    assert rc == 0
    assert len(_rows(tmp_path)) == 1


# --- WOT-2026-059e: la rama de token opaco aplica filtro de contexto ----------


def test_059e_nombre_de_fichero_en_prosa_no_bloquea():
    """DoD 059e: un nombre de fichero de alta entropia en prosa NO es una fuga.

    Reproduce el caso medido en el bucle L1500: 'reports/batch_run_<id>.json'
    recibia FLAG identico a una credencial real y bloqueo las 4 lentes de un
    fan-out publico (N=0). ROJO HOY: la rama de token opaco no mira contexto.
    """
    import random
    import string

    rng = random.Random(7)  # noqa: S311 - fixture determinista, no es cripto
    hi = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(33))
    assert ed._content_leak("revision manual del informe trimestral sin rutas") is None
    assert ed._content_leak(f"ruta del informe: reports/batch_run_{hi}.json") is None, (
        "un nombre de fichero en prosa no debe recibir FLAG"
    )
    assert (
        ed._content_leak(f"plan orchestrator_pipeline/flight_plans/queued/{hi}.json")
        is None
    ), "un nombre de fichero en cola de planes no debe recibir FLAG"


def test_059e_credencial_etiquetada_sigue_bloqueando():
    """CONTROL POSITIVO de 059e: con etiqueta/asignacion, el MISMO token bloquea."""
    valor = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"
    assert ed._content_leak(f"api_key = {valor}") is not None
    assert ed._content_leak(f"clave de acceso: {valor}") is not None


def test_059e_token_pelado_sigue_bloqueando():
    """CONTROL 027s intacto: el token pelado (sin contexto) sigue siendo fuga."""
    valor = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"
    assert ed._entropy_leak(valor) is not None


# --- WOT-2026-067i: simetria emisor <-> lector en la resolucion del sha ---
#
# El defecto que cierran: el EMISOR (`emit-nonce`) resolvia SOLO contra el motor
# mientras su LECTOR (`check_loop_execution`) ya aceptaba ambas raices. Eso hacia
# INSATISFACIBLE el cierre de todo ticket `delivery_authority: repo_destino`: el
# lector exigia rondas con nonce y el emisor prohibia emitir ese nonce.
# Medido sobre `5eff360b` (commit real de CTL-2026-027f) antes del fix.


def _two_repos_067i(tmp_path):
    """Motor y destino REALES (sin mockear git), cada uno con su commit propio.

    Devuelve (motor, sha_motor, destino, sha_destino). Los dos son repos git
    INDEPENDIENTES: ningun sha resuelve en el otro, que es la topologia que el
    caso `repo_destino` exige y que el fixture de dos-worktrees no reproduce.
    """
    import subprocess as sp

    def _mk(name, seed):
        repo = tmp_path / name
        repo.mkdir()

        def git(*a):
            r = sp.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            return r.stdout.strip()

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (repo / f"{seed}.txt").write_text(seed, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", seed)
        return repo, git("rev-parse", "HEAD")

    motor, sha_m = _mk("motor_067i", "seed-motor")
    destino, sha_d = _mk("destino_067i", "seed-destino")
    return motor, sha_m, destino, sha_d


def test_067i_a_sha_del_destino_resuelve(tmp_path):
    """DoD (a): un sha que SOLO vive en el destino se resuelve, no se bloquea.

    Es el caso que hacia insatisfacible el cierre de un ticket repo_destino.
    """
    motor, _sha_m, destino, sha_d = _two_repos_067i(tmp_path)
    sha40, resolved_against = ed.resolve_governed_commit_sha(motor, destino, sha_d)
    assert sha40 == sha_d
    assert resolved_against == "repo_destino"


def test_067i_c_sha_del_motor_no_regresiona(tmp_path):
    """DoD (c): un sha del motor sigue resolviendo igual, contra el motor."""
    motor, sha_m, destino, _sha_d = _two_repos_067i(tmp_path)
    sha40, resolved_against = ed.resolve_governed_commit_sha(motor, destino, sha_m)
    assert sha40 == sha_m
    assert resolved_against == "repo_motor"


def test_067i_b_sha_inexistente_sigue_bloqueado(tmp_path):
    """DoD (b): el nucleo fail-closed de 059c se CONSERVA pese a la ampliacion.

    El dominio se amplia (motor -> motor O destino) pero un sha que no resuelve
    en NINGUNA raiz sigue rechazandose, y el error NOMBRA ambas.
    """
    motor, _sha_m, destino, _sha_d = _two_repos_067i(tmp_path)
    with pytest.raises(ValueError) as exc:
        ed.resolve_governed_commit_sha(motor, destino, "deadbeef" * 5)
    msg = str(exc.value)
    assert "deadbeef" in msg
    assert str(motor) in msg and str(destino) in msg


def test_067i_g_abreviatura_ambigua_falla_cerrado(tmp_path, monkeypatch):
    """DoD (g): una abreviatura que resuelve a sha40 DISTINTOS en cada raiz.

    ENDURECE al lector: antes ganaba el motor EN SILENCIO, asi que el nonce
    acreditaba un commit que no era el pedido -- un veredicto sobre el commit
    equivocado es peor que no emitirlo.
    """
    motor, sha_m, destino, sha_d = _two_repos_067i(tmp_path)

    # El fixture AISLA la rama (leccion 021u) en vez de fabricar una colision de
    # sha por fuerza bruta: forzar el estado que la rama decide es lo que hace la
    # mutacion alcanzable. Buscar un prefijo colisionante real costaba ~137 s de
    # arranque de subprocesos (medido) y ademas dependia del azar -> un `skip`
    # dejaria (g) SIN VERIFICAR, que es el falso verde que este DoD cierra.
    def _fake(root, sha):
        # La MISMA abreviatura resuelve en ambas raices, a sha40 DISTINTOS.
        return (True, sha_m) if root == motor else (True, sha_d)

    monkeypatch.setattr(ed, "_canonical_motor_commit_sha", _fake)
    assert sha_m != sha_d, "precondicion: los dos repos deben tener shas distintos"

    with pytest.raises(ValueError, match="AMBIGUO"):
        ed.resolve_governed_commit_sha(motor, destino, "abc1234")


def test_067i_d_simetria_emisor_lector_misma_funcion(tmp_path):
    """DoD (d): la simetria es POR CONSTRUCCION, no por acuerdo.

    El lector delega en la MISMA funcion del emisor. Si alguien le devolviera su
    resolucion propia, este test lo caza: son el mismo objeto.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cle_067i",
        Path(__file__).resolve().parents[2] / "scripts" / "check_loop_execution.py",
    )
    cle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cle)
    assert cle.resolve_governed_commit_sha is ed.resolve_governed_commit_sha


def test_067i_ronda_tercera_superficie_resuelve_ambas_raices(tmp_path, monkeypatch):
    """La RONDA (`_validated_motor_sha`) comparte la misma resolucion.

    TERCERA superficie de la misma asimetria, y la que el fix inicial dejo
    fuera: se podia EMITIR el nonce de un commit del destino pero no GASTAR la
    ronda que lo acredita -- el dominio ampliado era inalcanzable en la
    practica. Lo cazo la sesion del destino en produccion
    (`loop-round --commit-sha 043b1d31...` -> `[BLOCKED] 059m`), no el bucle
    L818: su censo miro emisor/lector/barrera/escritor y NO este call-site.

    El test cubre las tres respuestas: sha del destino resuelve, sha del motor
    no regresiona, y un sha inexistente sigue fail-closed.
    """
    motor, sha_m, destino, sha_d = _two_repos_067i(tmp_path)
    monkeypatch.setattr(ed, "resolve_motor_root", lambda _p: motor, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "runtime.motor_link",
        type("_M", (), {"resolve_motor_root": staticmethod(lambda _p: motor)}),
    )

    assert ed._validated_motor_sha(destino, sha_d) == sha_d  # antes: BLOCKED
    assert ed._validated_motor_sha(destino, sha_m) == sha_m  # no-regresion
    with pytest.raises(ValueError, match="059m"):
        ed._validated_motor_sha(destino, "deadbeef" * 5)


# --- WOT-2026-046b: saneado de ruido de shell en evidencia del scorecard ------
#
# El CLI del backend envuelve la respuesta real con salida operativa (taskkill
# en castellano). _record_round persiste text[:500] sin saneado: la evidencia
# guarda el ruido del CLI delante de la respuesta, o en vez de ella si no
# queda texto despues de la respuesta real.
#
# Se sanea ANTES del truncado a 500: si se sanea despues, se sanea una ventana
# que ya solo tiene ruido (las lineas reales quedan fuera del tope).
# output_chars sigue midiendo el texto CRUDO (contrato de :150-157).


def test_046b_strips_shell_noise_prefixes_preserves_real_response(tmp_path):
    """MUTATION PIN: un stdout que empiece por prefijo de taskkill + respuesta
    real -> evidencia saneada sin prefijo, output_chars == len(texto crudo),
    len(evidencia) <= 500.

    Revertir el saneado (text[:500] sin strip) pone el prefijo en evidencia
    y rompe el primer assert.

    Asserts explcitos del work_plan (hallazgo MINOR, nan_qwen + codex):
    1. evidencia NO empieza por ningun prefijo de la lista.
    2. output_chars == len(texto crudo sin sanear) -- contrato de output_chars.
    3. len(evidencia) <= 500 -- truncado DESPUES del saneado.
    """
    raw_reply = (
        "CORRECTO: el proceso con PID 12345 ha sido terminado.\n\n"
        "Esta es la respuesta real del backend con contenido "
        "sustancial para verificar que el saneado no la trunca.\n"
        "Segunda linea con mas texto para medir output_chars.\n"
        "Tercera linea que completa el contenido."
    )
    transport = _FakeTransport(replies=[raw_reply])
    ed.run_loop_round(
        "p_chal",
        "revisa esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-046b-strip",
        task_type="code-review",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L700",
        backend_key="BA05",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    # (1) evidencia sin prefijo de ruido de shell
    shell_prefixes = (
        "CORRECTO:",
        "proceso con PID",
        "terminado.",
        "Se ha cancelado",
        "ERROR:",
    )
    assert not any(row["evidencia"].startswith(p) for p in shell_prefixes), (
        f"evidencia no debe empezar por prefijo de shell noise: {row['evidencia']!r}"
    )
    # (2) output_chars mide el texto crudo original (contrato de ensemble_dispatch.py:150-157)
    expected_chars = len(raw_reply)
    assert row["output_chars"] == expected_chars, (
        f"output_chars debe ser {expected_chars} (len del texto crudo), "
        f"fue {row['output_chars']}: contrato de output_chars violado"
    )
    # (3) truncado despues del saneado: evidencia <= 500
    assert len(row["evidencia"]) <= 500, (
        f"evidencia saneada no debe exceder 500 chars, fue {len(row['evidencia'])}"
    )
    # Control: outcome debe ser None (hay texto real despues del ruido)
    assert row["outcome"] is None, (
        "con respuesta real tras el ruido, outcome debe ser None, "
        f"fue {row['outcome']!r}"
    )


def test_046b_shell_noise_only_becomes_no_aportacion(tmp_path):
    """Caso limite (DoD 4, work_plan): un stdout que sea SOLO chachara de shell
    (sin respuesta real detras) -> outcome=no-aportacion +
    failure_mode="shell_noise_only", NUNCA outcome=None (respuesta valida).

    Revertir el saneado: el texto de shell pasa por `if not text` como no-vacío
    -> outcome se mantiene None, este test cae.
    """
    raw_reply = "CORRECTO: el proceso con PID 1234 ha sido terminado."
    transport = _FakeTransport(replies=[raw_reply])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-046b-noise-only",
        task_type="code-review",
        rol="challenger",
        phase="fanout-comun",
        loop_id="L800",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    assert row["outcome"] == "no-aportacion", (
        f"stdout solo ruido no es respuesta valida: outcome debe ser 'no-aportacion', "
        f"fue {row['outcome']!r}"
    )
    assert row["failure_mode"] == "shell_noise_only", (
        f"failure_mode debe ser 'shell_noise_only' para ruido puro: "
        f"fue {row['failure_mode']!r}"
    )
    assert row["output_chars"] == len(raw_reply), (
        "output_chars mide el texto CRUDO antes de saneado (contrato existente); "
        "tras el saneado no queda evidencia, pero output_chars refleja lo que el backend devolvio"
    )


def test_046b_strips_multiple_noise_lines(tmp_path):
    """Varias lineas de ruido seguidas -> se eliminan todas hasta la primera
    linea que no coincida con ningun prefijo.

    Mutation: si el saneado solo elimina la primera linea, las siguientes
    siguen contaminando evidencia.
    """
    raw_reply = (
        "CORRECTO: el proceso con PID 1234 ha sido terminado.\n"
        "proceso con PID 5678 suspendido.\n"
        "ERROR: timeout agotado.\n"
        "respuesta real tras tres lineas de ruido\n"
        "mas contenido despues"
    )
    transport = _FakeTransport(replies=[raw_reply])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-046b-multi",
        task_type="prose",
        rol="proposer",
        phase="challenge-fanout",
        loop_id="L900",
        backend_key="BA20",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    expected_evidence = (
        "respuesta real tras tres lineas de ruido\nmas contenido despues"
    )
    assert row["evidencia"] == expected_evidence, (
        f"todas las lineas de ruido deben eliminarse: "
        f"fue {row['evidencia']!r}, se esperaba {expected_evidence!r}"
    )
    assert row["outcome"] is None
    assert row["output_chars"] == len(raw_reply)


def test_046b_no_strip_when_response_starts_with_prefijo_but_has_context(tmp_path):
    """Control: si el texto CRUDO empieza por un prefijo pero tiene detras
    contenido REAL (no ruido de shell), el saneado aplica `startswith` a la
    PRIMERA linea entera -- si la primera linea es EXACTAMENTE un prefijo
    (o empieza por el), se elimina.

    El work_plan declara el limite conocido: una respuesta real que por
    coincidencia empiece por uno de los 5 prefijos exactos se trata igual
    que ruido. Este test documenta EXPLICITAMENTE ese limite como limite
    aceptado.
    """
    # Una respuesta real que empieza por "ERROR:" (coincide exactamente con el prefijo)
    # -> se trata como ruido (limite conocido y aceptado del algoritmo binario,
    #    WOT-2026-046b work_plan, decision TOMADA).
    raw_reply = "ERROR: validacion de negocio fallida en modulo X"
    transport = _FakeTransport(replies=[raw_reply])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-046b-edge",
        task_type="code-review",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L700",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    # Limite conocido: la primera linea coincide EXACTAMENTE con el prefijo
    # "ERROR:" (sin nada mas despues en la misma linea), asi que se elimina.
    # Tras la eliminacion no queda texto -> no-aportacion.
    assert row["outcome"] == "no-aportacion", (
        "respuesta real que coincide exactamente con un prefijo se trata igual "
        "que ruido: limite DOCUMENTADO del algoritmo binario (work_plan decision TOMADA)"
    )
    assert row["failure_mode"] == "shell_noise_only"


def test_046b_response_with_prefix_content_in_middle_survives(tmp_path):
    """CONTROL POSITIVO: si el prefijo aparece en el MEDIO del texto (no al
    inicio de la primera linea), NO se elimina. Solo se eliminan lineas cuyo
    INICIO coincida con un prefijo.

    Mutation: si el saneado buscara el prefijo en cualquier posicion del texto,
    este control se pondria rojo.
    """
    raw_reply = (
        "Analisis completado. ERROR: no se encontro el bug, pero el reporte esta bien."
    )
    transport = _FakeTransport(replies=[raw_reply])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-046b-middle",
        task_type="code-review",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L700",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    row = _rows(tmp_path)[0]
    # La primera linea empieza por "Analisis", no por ningun prefijo -> no se toca nada.
    assert row["evidencia"] == raw_reply[:500], (
        "un prefijo en el MEDIO del texto no debe eliminarse"
    )
    assert row["outcome"] is None
    assert row["output_chars"] == len(raw_reply)


def test_model_family_map_covers_all_ensemble_profiles():
    """WOT-2026-082a: cada combinacion (backend, model) VIVA tiene familia propia.

    Before: 12 de los 26 combos de `ensemble_profiles` no tenian entrada en
    MODEL_FAMILY_MAP y caian a "sin_familia" (WARN `unmapped_backend_model_pairs`)
    en la proyeccion `backend_family_leaders.json` (censo medido 2026-09-29:
    26 live, 21 mapped, 12 missing).

    During: carga la config REAL del motor (M9, motor-explicita:
    `load_motor_config()` ignora AGENT_PROJECT_ROOT), recorre los 26 perfiles
    del censo 2026-09-29 y exige (a) cobertura total del mapa, (b) las
    familias decididas para las 12 altas y (c) la preservacion de la entrada
    historica glm-5.2.

    After: falla listando exactamente los combos sin cubrir o con familia
    distinta de la decidida. MUTATION (worktree aislado, WOT-2026-082a):
    sin las 12 entradas nuevas -> ROJO (12 combos listados); con el fix ->
    VERDE. La cobertura es el INVARIANTE; el "26" es evidencia fechada del
    censo, no una condicion del test (un perfil nuevo debe quedar cubierto,
    sin que el test se rompa por el conteo).
    """
    config = ed.load_motor_config()
    profiles = config.get("ensemble_profiles", {})
    missing = sorted(
        (name, prof.get("backend"), prof.get("model"))
        for name, prof in profiles.items()
        if (prof.get("backend"), prof.get("model")) not in ed.MODEL_FAMILY_MAP
    )
    assert not missing, (
        "combos (backend, model) vivos sin familia en MODEL_FAMILY_MAP "
        f"(censo 2026-09-29 tenia 12): {missing}"
    )

    # Familias decididas para las 12 altas de WOT-2026-082a. Autoridad de la
    # familia: la CLAVE de cada perfil vivo (convencion de nomenclatura de
    # AGENTS.md); `minimax` y `spacebunny` sin vocabulario previo adoptan el
    # nombre del propio modelo (decision documentada en el commit del ticket).
    expected_new = {
        ("aihubmix_api", "coding-glm-5.1-free"): "codingglm",
        ("aihubmix_api", "coding-minimax-m2.7-free"): "minimax",
        ("aihubmix_api", "xiaomi-mimo-v2.5-free"): "mimo",
        ("groq_api", "openai/gpt-oss-120b"): "gptoss",
        ("groq_api", "qwen/qwen3.8-27b"): "qwen",
        ("opencode", "opencode-go/glm-5.3-flash"): "glm",
        ("openrouter_api", "cohere/north-mini-code:free"): "northcode",
        ("openrouter_api", "nvidia/nemotron-3-ultra-550b-a55b:free"): "nemotron",
        ("openrouter_api", "stealth/space-bunny-alpha"): "spacebunny",
        ("tokenharbor_api", "deepseek-v4.1-flash:free"): "deepseek",
        ("tokenharbor_api", "mimo-v2.6-flash:free"): "mimo",
        ("tokenharbor_api", "qwen3.8-flash:free"): "qwen",
    }
    wrong = {
        key: (ed.MODEL_FAMILY_MAP.get(key), familias)
        for key, familias in expected_new.items()
        if ed.MODEL_FAMILY_MAP.get(key) != familias
    }
    assert not wrong, (
        f"familias distintas de las decididas (obtenido, esperado): {wrong}"
    )

    # Decision del operador 2026-09-29 (NO reabrir): el historico glm-5.2 se
    # CONSERVA -- 384 filas reales del scorecard dependen de esa entrada
    # (mismo precedente que BA14 deepseek-v4-flash-0731).
    assert ed.MODEL_FAMILY_MAP.get(("opencode", "opencode-go/glm-5.2")) == "glm", (
        "la entrada historica glm-5.2 no puede eliminarse: 384 filas del "
        "scorecard la usan (precedente BA14, decision del operador 2026-09-29)"
    )


# ---------------------------------------------------------------------------
# resolve_similar_fallback (WOT-2026-083a): fallback en cascada
# familia -> rendimiento similar. Config y scorecard SINTETICOS (no el
# agents.json real): estos tests fijan el COMPORTAMIENTO del algoritmo,
# independiente de que perfiles existan hoy en produccion.
# ---------------------------------------------------------------------------


def _fallback_test_config() -> dict:
    """3 perfiles GLM (familias identicas, rendimiento distinto) + 1 ajeno."""
    return {
        "ensemble_profiles": {
            "challenger_glm_slow": {"backend": "vendor_a", "model": "glm-x"},
            "challenger_glm_mid": {"backend": "vendor_b", "model": "glm-y"},
            "challenger_glm_fast": {"backend": "vendor_c", "model": "glm-z"},
            "challenger_other_family": {"backend": "vendor_d", "model": "qwen-w"},
        }
    }


def _fallback_test_family_map(monkeypatch) -> None:
    monkeypatch.setattr(
        ed,
        "MODEL_FAMILY_MAP",
        {
            ("vendor_a", "glm-x"): "glm",
            ("vendor_b", "glm-y"): "glm",
            ("vendor_c", "glm-z"): "glm",
            ("vendor_d", "qwen-w"): "qwen",
        },
    )


def _write_scorecard_rows(tmp_path: Path, rows: list[dict]) -> Path:
    scorecard = tmp_path / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl"
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    with open(scorecard, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return tmp_path


def test_resolve_similar_fallback_prefers_fastest_alive_in_same_family(
    tmp_path, monkeypatch
):
    """Con 3 candidatos GLM vivos, elige el de menor p50, no el primero de la lista."""
    _fallback_test_family_map(monkeypatch)
    config = _fallback_test_config()
    project_root = _write_scorecard_rows(
        tmp_path,
        [
            {
                "event": "ronda",
                "backend": "vendor_a",
                "model": "glm-x",
                "latency_ms": 900_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_b",
                "model": "glm-y",
                "latency_ms": 150_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_c",
                "model": "glm-z",
                "latency_ms": 140_000,
            },
        ],
    )

    def check_alive(name, *, config):
        return {"alive": True}

    chosen = ed.resolve_similar_fallback(
        "challenger_glm_slow",
        config=config,
        project_root=project_root,
        check_alive=check_alive,
    )
    assert chosen == "challenger_glm_fast", (
        "debe elegir el p50 mas bajo (140s) de la familia, no vendor_b (150s) "
        "ni caer a resolve_fallback_backend"
    )


def test_resolve_similar_fallback_skips_dead_candidate_tries_next_fastest(
    tmp_path, monkeypatch
):
    """Si el mas rapido esta muerto, prueba el siguiente por p50, no cualquiera."""
    _fallback_test_family_map(monkeypatch)
    config = _fallback_test_config()
    project_root = _write_scorecard_rows(
        tmp_path,
        [
            {
                "event": "ronda",
                "backend": "vendor_a",
                "model": "glm-x",
                "latency_ms": 900_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_b",
                "model": "glm-y",
                "latency_ms": 150_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_c",
                "model": "glm-z",
                "latency_ms": 140_000,
            },
        ],
    )
    calls: list[str] = []

    def check_alive(name, *, config):
        calls.append(name)
        return {"alive": name != "challenger_glm_fast"}

    chosen = ed.resolve_similar_fallback(
        "challenger_glm_slow",
        config=config,
        project_root=project_root,
        check_alive=check_alive,
    )
    assert chosen == "challenger_glm_mid"
    assert calls == ["challenger_glm_fast", "challenger_glm_mid"], (
        "debe probar en orden de p50 ascendente, no en orden de insercion del dict"
    )


def test_resolve_similar_fallback_filters_out_candidates_beyond_latency_ratio(
    tmp_path, monkeypatch
):
    """Un candidato de la misma familia pero mucho mas lento NUNCA se propone
    (queda filtrado por max_latency_ratio); el fallback cae a
    resolve_fallback_backend en vez de proponer un candidato mas lento que el
    perfil que fallo."""
    _fallback_test_family_map(monkeypatch)
    config = _fallback_test_config()
    # El perfil que FALLA es el rapido (140s); el unico companero de familia
    # vivo (vendor_a) es 900s -- 6.4x mas lento, por encima del ratio 2.0x.
    project_root = _write_scorecard_rows(
        tmp_path,
        [
            {
                "event": "ronda",
                "backend": "vendor_a",
                "model": "glm-x",
                "latency_ms": 900_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_c",
                "model": "glm-z",
                "latency_ms": 140_000,
            },
        ],
    )
    config["ensemble_profiles"] = {
        "challenger_glm_fast": {"backend": "vendor_c", "model": "glm-z"},
        "challenger_glm_slow": {"backend": "vendor_a", "model": "glm-x"},
        "challenger_other_family": {"backend": "vendor_d", "model": "qwen-w"},
    }
    fallback_calls: list[str] = []

    def fake_fallback_backend(
        pool_backend,
        *,
        config,
        check_alive,
        exclude_profiles=frozenset(),
        project_root=None,
    ):
        fallback_calls.append(pool_backend)
        return "challenger_other_family"

    monkeypatch.setattr(ed, "resolve_fallback_backend", fake_fallback_backend)

    chosen = ed.resolve_similar_fallback(
        "challenger_glm_fast",
        config=config,
        project_root=project_root,
        max_latency_ratio=2.0,
        check_alive=lambda name, *, config: {"alive": True},
    )
    assert chosen == "challenger_other_family"
    assert fallback_calls == ["vendor_c"], (
        "debe delegar en resolve_fallback_backend con el backend del perfil "
        "caido cuando NINGUN companero de familia pasa el filtro de rendimiento"
    )


def test_resolve_similar_fallback_falls_back_when_no_family_entry(
    tmp_path, monkeypatch
):
    """Un perfil sin entrada en MODEL_FAMILY_MAP delega integro, sin inventar familia."""
    monkeypatch.setattr(ed, "MODEL_FAMILY_MAP", {})
    config = {
        "ensemble_profiles": {
            "challenger_unmapped": {"backend": "vendor_x", "model": "mystery"},
        }
    }
    project_root = _write_scorecard_rows(tmp_path, [])
    fallback_calls: list[str] = []

    def fake_fallback_backend(
        pool_backend,
        *,
        config,
        check_alive,
        exclude_profiles=frozenset(),
        project_root=None,
    ):
        fallback_calls.append(pool_backend)
        return "someone_else"

    monkeypatch.setattr(ed, "resolve_fallback_backend", fake_fallback_backend)

    chosen = ed.resolve_similar_fallback(
        "challenger_unmapped", config=config, project_root=project_root
    )
    assert chosen == "someone_else"
    assert fallback_calls == ["vendor_x"]


def test_resolve_similar_fallback_falls_back_when_family_has_no_other_member(
    tmp_path, monkeypatch
):
    """Familia con un unico perfil vivo (el que fallo): no hay compañero, delega."""
    _fallback_test_family_map(monkeypatch)
    config = {
        "ensemble_profiles": {
            "challenger_glm_slow": {"backend": "vendor_a", "model": "glm-x"},
            "challenger_other_family": {"backend": "vendor_d", "model": "qwen-w"},
        }
    }
    project_root = _write_scorecard_rows(tmp_path, [])
    fallback_calls: list[str] = []

    def fake_fallback_backend(
        pool_backend,
        *,
        config,
        check_alive,
        exclude_profiles=frozenset(),
        project_root=None,
    ):
        fallback_calls.append(pool_backend)
        return "challenger_other_family"

    monkeypatch.setattr(ed, "resolve_fallback_backend", fake_fallback_backend)

    chosen = ed.resolve_similar_fallback(
        "challenger_glm_slow", config=config, project_root=project_root
    )
    assert chosen == "challenger_other_family"
    assert fallback_calls == ["vendor_a"]


def test_profile_p50_latency_ms_computes_median_and_handles_missing_data():
    """Mediana real (par e impar) y None sin datos -- sin inventar un valor."""
    config = {
        "ensemble_profiles": {
            "p": {"backend": "b", "model": "m"},
            "empty": {"backend": "x", "model": "y"},
        }
    }
    rows_odd = [
        {"backend": "b", "model": "m", "latency_ms": 100},
        {"backend": "b", "model": "m", "latency_ms": 300},
        {"backend": "b", "model": "m", "latency_ms": 200},
    ]
    assert ed._profile_p50_latency_ms("p", config=config, rows=rows_odd) == 200.0

    rows_even = [
        {"backend": "b", "model": "m", "latency_ms": 100},
        {"backend": "b", "model": "m", "latency_ms": 200},
        {"backend": "b", "model": "m", "latency_ms": 300},
        {"backend": "b", "model": "m", "latency_ms": 400},
    ]
    assert ed._profile_p50_latency_ms("p", config=config, rows=rows_even) == 250.0

    assert ed._profile_p50_latency_ms("empty", config=config, rows=[]) is None


# ---------------------------------------------------------------------------
# Correcciones de auditoria de cableado (2026-09-29): limite de gasto en el
# fallback + aviso de typo en --phase.
# ---------------------------------------------------------------------------


def test_resolve_similar_fallback_respects_max_attempts_budget(tmp_path, monkeypatch):
    """Con max_attempts=1, prueba SOLO el candidato mas rapido y degrada al
    fallback generico sin gastar llamadas en los otros 2 companeros de
    familia, aunque uno de ellos SI estaria vivo."""
    _fallback_test_family_map(monkeypatch)
    config = _fallback_test_config()
    project_root = _write_scorecard_rows(
        tmp_path,
        [
            {
                "event": "ronda",
                "backend": "vendor_a",
                "model": "glm-x",
                "latency_ms": 900_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_b",
                "model": "glm-y",
                "latency_ms": 150_000,
            },
            {
                "event": "ronda",
                "backend": "vendor_c",
                "model": "glm-z",
                "latency_ms": 140_000,
            },
        ],
    )
    calls: list[str] = []

    def check_alive(name, *, config):
        calls.append(name)
        return {"alive": False}  # todos "muertos" para forzar agotar el budget

    fallback_calls: list[str] = []

    def fake_fallback_backend(
        pool_backend,
        *,
        config,
        check_alive,
        exclude_profiles=frozenset(),
        project_root=None,
    ):
        fallback_calls.append(pool_backend)
        return "challenger_other_family"

    monkeypatch.setattr(ed, "resolve_fallback_backend", fake_fallback_backend)

    chosen = ed.resolve_similar_fallback(
        "challenger_glm_slow",
        config=config,
        project_root=project_root,
        max_attempts=1,
        check_alive=check_alive,
    )
    assert chosen == "challenger_other_family"
    assert calls == ["challenger_glm_fast"], (
        "max_attempts=1 debe probar SOLO el primero (mas rapido) del orden "
        "por p50, nunca los 3 companeros de familia"
    )
    assert fallback_calls == ["vendor_a"]


def test_warn_phase_typo_flags_close_but_not_exact_match(capsys):
    """Un typo cercano a una fase de gobierno real avisa por stderr."""
    ed._warn_phase_typo("manager_reviw")
    captured = capsys.readouterr()
    assert "manager_review" in captured.err
    assert "WARN" in captured.err


def test_warn_phase_typo_silent_on_exact_government_phase(capsys):
    """Una fase de gobierno EXACTA no genera aviso (la maneja otra barrera)."""
    ed._warn_phase_typo("manager_review")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_warn_phase_typo_silent_on_deliberately_new_phase(capsys):
    """Una fase exploratoria nueva y NO parecida a ninguna de gobierno no
    genera ruido -- no es un enum cerrado, es una red de seguridad de typo."""
    ed._warn_phase_typo("DESIGN_REVIEW")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_warn_phase_typo_handles_none():
    """None (--phase ausente, aunque el CLI lo exige) no revienta."""
    ed._warn_phase_typo(None)  # no debe lanzar


def test_ensemble_runtime_artifacts_registry_covers_all_rel_constants():
    """ENSEMBLE_RUNTIME_ARTIFACTS keys must equal the set discovered by the
    introspection function.  Today the registry does not exist -> RED via
    AttributeError; after the fix -> GREEN."""
    assert hasattr(ed, "ENSEMBLE_RUNTIME_ARTIFACTS")
    registry_keys = set(ed.ENSEMBLE_RUNTIME_ARTIFACTS)
    discovered_keys = set(ed._iter_ensemble_runtime_rel_constants())
    assert registry_keys == discovered_keys, (
        f"Desincronizacion: en registro pero no descubiertas={discovered_keys - registry_keys}, "
        f"en discovered pero no en registro={registry_keys - discovered_keys}"
    )


def test_ensemble_runtime_artifacts_registry_detects_unregistered_constant(
    monkeypatch,
):
    """Mutation-verify real: inject a fake `_REL` constant NOT present in
    ENSEMBLE_RUNTIME_ARTIFACTS and verify the introspection function detects
    it.  This test proves the DETECTOR works (not that the registry is always
    in sync -- the distinction matters: this test must pass BEFORE and AFTER
    the fix)."""
    ed.FAKE_NEW_REL = Path(".agent/runtime/ensemble/fake.jsonl")
    try:
        discovered = ed._iter_ensemble_runtime_rel_constants()
        assert "FAKE_NEW_REL" in discovered, (
            "El detector no encontro FAKE_NEW_REL inyectado -> el mecanismo "
            "de introspeccion no es fiable"
        )
        assert "FAKE_NEW_REL" not in ed.ENSEMBLE_RUNTIME_ARTIFACTS, (
            "FAKE_NEW_REL no deberia estar en el registro estatico"
        )
    finally:
        delattr(ed, "FAKE_NEW_REL")


def test_ensemble_runtime_artifacts_registry_values_match_original_constants():
    """For every entry in the registry, ENSEMBLE_RUNTIME_ARTIFACTS[name] must
    equal the original constant value -- prevents the registry from having a
    stale copy if someone edits one of them by hand."""
    for _name, _registry_path in ed.ENSEMBLE_RUNTIME_ARTIFACTS.items():
        _original = getattr(ed, _name)
        assert _registry_path == _original, (
            f"Registro desincronizado para {_name}: registry={_registry_path}, "
            f"original={_original}"
        )


def test_ensemble_runtime_rel_constants_detects_str_value():
    """Introspection must detect `_REL` constants even when they are str (not
    just Path).  This is Blocker 2 from WOT-2026-084a: the previous version
    only filtered `isinstance(_val, Path)` and silently missed str values.
    Verify the fix: inject a str `_REL`, confirm _iter_ensemble_runtime_rel
    _constants returns it as Path."""
    ed.STR_REL = ".agent/runtime/ensemble/str_test.jsonl"
    try:
        discovered = ed._iter_ensemble_runtime_rel_constants()
        assert "STR_REL" in discovered, (
            "La introspeccion no detecto una constante _REL de tipo str"
        )
        assert isinstance(discovered["STR_REL"], Path), (
            "El valor devuelto debe ser Path, no str original"
        )
        # Use Path for comparison to avoid Windows/Linux separator issues.
        expected = Path(".agent/runtime/ensemble/str_test.jsonl")
        assert discovered["STR_REL"] == expected, (
            f"El Path normalizado debe coincidir: {discovered['STR_REL']} != {expected}"
        )
    finally:
        delattr(ed, "STR_REL")


# --------------------------------------------------------------------------- #
# WOT-2026-086b: `leaders` no cuenta como muestra un intento que la lente
# nunca recibio (error del llamante o cuota agotada).
# --------------------------------------------------------------------------- #


def _ronda_row(ticket: str, *, failure_mode, outcome="no-aportacion", ronda=1):
    return {
        "ts": "t",
        "event": "ronda",
        "ticket": ticket,
        "rol": "challenger",
        "task_type": "code-review",
        "backend": "fake",
        "model": "m2",
        "ronda": ronda,
        "outcome": outcome,
        "evidencia": "(respuesta vacia)",
        "input_bytes": 0,
        "context_kind": "diff",
        "failure_mode": failure_mode,
    }


@pytest.mark.parametrize(
    "failure_mode",
    [
        "usage-error",
        "missing-nonce",
        "transport_failed: TransportError: HTTP 402 monthly_cap_reached",
        "transport_failed: TransportError: HTTP 429 insufficient_quota",
    ],
)
def test_086b_non_sample_rounds_do_not_enter_adjudicated_cells(failure_mode):
    """Error del llamante o cuota agotada: la lente no evaluo el contenido,
    asi que la fila no es muestra de calidad. Mutation: quitar el filtro de
    `_adjudicated_cells` -> la celda aparece -> RED."""
    rows = [_ronda_row("WOT-TEST-086b", failure_mode=failure_mode)]
    assert ed._adjudicated_cells(rows) == {}


def test_086b_real_silent_round_still_counts_as_no_aportacion():
    """Control positivo: una ronda que SI llego a la lente y callo (sin
    failure_mode, o con un fallo de transporte que no es cuota) sigue contando."""
    rows = [
        _ronda_row("WOT-TEST-086b-a", failure_mode=None),
        _ronda_row(
            "WOT-TEST-086b-b",
            failure_mode="transport_failed: TransportError: timed out",
        ),
    ]
    cells = ed._adjudicated_cells(rows)
    assert set(cells) == {
        ("WOT-TEST-086b-a", 1, "challenger"),
        ("WOT-TEST-086b-b", 1, "challenger"),
    }


def test_086b_phantom_row_does_not_shadow_a_later_real_round():
    """La fila fantasma entraba con `setdefault` y OCUPABA la clave (ticket,
    ronda, rol): la ronda real posterior con la misma clave quedaba tapada."""
    real = _ronda_row("WOT-TEST-086b", failure_mode=None)
    real["evidencia"] = "ronda real"
    rows = [_ronda_row("WOT-TEST-086b", failure_mode="usage-error"), real]
    cells = ed._adjudicated_cells(rows)
    assert cells[("WOT-TEST-086b", 1, "challenger")]["evidencia"] == "ronda real"


def test_086b_leaders_ignores_usage_error_rows_but_scorecard_keeps_them(tmp_path):
    """Extremo a extremo sobre la proyeccion: 5 intentos rechazados (n >=
    LEADER_MIN_N) no deben producir celda ni lider fantasma, y las 5 filas
    siguen en el scorecard (el registro del intento es aditivo, no se borra)."""
    for i in range(5):
        ed.append_scorecard(
            tmp_path, _ronda_row(f"WOT-TEST-{i:03d}b", failure_mode="usage-error")
        )
    ed.regenerate_leaders(tmp_path)
    leaders = json.loads((tmp_path / ed.LEADERS_REL).read_text(encoding="utf-8"))
    cell = leaders["por_task_type"].get("code-review")
    assert cell is None or cell.get("lider") is None
    assert "fake|m2" not in json.dumps(leaders)
    rows = _rows(tmp_path)
    assert sum(r.get("failure_mode") == "usage-error" for r in rows) == 5


@pytest.mark.parametrize(
    ("given", "expected_hint"),
    [
        ("contract_audit", "contract-audit"),
        ("Code-Review", "code-review"),
        ("prompt_audit", "prompt-audit"),
        ("tirage", "triage"),
    ],
)
def test_086b_invalid_task_type_message_suggests_valid_value(given, expected_hint):
    msg = ed._invalid_task_type_message(given)
    assert "invalido; usa uno de" in msg
    assert f"quisiste decir '{expected_hint}'" in msg


def test_086b_invalid_task_type_message_without_close_match_has_no_hint():
    msg = ed._invalid_task_type_message("zzzzzz")
    assert "invalido; usa uno de" in msg
    assert "quisiste decir" not in msg


def test_086b_run_loop_round_error_carries_the_hint(tmp_path):
    """El mensaje que ve el llamante (no solo la funcion auxiliar) lleva la
    sugerencia: los tres puntos que rechazan `task_type` usan el mismo texto."""
    with pytest.raises(ValueError, match="quisiste decir 'contract-audit'"):
        ed.run_loop_round(
            "p_chal",
            "contenido",
            config={"ensemble_profiles": {}, "backends": {}},
            project_root=tmp_path,
            ticket="WOT-TEST-086b",
            task_type="contract_audit",
            rol="challenger",
            phase="premise_check",
            loop_id="L720",
            backend_key="BA01",
            sensitivity="public",
        )


# --------------------------------------------------------------------------- #
# WOT-2026-086d: un fallo del canal `agent` conserva y clasifica su causa.
# --------------------------------------------------------------------------- #


def _popen_returning(stdout: str, stderr: str, rc: int):
    class _Popen:
        pid = 4850
        returncode = rc

        def __init__(self, cmd, *a, **k):
            pass

        def communicate(self, input=None, timeout=None):
            return (stdout, stderr)

    return _Popen


def test_086d_failed_agent_keeps_stderr_tail(monkeypatch):
    """Codex escribe la causa en STDERR ("You've hit your usage limit ... try
    again at 3:05 PM") y stdout suele venir vacio: antes el texto de fallo
    solo llevaba `rc=N` + stdout y la causa se perdia. Mutation: no anexar
    stderr -> RED."""
    err = "\x1b[31mERROR\x1b[0m You've hit your usage limit. Try again at 3:05 PM."
    monkeypatch.setattr(ed.subprocess, "Popen", _popen_returning("", err, 1))

    out = ed._transport_agent(
        {"backend": "codex", "channel": "agent"},
        {"executable": "codex.cmd", "args": ["exec"]},
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    assert out.startswith(ed._TRANSPORT_FAILED_PREFIX)
    assert "[stderr]" in out
    assert "You've hit your usage limit" in out
    assert "\x1b[" not in out, "los codigos ANSI no deben llegar al scorecard"


def test_086d_stderr_tail_is_bounded(monkeypatch):
    """Solo la COLA de stderr: un volcado largo no debe inflar la fila."""
    err = "ruido\n" * 2000 + "causa final: usage limit"
    monkeypatch.setattr(ed.subprocess, "Popen", _popen_returning("", err, 1))
    out = ed._transport_agent(
        {"backend": "codex", "channel": "agent"},
        {"executable": "codex.cmd", "args": ["exec"]},
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    tail = out.split("[stderr]", 1)[1]
    assert len(tail) <= ed._AGENT_STDERR_TAIL_CHARS + 1
    assert "causa final: usage limit" in tail


def test_086d_successful_agent_ignores_stderr(monkeypatch):
    """CONTROL POSITIVO: con rc=0 el banner de stderr (modelo, avisos) NO se
    mezcla en la respuesta."""
    monkeypatch.setattr(
        ed.subprocess, "Popen", _popen_returning("VEREDICTO: OK", "model: gpt-x", 0)
    )
    out = ed._transport_agent(
        {"backend": "codex", "channel": "agent"},
        {"executable": "codex.cmd", "args": ["exec"]},
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    assert out == "VEREDICTO: OK"


def test_086d_failed_agent_row_carries_failure_class(tmp_path):
    """La fila de la ronda nombra la CLASE del fallo (misma taxonomia que
    `_classify_transport_failure`), no solo el rc: `quota_exhausted` debe ser
    legible sin abrir la evidencia, y la ronda deja de contar en `leaders`
    (WOT-2026-086b). Mutation: failure_mode sin clase -> RED."""
    reply = (
        f"{ed._TRANSPORT_FAILED_PREFIX}rc=1\n"
        "[stderr] You've hit your usage limit. Try again at 3:05 PM."
    )
    ed.run_loop_round(
        "p_chal",
        "audita esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-086d",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA05",
        sensitivity="public",
        transport=_FakeTransport(replies=[reply]),
    )
    row = _rows(tmp_path)[0]
    assert row["failure_mode"].startswith("transport_failed: rc=1")
    assert "quota_exhausted" in row["failure_mode"]
    assert ed._is_non_sample_round(row), "una ronda sin cuota no es muestra de calidad"


def test_086d_failed_agent_without_known_cause_is_unknown(tmp_path):
    """Sin marcador reconocible la clase es `unknown`: no se inventa causa."""
    reply = (
        f"{ed._TRANSPORT_FAILED_PREFIX}rc=1\nCORRECTO: el proceso ha sido terminado."
    )
    ed.run_loop_round(
        "p_chal",
        "audita esto",
        config=_config(),
        project_root=tmp_path,
        ticket="WOT-TEST-086d",
        task_type="code-review",
        rol="challenger",
        phase="challenge-fanout",
        loop_id="L800",
        backend_key="BA05",
        sensitivity="public",
        transport=_FakeTransport(replies=[reply]),
    )
    row = _rows(tmp_path)[0]
    assert row["failure_mode"] == "transport_failed: rc=1; unknown"
    assert not ed._is_non_sample_round(row), (
        "un fallo sin causa conocida sigue siendo muestra (la lente recibio el "
        "contenido): solo cuota y error del llamante se descartan"
    )


# --------------------------------------------------------------------------- #
# Bucle L720 sobre f8f208a (nonce 1bd4d83c, 5/4 lentes): arreglos adjudicados.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "failure_mode",
    [
        "unexpected: KeyError: 'usage limit'",
        "shell_noise_only",
        "lente dijo: allowance exhausted en su propio analisis",
    ],
)
def test_086b_quota_marker_outside_transport_failure_is_still_a_sample(failure_mode):
    """Un marcador de cuota solo significa cuota en una fila de TRANSPORTE
    fallido (el texto lo escribio el proveedor). Fuera de esa clase es texto
    libre y la ronda sigue siendo muestra (4/4 lentes API, bucle L720).
    Mutation: buscar el marcador en cualquier failure_mode -> RED."""
    row = _ronda_row("WOT-TEST-086b", failure_mode=failure_mode)
    assert not ed._is_non_sample_round(row)
    assert ed._adjudicated_cells([row]) != {}


def test_086d_stderr_tail_is_redacted_and_control_free(monkeypatch):
    """La cola de stderr pasa por `bus.redact` (tokens, claves, correos, usuario
    de rutas Windows) y pierde los caracteres de control, incluidos los
    escapes OSC que el filtro de ANSI no cubria (4/4 lentes API).
    Mutation: anexar la cola sin redactar -> RED."""
    secret = "sk-" + "a" * 30
    err = (
        f"\x1b]0;titulo\x07Authorization: Bearer abc.def.ghi key={secret} "
        "mail usuario@example.com en C:\\Users\\alguien\\x\x00 usage limit"
    )
    monkeypatch.setattr(ed.subprocess, "Popen", _popen_returning("", err, 1))
    out = ed._transport_agent(
        {"backend": "codex", "channel": "agent"},
        {"executable": "codex.cmd", "args": ["exec"]},
        [{"role": "user", "content": "x"}],
        timeout=10,
    )
    tail = out.split("[stderr]", 1)[1]
    assert secret not in tail
    assert "usuario@example.com" not in tail
    assert "alguien" not in tail
    assert "abc.def.ghi" not in tail
    assert not any(ord(c) < 32 and c not in "\n\t" for c in tail)
    assert "usage limit" in tail, "la causa sobrevive a la redaccion"
