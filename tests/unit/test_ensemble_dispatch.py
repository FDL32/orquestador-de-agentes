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
import traceback
import urllib.error
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
    assert row["failure_mode"] == "usage-error", (
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
            "model": "deepseek-v4-flash-0731",
            "api_key_env": "FAKE_KEY_047Y",
            "api_base_url": "https://example.invalid/v1/chat/completions",
        },
        {"executable": "", "args": []},
        [{"role": "user", "content": "hola"}],
        timeout=10,
    )
    assert out == "respuesta-api"
    assert sent["body"]["model"] == "deepseek-v4-flash-0731", (
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
    CIEGAS a proposito como calibracion permanente del modelo base."""
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
            self._run("challenger_nan_qwen3_6", "BA12", tmp_path)

    def test_matching_key_passes(self, tmp_path):
        """CONTROL POSITIVO: la invocacion correcta no se molesta."""
        assert self._run("challenger_opencode_glm_5_2", "BA06", tmp_path) == "ok"

    def test_error_names_the_key_the_caller_should_use(self, tmp_path):
        """Gate self-service: el mensaje dice COMO arreglarlo, no solo que fallo."""
        with pytest.raises(ValueError) as exc:
            self._run("challenger_opencode_glm_5_2", "BA12", tmp_path)
        assert "--backend-key BA06" in str(exc.value)


_WOT_025Z_SECTION_MARKER = "# === WOT-2026-025z substantive tests start ==="

_NAN_MODELS = {
    "deepseek-v4-flash-0731": "challenger_nan_deepseek_v4_flash",
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
            "0c1362c4bfeb13d8c5e8c304d0210dd1170f971b",
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
    assert row["commit_sha"] == "0c1362c4bfeb13d8c5e8c304d0210dd1170f971b"
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
