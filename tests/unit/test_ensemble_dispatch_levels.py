from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ensemble_dispatch as ed


def _config(level: str = "premium", access: str = "cuenta_propia") -> dict:
    return {
        "backends": {"fake": {}},
        "ensemble_profiles": {
            "p": {
                "backend": "fake",
                "model": "m",
                "backend_key": "BA-X",
                "channel": "api",
            }
        },
        "ensemble_registry": {
            "backend_keys": {
                "BA-X": {
                    "status": "active",
                    "nivel": level,
                    "niveles": [level],
                    "acceso": access,
                }
            },
            "roles": {"U4": {"nivel": "medio"}, "U8": {"nivel": "alto"}},
            "uso_maximo_por_tipo": {"base": 1, "medio": 2, "alto": 3, "premium": 4},
        },
    }


def test_level_gate_rejects_without_authorized_override(tmp_path: Path):
    cfg = _config("alto")
    with pytest.raises(ed.DispatchBlockedError, match="nivel-no-autorizado"):
        ed.evaluate_level_gate(
            "p", config=cfg, phase="MANAGER_REVIEW", project_root=tmp_path
        )


def test_close_uses_u8_and_common_ceiling_source(tmp_path):
    cfg = _config("alto")
    collaboration = tmp_path / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    (collaboration / "FICHA_T.md").write_text("nivel_lentes: alto\n", encoding="utf-8")
    result = ed.evaluate_level_gate(
        "p", config=cfg, phase="CLOSE", project_root=tmp_path, ticket="T"
    )
    assert result["uso"] == "U8"
    assert result["techo"] == 3


def test_u8_without_high_lens_metadata_falls_back_to_u4(tmp_path):
    cfg = _config("alto")
    collaboration = tmp_path / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    (collaboration / "FICHA_T.md").write_text("nivel_lentes: medio\n", encoding="utf-8")
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.evaluate_level_gate(
            "p", config=cfg, phase="CLOSE", project_root=tmp_path, ticket="T"
        )


def test_u4_allows_ba05_style_multi_level_key_without_request(tmp_path):
    cfg = _config("alto")
    cfg["ensemble_registry"]["backend_keys"]["BA-X"]["niveles"] = ["medio", "alto"]
    cfg["ensemble_registry"]["backend_keys"]["BA-X"]["nivel"] = "alto"
    result = ed.evaluate_level_gate(
        "p", config=cfg, phase="MANAGER_REVIEW", project_root=tmp_path
    )
    assert result["nivel_clave"] == "medio"


def test_inactive_key_is_unknown_and_rejected_even_if_it_declares_medium():
    cfg = _config("medio")
    cfg["ensemble_registry"]["backend_keys"]["BA-X"]["status"] = "deprecated"
    with pytest.raises(ed.LevelGateError, match="clave-inactiva"):
        ed.evaluate_level_gate("p", config=cfg, phase="MANAGER_REVIEW")


def _real_config():
    return json.loads(
        (
            Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
        ).read_text(encoding="utf-8")
    )


def test_real_registry_ba05_uses_d3_and_common_ceiling():
    cfg = _real_config()
    result = ed.evaluate_level_gate(
        "challenger_codex", config=cfg, phase="MANAGER_REVIEW"
    )
    assert result["nivel_clave"] == "medio"
    assert (
        result["techo"]
        == cfg["ensemble_registry"]["uso_maximo_por_tipo"][result["nivel_max_uso"]]
    )


@pytest.mark.parametrize(
    "profile",
    ["challenger_claude_haiku_api", "challenger_claude_sonnet_api"],
    ids=["ba250", "ba251"],
)
def test_externo_pago_real_keys_rejected_even_with_request(profile):
    """t3-d05 (2 de 3 rechazos): claves reales BA250/BA251 con peticion valida."""
    with pytest.raises(ed.LevelGateError, match="acceso-externo-pago"):
        ed.evaluate_level_gate(
            profile,
            config=_real_config(),
            phase="MANAGER_REVIEW",
            peticion_usuario="12345678-1234-4234-8234-123456789012",
        )


def test_real_registry_ceiling_ignores_backend_specific_usage_field():
    cfg = _real_config()
    cfg["ensemble_registry"]["backend_keys"]["BA05"]["uso_maximo"] = 1
    result = ed.evaluate_level_gate(
        "challenger_codex", config=cfg, phase="MANAGER_REVIEW"
    )
    assert (
        result["techo"]
        == cfg["ensemble_registry"]["uso_maximo_por_tipo"]["medio"]
        == 7000
    )


def test_send_to_profile_always_gates_and_preserves_policy_privacy_order():
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.send_to_profile(
            "p",
            [{"role": "user", "content": "x"}],
            config=_config("premium"),
            sensitivity="public",
            transport=lambda *_args: "unreachable",
        )
    assert (
        ed.send_to_profile(
            "p",
            [{"role": "user", "content": "x"}],
            config=_config("medio"),
            sensitivity="public",
            transport=lambda *_args: "ok",
        )
        == "ok"
    )


def test_smoke_profile_inherits_level_rejection_from_send_to_profile():
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.smoke_profile(
            "p",
            config=_config("premium"),
            transport=lambda *_args: "unreachable",
        )


def test_externo_pago_rejects_even_with_request(tmp_path):
    with pytest.raises(ed.DispatchBlockedError, match="acceso-externo-pago"):
        ed.evaluate_level_gate(
            "p",
            config=_config("medio", "externo_pago"),
            phase="MANAGER_REVIEW",
            project_root=tmp_path,
            peticion_usuario="12345678-1234-4234-8234-123456789012",
        )


def test_stall_receipt_rejects_sanctioned_projection(tmp_path, monkeypatch):
    """t3-d04 (recibo 1 de 2): proyeccion URGENTE -> gasto-sancionado rc 2."""
    ops = tmp_path / "ops"
    ops.mkdir()
    monkeypatch.setenv("FLIGHT_OPS_DIR", str(ops))
    (ops / "stall_state.json").write_text(
        json.dumps({"nan_receipt": {"proyeccion": {"nivel": "URGENTE"}}}),
        encoding="utf-8",
    )
    with pytest.raises(ed.DispatchBlockedError, match="gasto-sancionado"):
        ed.evaluate_level_gate(
            "p", config=_config("medio"), phase="MANAGER_REVIEW", project_root=tmp_path
        )


def test_stall_receipt_allows_clean_and_keeps_provenance(tmp_path, monkeypatch):
    """t3-d04 (recibo 2 de 2): recibo limpio permite y conserva procedencia."""
    ops = tmp_path / "ops"
    ops.mkdir()
    monkeypatch.setenv("FLIGHT_OPS_DIR", str(ops))
    (ops / "stall_state.json").write_text(
        json.dumps(
            {
                "nan_receipt": {
                    "nivel": "medio",
                    "uso": 1,
                    "autorizacion": "ok",
                    "procedencia": ["tmp"],
                    "peticion_usuario": None,
                    "proyeccion": {"nivel": None},
                }
            }
        ),
        encoding="utf-8",
    )
    result = ed.evaluate_level_gate(
        "p", config=_config("medio"), phase="MANAGER_REVIEW", project_root=tmp_path
    )
    assert result["procedencia_stall"] == ["tmp"]


def test_cli_smoke_over_maximum_returns_rc_2_and_revalidation_instruction(
    monkeypatch, tmp_path, capsys
):
    """La ruta productiva ``main`` convierte el veto de nivel en rc 2."""
    monkeypatch.setattr(ed, "load_motor_config", _real_config)
    rc = ed.main(
        [
            "smoke",
            "--profile",
            "challenger_claude_sonnet_api",
            "--project-root",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr()
    text = output.out + output.err
    assert rc == 2
    assert "acceso-externo-pago" in text or "nivel-no-autorizado" in text
    assert "--peticion-store-path" in text


def test_cli_loop_round_over_maximum_returns_rc_2_and_revalidation_instruction(
    monkeypatch, tmp_path, capsys
):
    """``loop-round`` comparte el gate y su rc con la entrada ``smoke``."""
    monkeypatch.setattr(ed, "load_motor_config", _real_config)
    content = tmp_path / "content.txt"
    content.write_text("contenido publico", encoding="utf-8")
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "challenger_claude_sonnet_api",
            "--content-file",
            str(content),
            "--ticket",
            "WOT-2026-221c",
            "--task-type",
            "prose",
            "--rol",
            "challenger",
            "--phase",
            "DESIGN_REVIEW",
            "--loop-id",
            "L-221C",
            "--backend-key",
            "BA251",
            "--project-root",
            str(tmp_path),
            "--data-sensitivity",
            "public",
        ]
    )
    output = capsys.readouterr()
    text = output.out + output.err
    assert rc == 2
    assert "acceso-externo-pago" in text or "nivel-no-autorizado" in text
    assert "--peticion-store-path" in text


def test_cli_smoke_within_maximum_is_not_rejected_by_level_gate(
    monkeypatch, tmp_path, capsys
):
    """Un perfil medio pasa el gate aunque el smoke no encuentre un modelo."""
    monkeypatch.setattr(ed, "load_motor_config", _real_config)
    rc = ed.main(
        [
            "smoke",
            "--profile",
            "challenger_codex",
            "--project-root",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr()
    text = output.out + output.err
    assert rc != 2
    assert "nivel-no-autorizado" not in text
    assert "acceso-externo-pago" not in text


CHAIN_MESSAGE_ID = "77777777-7777-4777-8777-777777777777"
CHAIN_ANCHOR_ID = "88888888-8888-4888-8888-888888888888"
CHAIN_TEXT = "AUTORIZO el relevo sintetico ticket -> p hasta 2099-01-01T00:00:00+00:00"


def _level_record(*, expires_at=None, created_at=None, text=None):
    now = datetime.now(timezone.utc).replace(microsecond=123000)
    created = created_at or now
    expires = expires_at or (created + timedelta(hours=1)).isoformat()
    literal = text or (
        f"AUTORIZO el relevo sintetico ticket -> p cuando el saliente llegue a "
        f"330k de contexto, hasta {expires}"
    )
    return {
        "successors": ["ticket", "p"],
        "trigger_context_tokens": 330_000,
        "expires_at": expires,
        "literal_text": literal,
        "message_id": CHAIN_MESSAGE_ID,
        "text_sha256": hashlib.sha256(literal.encode("utf-8")).hexdigest(),
        "max_duration_hours": 12,
        "created_at": created.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def _level_store(path: Path, *, text=CHAIN_TEXT, created_at="2026-11-23T08:00:00.000Z"):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE orchestration_v2_projection_messages (
          message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT,
          node_id TEXT, role TEXT NOT NULL, streaming INTEGER NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE orchestration_v2_projection_threads (
          thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
          default_provider TEXT NOT NULL, runtime_mode TEXT NOT NULL,
          interaction_mode TEXT NOT NULL, active_provider_thread_id TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
          deleted_at TEXT, payload_json TEXT NOT NULL, provider_instance_id TEXT
        );
        """
    )
    anchor_thread = "11111111-1111-4111-8111-111111111111"
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            anchor_thread,
            "project",
            "title",
            "provider",
            "default",
            "default",
            None,
            "2026-11-23T00:00:00Z",
            "2026-11-23T00:00:00Z",
            None,
            None,
            "{}",
            None,
        ),
    )
    for message_id, role, message_text in (
        (CHAIN_ANCHOR_ID, "assistant", "anchor"),
        (CHAIN_MESSAGE_ID, "user", text),
    ):
        payload = json.dumps(
            {
                "id": message_id,
                "threadId": anchor_thread,
                "role": role,
                "text": message_text,
                "createdBy": "user" if role == "user" else "agent",
                "creationSource": "web" if role == "user" else "provider",
                "streaming": False,
                "createdAt": "2026-11-23T00:00:00.000Z"
                if message_id == CHAIN_ANCHOR_ID
                else created_at,
                "updatedAt": "2026-11-23T00:00:00.000Z"
                if message_id == CHAIN_ANCHOR_ID
                else created_at,
            }
        )
        connection.execute(
            "INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?,?,?,?)",
            (
                message_id,
                anchor_thread,
                "run",
                "node",
                role,
                0,
                "2026-11-23T00:00:00.000Z"
                if message_id == CHAIN_ANCHOR_ID
                else created_at,
                "2026-11-23T00:00:00.000Z"
                if message_id == CHAIN_ANCHOR_ID
                else created_at,
                payload,
            ),
        )
    connection.commit()
    connection.close()


def _authorized_level_environment(
    tmp_path: Path, monkeypatch, *, record=None, text=None
):
    flight = tmp_path / "flight"
    flight.mkdir()
    record = record or _level_record(text=text)
    (flight / "autorizacion_cadena.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    store = tmp_path / "state.sqlite"
    _level_store(
        store,
        text=text if text is not None else record["literal_text"],
        created_at=record["created_at"],
    )
    monkeypatch.setenv("FLIGHT_DIR", str(flight))
    return store


def test_level_gate_real_authorization_returns_receipt_without_monkeypatch(
    monkeypatch, tmp_path
):
    """La autorizada pasa por revalidacion y consume solo el ledger temporal."""
    store = _authorized_level_environment(tmp_path, monkeypatch)
    result = ed.evaluate_level_gate(
        "p",
        config=_config("alto"),
        phase="MANAGER_REVIEW",
        peticion_usuario=CHAIN_MESSAGE_ID,
        peticion_store_path=store,
        peticion_anchor=CHAIN_ANCHOR_ID,
    )
    assert result["nivel_gate_version"] == ed.LEVEL_GATE_VERSION
    assert result["peticion"] == CHAIN_MESSAGE_ID


@pytest.mark.parametrize("missing", ["flags", "flight"])
def test_level_gate_without_authorization_context_fails_closed(
    monkeypatch, tmp_path, missing
):
    """Sin store/ancla o sin ``FLIGHT_DIR`` la instruccion es reproducible."""
    if missing == "flags":
        kwargs = {"peticion_usuario": CHAIN_MESSAGE_ID}
    else:
        kwargs = {
            "peticion_usuario": CHAIN_MESSAGE_ID,
            "peticion_store_path": tmp_path / "missing.sqlite",
            "peticion_anchor": CHAIN_ANCHOR_ID,
        }
    with pytest.raises(ed.LevelGateError) as excinfo:
        ed.evaluate_level_gate(
            "p", config=_config("alto"), phase="MANAGER_REVIEW", **kwargs
        )
    message = str(excinfo.value)
    assert "--peticion-store-path" in message
    assert "--peticion-anchor" in message
    assert "FLIGHT_DIR" in message


def test_level_gate_real_authorization_rejects_expiry(monkeypatch, tmp_path):
    """La fecha literal caducada no puede autorizar un nivel superior."""
    now = datetime.now(timezone.utc).replace(microsecond=123000)
    record = _level_record(
        created_at=now - timedelta(hours=2),
        expires_at=(now - timedelta(hours=1)).isoformat(),
    )
    store = _authorized_level_environment(tmp_path, monkeypatch, record=record)
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.evaluate_level_gate(
            "p",
            config=_config("alto"),
            phase="MANAGER_REVIEW",
            peticion_usuario=CHAIN_MESSAGE_ID,
            peticion_store_path=store,
            peticion_anchor=CHAIN_ANCHOR_ID,
        )


def test_level_gate_real_authorization_rejects_mutated_text(monkeypatch, tmp_path):
    """El digest del mensaje real debe casar con el literal del registro."""
    record = _level_record()
    store = _authorized_level_environment(
        tmp_path, monkeypatch, record=record, text="texto mutado"
    )
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.evaluate_level_gate(
            "p",
            config=_config("alto"),
            phase="MANAGER_REVIEW",
            peticion_usuario=CHAIN_MESSAGE_ID,
            peticion_store_path=store,
            peticion_anchor=CHAIN_ANCHOR_ID,
        )


def test_level_gate_real_authorization_rejects_reuse(monkeypatch, tmp_path):
    """La segunda ronda con ``(messageId, step)`` ya consumido falla cerrado."""
    store = _authorized_level_environment(tmp_path, monkeypatch)
    kwargs = dict(
        config=_config("alto"),
        phase="MANAGER_REVIEW",
        peticion_usuario=CHAIN_MESSAGE_ID,
        peticion_store_path=store,
        peticion_anchor=CHAIN_ANCHOR_ID,
    )
    ed.evaluate_level_gate("p", **kwargs)
    with pytest.raises(ed.LevelGateError, match="nivel-no-autorizado"):
        ed.evaluate_level_gate("p", **kwargs)


def test_smoke_precheck_consumes_valid_request_once(monkeypatch, tmp_path):
    """Smoke consume una peticion valida una sola vez al despachar."""
    store = _authorized_level_environment(tmp_path, monkeypatch)
    args = ed.argparse.Namespace(
        profile="p",
        project_root=str(tmp_path),
        peticion_usuario=CHAIN_MESSAGE_ID,
        peticion_store_path=store,
        peticion_anchor=CHAIN_ANCHOR_ID,
        ignore_quarantine=False,
        timeout=15,
        max_tokens=64,
        include_agents=True,
        max_concurrent_per_provider=1,
    )
    rc = ed._cmd_smoke(
        args,
        _config("alto"),
        models_fetcher=lambda *_a, **_k: None,
        transport=lambda *_a: "PONG-019o",
    )
    ledger = tmp_path / "flight" / "autorizacion_cadena.ledger.jsonl"
    rows = ledger.read_text(encoding="utf-8").splitlines()
    assert rc == 0
    assert len(rows) == 1


def test_smoke_quarantine_does_not_consume_request(monkeypatch, tmp_path):
    """El skip por cuarentena no llega al punto de consumo del despacho."""
    store = _authorized_level_environment(tmp_path, monkeypatch)
    quarantine = tmp_path / ".agent" / "runtime" / "ensemble"
    quarantine.mkdir(parents=True)
    (quarantine / "backend_quarantine.json").write_text(
        json.dumps(
            {
                "by_backend": {},
                "by_profile": {
                    "p": {
                        "reason": "network_timeout",
                        "expires_at": (
                            datetime.now(timezone.utc) + timedelta(hours=1)
                        ).isoformat(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    args = ed.argparse.Namespace(
        profile="p",
        project_root=str(tmp_path),
        peticion_usuario=CHAIN_MESSAGE_ID,
        peticion_store_path=store,
        peticion_anchor=CHAIN_ANCHOR_ID,
        ignore_quarantine=False,
        timeout=15,
        max_tokens=64,
        include_agents=True,
        max_concurrent_per_provider=1,
    )
    rc = ed._cmd_smoke(
        args,
        _config("alto"),
        models_fetcher=lambda *_a, **_k: pytest.fail("el perfil estaba en cuarentena"),
        transport=lambda *_a: pytest.fail("el perfil estaba en cuarentena"),
    )
    ledger = tmp_path / "flight" / "autorizacion_cadena.ledger.jsonl"
    assert rc == 1
    assert not ledger.exists() or ledger.read_text(encoding="utf-8") == ""


def test_smoke_missing_model_does_not_consume_request(monkeypatch, tmp_path):
    """El skip por ausencia en ``/v1/models`` tampoco consume la peticion."""
    store = _authorized_level_environment(tmp_path, monkeypatch)
    args = ed.argparse.Namespace(
        profile="p",
        project_root=str(tmp_path),
        peticion_usuario=CHAIN_MESSAGE_ID,
        peticion_store_path=store,
        peticion_anchor=CHAIN_ANCHOR_ID,
        ignore_quarantine=False,
        timeout=15,
        max_tokens=64,
        include_agents=True,
        max_concurrent_per_provider=1,
    )
    rc = ed._cmd_smoke(
        args,
        _config("alto"),
        models_fetcher=lambda *_a, **_k: set(),
        transport=lambda *_a: pytest.fail("el modelo estaba ausente"),
    )
    ledger = tmp_path / "flight" / "autorizacion_cadena.ledger.jsonl"
    assert rc == 1
    assert not ledger.exists() or ledger.read_text(encoding="utf-8") == ""
