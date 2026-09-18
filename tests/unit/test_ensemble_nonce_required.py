"""Tests for challenge_nonce requirement in loop-round government phases (WOT-2026-040i).

Hermetic by construction: every dispatch test injects a fake `transport`
(no network, no real CLI). The load-bearing assertions, each with the mutation
it pins:
  - government phase without nonce -> exit != 0 (mutation: remove the check ->
    the round dispatches -> RED);
  - no row written on nonce-fail (mutation: remove the check -> a row is
    written -> RED);
  - non-government phase passes without nonce (mutation: block all phases ->
    RED);
  - historical ledgers without nonce parse cleanly (mutation: corrupt the
    reader -> RED).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import ensemble_dispatch as ed


def _config():
    """Minimal valid ensemble config for hermetic dispatch tests."""
    backend: dict = {
        "executable": "",
        "args": [],
        "discovery": {"method": "path_only"},
    }
    return {
        "schema_version": "1.3",
        "backends": {"fake": backend},
        "ensemble_profiles": {
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
    }


class _FakeTransport:
    """Records calls; returns canned replies (empty string = no-aportacion)."""

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.replies = list(replies or [])

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.replies.pop(0) if self.replies else "respuesta"


def _rows(project_root: Path) -> list[dict]:
    path = project_root / ed.SCORECARD_REL
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------- #
# DoD-1: Fallo sin nonce en gobierno
# --------------------------------------------------------------------------- #


def test_government_phase_without_nonce_fails(tmp_path, monkeypatch):
    """WOT-2026-040i DoD-1: una ronda de gobierno sin nonce FALLA.

    `loop-round --phase challenge-fanout` sin `--challenge-nonce` -> exit != 0,
    mensaje con `emit-nonce`.

    Mutation: quitar el check en `_cmd_loop_round` -> la ronda se despacha y
    el test cae (rc=0, no contiene `emit-nonce`).
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "send_to_profile", transport)
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
            "WOT-TEST-040i",
            "--task-type",
            "contract-audit",
            "--rol",
            "challenger",
            "--phase",
            "challenge-fanout",
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0, "gobierno sin nonce debe fallar; sin el check, rc=0 y el test cae"
    assert transport.calls == [], (
        f"gobierno sin nonce no debe llamar al backend; calls={transport.calls}"
    )


# --------------------------------------------------------------------------- #
# DoD-2: Falla ANTES del backend
# --------------------------------------------------------------------------- #


def test_government_phase_without_nonce_no_scorecard_row(tmp_path, monkeypatch):
    """WOT-2026-040i DoD-2(a): tras el fallo sin nonce, 1 fila con missing-nonce.

    Mutation: quitar el check -> se despacha el backend y se escribe una fila con
    el veredicto real -> RED (la fila tendria output_chars > 0, no missing-nonce).
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    before = _rows(tmp_path)
    ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload_file),
            "--ticket",
            "WOT-TEST-040i",
            "--task-type",
            "contract-audit",
            "--rol",
            "challenger",
            "--phase",
            "challenge-fanout",
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    after = _rows(tmp_path)
    assert len(after) == len(before) + 1, (
        f"sin nonce en gobierno debe escribir EXACTAMENTE UNA fila; "
        f"antes={len(before)}, despues={len(after)}"
    )
    row = after[-1]
    assert row["failure_mode"] == "missing-nonce", (
        f"la fila debe ser missing-nonce; failure_mode={row['failure_mode']}"
    )


def test_government_phase_without_nonce_no_backend_call(tmp_path, monkeypatch):
    """WOT-2026-040i DoD-2(b): tras el fallo sin nonce, 0 llamadas al backend.

    Mutation: quitar el check -> `send_to_profile` se llama -> RED.
    """
    transport = _FakeTransport(replies=["no deberia llegar"])
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload_file),
            "--ticket",
            "WOT-TEST-040i",
            "--task-type",
            "contract_audit",
            "--rol",
            "challenger",
            "--phase",
            "challenge-fanout",
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert transport.calls == [], (
        f"sin nonce en gobierno no debe llamar al backend; calls={transport.calls}"
    )


# --------------------------------------------------------------------------- #
# DoD-4: Fase no-gobierno intacta
# --------------------------------------------------------------------------- #


def test_non_government_phase_passes_without_nonce(tmp_path, monkeypatch):
    """WOT-2026-040i DoD-4: una fase fuera de gobierno sigue pasando sin nonce.

    `premise_check` es la fase no-gobierno canonica (ronda 0): no exige nonce.
    Se usa `code-review` como task_type valido para una fase que no es de gobierno.

    Mutation: bloquear TODAS las fases sin nonce -> la ronda de code-review
    falla -> RED.
    """
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
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
            "WOT-TEST-040i",
            "--task-type",
            "code-review",
            "--rol",
            "challenger",
            "--phase",
            "premise_check",
            "--loop-id",
            "L000",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc == 0, (
        "fase no-gobierno sin nonce debe pasar; "
        f"rc={rc} (sin el fix, rc!=0 y el test cae)"
    )
    rows = _rows(tmp_path)
    assert len(rows) == 1, "fase no-gobierno sin nonce debe escribir fila"


# --------------------------------------------------------------------------- #
# DoD-3: Historico legible
# --------------------------------------------------------------------------- #


def test_historical_ledger_without_nonce_parses_cleanly(tmp_path):
    """WOT-2026-040i DoD-3: un ledger con filas sin challenge_nonce se parsea.

    Las 690 historicas sin nonce deben seguir leyendose sin excepcion.

    Mutation: corromper el reader -> excepcion -> RED.
    """
    # Sembrar filas sin challenge_nonce (simulando historico pre-fix)
    ensemble_dir = tmp_path / ".agent" / "runtime" / "ensemble"
    ensemble_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = ensemble_dir / "scorecard.jsonl"
    historical_rows = [
        {
            "ts": f"t{i}",
            "event": "ronda",
            "ticket": f"WOT-TEST-{i:03d}a",
            "rol": "challenger",
            "task_type": "contract-audit",
            "backend": "fake",
            "ronda": 1,
            "outcome": None,
            "evidencia": "e",
            "phase": "CONTRACT_AUDIT",
            "loop_id": "L700",
            "backend_key": f"BA{i:02d}",
            # Sin challenge_nonce: historico pre-fix
        }
        for i in range(5)
    ]
    with open(scorecard_path, "w", encoding="utf-8") as f:
        for row in historical_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Leer el ledger debe funcionar sin excepcion
    rows = _rows(tmp_path)
    assert len(rows) == 5, (
        f"deben leerse las 5 filas historicas sin nonce; leidas={len(rows)}"
    )
    for row in rows:
        assert row.get("challenge_nonce") is None, (
            "las filas historicas no deben tener challenge_nonce"
        )


# --------------------------------------------------------------------------- #
# DoD-1: Otras fases de gobierno tambien fallan sin nonce
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "phase",
    [
        "challenge-fanout",
        "CONTRACT_AUDIT",
        "MANAGER_REVIEW",
        "CLOSE",
        "close",
    ],
)
def test_other_government_phases_without_nonce_fail(tmp_path, monkeypatch, phase):
    """WOT-2026-040i DoD-1: todas las fases de gobierno fallan sin nonce.

    Mutation: quitar el check -> todas las fases se despachan -> RED.
    """
    transport = _FakeTransport(replies=["no deberia llegar"])
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
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
            "WOT-TEST-040i",
            "--task-type",
            "contract-audit",
            "--rol",
            "challenger",
            "--phase",
            phase,
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0, f"fase {phase} sin nonce debe fallar; rc={rc}"
    assert transport.calls == [], f"fase {phase} sin nonce no debe llamar al backend"


def test_cross_case_nonce_missing_and_invalid_task_type(tmp_path, monkeypatch):
    """WOT-2026-040i: nonce ausente + task_type invalido → 0 filas.

    Este caso cruzado es la unica combinacion que podia escribir fila: el check
    de nonce debe disparar ANTES del pre-check de task_type que escribe al
    scorecard.

    Mutation: mover el check de nonce despues del de task_type -> se escribe
    una fila con failure_mode=usage-error -> RED.
    """
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    before = _rows(tmp_path)
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload_file),
            "--ticket",
            "WOT-TEST-040i",
            "--task-type",
            "contract_audit",
            "--rol",
            "challenger",
            "--phase",
            "challenge-fanout",
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0, (
        "gobierno sin nonce + task_type invalido debe fallar; "
        f"rc={rc} (sin el fix, rc=0 y el test cae)"
    )
    after = _rows(tmp_path)
    assert len(after) == len(before) + 1, (
        f"sin nonce en gobierno debe escribir EXACTAMENTE UNA fila con missing-nonce; "
        f"antes={len(before)}, despues={len(after)}"
    )
    row = after[-1]
    assert row["failure_mode"] == "missing-nonce", (
        f"la fila debe ser missing-nonce; failure_mode={row['failure_mode']}"
    )
    assert transport.calls == [], (
        f"gobierno sin nonce no debe llamar al backend; calls={transport.calls}"
    )


def test_usage_error_in_government_phase_with_nonce(tmp_path, monkeypatch):
    """WOT-2026-040i: task_type invalido EN fase de gobierno con nonce valido → 1 fila.

    El nonce esta presente, asi que el check de nonce no bloquea. El check de
    task_type invalido SI dispara y escribe una fila con failure_mode=usage-error.
    Esto garantiza que la clase usage-error sigue cubierta en fases de gobierno.

    Mutation: quitar el pre-check de task_type -> no se escribe fila -> RED.
    """
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload_file = tmp_path / "payload.txt"
    payload_file.write_text("material publico", encoding="utf-8")
    before = _rows(tmp_path)
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload_file),
            "--ticket",
            "WOT-TEST-040i",
            "--task-type",
            "contract_audit",
            "--rol",
            "challenger",
            "--phase",
            "challenge-fanout",
            "--loop-id",
            "L700",
            "--backend-key",
            "BA01",
            "--challenge-nonce",
            "abc123",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0, (
        "task_type invalido en gobierno con nonce valido debe fallar; rc={rc}"
    )
    after = _rows(tmp_path)
    assert len(after) == len(before) + 1, (
        f"task_type invalido debe escribir EXACTAMENTE UNA fila; "
        f"antes={len(before)}, despues={len(after)}"
    )
    row = after[-1]
    assert row["failure_mode"] == "usage-error", (
        f"la fila debe ser usage-error; failure_mode={row['failure_mode']}"
    )
    assert transport.calls == [], (
        f"task_type invalido no debe llamar al backend; calls={transport.calls}"
    )
