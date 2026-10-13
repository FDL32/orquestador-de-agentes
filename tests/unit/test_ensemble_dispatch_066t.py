"""WOT-2026-066t: un `task_type` de gobierno exige el par nonce+sha VALIDO.

La barrera vive en `_validated_governance_pair`, invocada por `run_loop_round`
(la ruta comun que escribe `event: ronda`, CLI y Python directo por igual).
Dientes de cada asercion, con su mutation:

- gobierno sin par -> ValueError + CERO fila + CERO llamadas al backend
  (mutation: retirar la barrera -> hoy se escribe la fila y da rc=0 -> RED);
- par VALIDO -> fila escrita con sha40 normalizado (mutation: bloquear todo
  -> el control positivo cae -> RED);
- no-gobierno sin par -> fila escrita como hoy (CONTROL NEGATIVO, mutation:
  bloquear sin mirar `GOVERNANCE_TASK_TYPES` -> RED);
- nonce fabricado -> bloqueado NOMBRANDO el nonce, no `continue` mudo.

Fixtures realistas: el dominio positivo usa un git REAL como motor falso con
`motor_destination_link.json` (patron `test_ensemble_emit_nonce_guard`), asi
la resolucion del sha corre por la via productiva
(`_validated_motor_sha` -> `resolve_governed_commit_sha` -> `git rev-parse`),
no por un helper mockeado.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import ensemble_dispatch as ed


GOV_TASK_TYPES = ("contract-audit", "code-review", "prompt-audit", "adjudication")


def _config() -> dict:
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


def _make_git_repo_with_commit(root: Path, *, seed: str = "seed") -> tuple[Path, str]:
    """Repo git REAL en `root` con un commit; devuelve (repo, sha40 de HEAD)."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "seed.txt").write_text(seed, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", seed], check=True)
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return root, out.stdout.strip()


def _amend_second_commit(repo: Path, seed: str) -> str:
    """SEGUNDO commit real en el mismo motor; devuelve su sha40."""
    (repo / "seed.txt").write_text(seed, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", seed], check=True)
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _link_motor(dest: Path, motor: Path) -> None:
    """Escribe el motor_destination_link.json que `resolve_motor_root` lee."""
    cfg = dest / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )


def _governed_dest(tmp_path: Path) -> tuple[Path, str]:
    """Destino-falso enlazado a un motor git real; devuelve (dest, sha40)."""
    motor, sha40 = _make_git_repo_with_commit(tmp_path / "motor_066t")
    dest = tmp_path / "dest"
    dest.mkdir()
    _link_motor(dest, motor)
    return dest, sha40


def _round_kwargs(dest: Path, transport, **overrides) -> dict:
    kwargs = dict(
        config=_config(),
        project_root=dest,
        ticket="WOT-TEST-066t",
        task_type="contract-audit",
        rol="challenger",
        phase="fanout-dif",
        loop_id="L066T",
        backend_key="BA11",
        sensitivity="public",
        transport=transport,
    )
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------- #
# DoD: GOVERNANCE_TASK_TYPES definido UNA vez, con el censo exacto
# --------------------------------------------------------------------------- #


def test_governance_task_types_is_the_census_set_once():
    """El conjunto canonico es exactamente el del censo de la premisa
    (contract-audit 63, code-review 46, prompt-audit 7, adjudication 2 = 118).

    Mutation: cambiar un miembro o duplicar la definicion en otro sitio ->
    esta igualdad exacta cae. `exploracion` (WOT-2026-055o) NUNCA es de
    gobierno: sus filas declaran ausencia de ceremonia a proposito.
    """
    assert (
        frozenset({"contract-audit", "code-review", "prompt-audit", "adjudication"})
        == ed.GOVERNANCE_TASK_TYPES
    )
    assert ed.GOVERNANCE_TASK_TYPES <= ed.TASK_TYPES
    assert "exploracion" not in ed.GOVERNANCE_TASK_TYPES
    assert "triage" not in ed.GOVERNANCE_TASK_TYPES


# --------------------------------------------------------------------------- #
# DoD-1 + MUTATION: gobierno sin par -> BLOQUEA, cero fila, cero backend
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task_type", GOV_TASK_TYPES)
def test_gov_task_type_without_pair_blocks_without_row(tmp_path, task_type):
    """MUTATION pedida por la ficha: 'ronda de gobierno sin par -> hoy se
    escribe, con el fix NO'. Aqui se exige el NO: ValueError nombrando 066t,
    CERO filas en el scorecard y CERO llamadas al backend (no se gasta la
    ronda en un receipt que nace inauditable).
    """
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError, match="WOT-2026-066t"):
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            **_round_kwargs(tmp_path, transport, task_type=task_type),
        )
    assert not (tmp_path / ed.SCORECARD_REL).exists(), (
        "sin par no hay fila: ni siquiera el fichero debe crearse"
    )
    assert transport.calls == [], "el bloqueo llega ANTES de gastar la llamada"


@pytest.mark.parametrize(
    ("commit_sha", "challenge_nonce"),
    [
        (None, "N-solo-nonce"),
        ("abc123", None),
        ("", "N-nonce"),
        ("abc123", ""),
    ],
)
def test_gov_task_type_with_incomplete_pair_blocks(
    tmp_path, commit_sha, challenge_nonce
):
    """El PAR es lo exigido: una de las dos ausente o vacia sigue siendo
    sin par. El bloqueo debe disparar ANTES de resolver el sha (por eso
    `tmp_path` sin link de motor es suficiente: el camino muere antes de
    tocar git).
    """
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError, match="exige el par"):
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            **_round_kwargs(
                tmp_path,
                transport,
                commit_sha=commit_sha,
                challenge_nonce=challenge_nonce,
            ),
        )
    assert transport.calls == []
    assert not (tmp_path / ed.SCORECARD_REL).exists()


def test_cli_loop_round_gov_task_without_pair_blocks_no_row(tmp_path, monkeypatch):
    """La ficha mide que 88 de las 118 rondas sin par entraron via
    `loop-round` con fase NO de gobierno (040i no las veia). Este test fija
    la misma via CLI: rc != 0, CERO filas (ni siquiera la fila de traza
    missing-nonce de 040i: aqui no hay fase de gobierno, no hay rastro), y
    cero llamadas al backend.

    Mutation: dejar `--commit-sha`/`--challenge-nonce` opcionales sin barrera
    de task_type -> rc=0, 1 fila -> RED.
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    transport = _FakeTransport(replies=["respuesta"])
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload = tmp_path / "payload.txt"
    payload.write_text("material publico", encoding="utf-8")
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload),
            "--ticket",
            "WOT-TEST-066t",
            "--task-type",
            "code-review",
            "--rol",
            "challenger",
            "--phase",
            "premise_check",
            "--loop-id",
            "L066T",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0, f"gobierno sin par via loop-round debe bloquear; rc={rc}"
    assert transport.calls == [], "el bloqueo llega ANTES de gastar la llamada"
    assert _rows(tmp_path) == [], (
        "WOT-2026-066t BLOQUEA sin escribir la fila (NO WARN): cero filas"
    )


# --------------------------------------------------------------------------- #
# DoD-2 + control positivo: el par VALIDO escribe la fila con sha40
# --------------------------------------------------------------------------- #


def test_valid_pair_round_is_recorded_with_normalized_sha(tmp_path):
    """CONTROL POSITIVO (mutacion del DoD-1): con par valido la ronda de
    gobierno SI se escribe, igual que antes del fix. Ademas fija la
    normalizacion: una abreviatura acreditada deja sha40 en la fila, para
    que el join del lector (`check_loop_execution`, exactitud de sha40) no
    falle por formato.
    """
    dest, sha40 = _governed_dest(tmp_path)
    ed.emit_nonce(
        dest,
        commit_sha=sha40,
        loop_id="L066T",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-066t",
    )
    transport = _FakeTransport(replies=["VEREDICTO: APROBADO"])
    reply = ed.run_loop_round(
        "p_chal",
        "audita esto",
        **_round_kwargs(
            dest,
            transport,
            commit_sha=sha40[:10],
            challenge_nonce="N-066t",
        ),
    )
    assert reply == "VEREDICTO: APROBADO"
    assert len(transport.calls) == 1, "el par valido si gasta la llamada"
    rows = _rows(dest)
    assert len(rows) == 1, "la ronda con par valido se escribe"
    assert rows[0]["commit_sha"] == sha40, (
        f"la fila debe llevar el sha40 normalizado: {rows[0]['commit_sha']!r}"
    )
    assert rows[0]["challenge_nonce"] == "N-066t"


# --------------------------------------------------------------------------- #
# DoD-2: validez, no presencia -- los fabricados se NOMBRAN
# --------------------------------------------------------------------------- #


def test_fabricated_nonce_is_named_and_blocked(tmp_path):
    """Un nonce con buena forma pero AUSENTE del ledger es un nonce
    FABRICADO: se BLOQUEA NOMBRANDO el valor (prohibido el `continue`
    mudo) y no se escribe fila.
    """
    dest, sha40 = _governed_dest(tmp_path)
    ed.emit_nonce(
        dest,
        commit_sha=sha40,
        loop_id="L066T",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-REAL",
    )
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError) as excinfo:
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            **_round_kwargs(
                dest,
                transport,
                commit_sha=sha40,
                challenge_nonce="NO-FABRICADO-xyz",
            ),
        )
    message = str(excinfo.value)
    assert "NO-FABRICADO-xyz" in message, (
        f"el nonce fabricado debe ser NOMBRADO en el rechazo: {message}"
    )
    assert "FABRICADO" in message
    assert transport.calls == []
    assert _rows(dest) == []


def test_nonce_issued_for_other_sha_blocks_naming_both(tmp_path):
    """El par debe casar: un nonce REAL emitido contra OTRO commit no
    acredita esta ronda. Se nombran ambos shas (el de la emision y el de
    la ronda), porque 'el nonce no vale' sin decir contra que commit nacio
    es un autenticador que no se puede auto-servir.
    """
    motor, sha_a = _make_git_repo_with_commit(tmp_path / "motor_066t")
    sha_b = _amend_second_commit(motor, "seed-b")
    dest = tmp_path / "dest"
    dest.mkdir()
    _link_motor(dest, motor)
    ed.emit_nonce(
        dest,
        commit_sha=sha_a,
        loop_id="L066T",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-DE-OTRO-COMMIT",
    )
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError) as excinfo:
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            **_round_kwargs(
                dest,
                transport,
                commit_sha=sha_b,
                challenge_nonce="N-DE-OTRO-COMMIT",
            ),
        )
    message = str(excinfo.value)
    assert "fue emitido contra" in message
    assert sha_a in message and sha_b in message, (
        f"el error debe nombrar AMBOS shas: {message}"
    )
    assert transport.calls == []
    assert _rows(dest) == []


def test_future_emission_blocks(tmp_path, monkeypatch):
    """'emitido ANTES' es parte de la validez, no decoracion: una emision
    con `issued_before_ts` POSTERIOR a esta ronda (ledger alterado o reloj
    mentiroso) no es la ceremonia previa y se bloquea. Se simula por la via
    productiva (`emit_nonce` con el reloj parcheado), no a mano: el ledger
    lo escribe el propio `emit_nonce`.
    """
    dest, sha40 = _governed_dest(tmp_path)
    real_now = ed._now_iso

    def _future_now() -> str:
        return "2999-01-01T00:00:00+00:00"

    monkeypatch.setattr(ed, "_now_iso", _future_now)
    ed.emit_nonce(
        dest,
        commit_sha=sha40,
        loop_id="L066T",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce="N-FUTURO",
    )
    monkeypatch.setattr(ed, "_now_iso", real_now)
    transport = _FakeTransport(replies=["no deberia llegar"])
    with pytest.raises(ValueError, match="POSTERIOR"):
        ed.run_loop_round(
            "p_chal",
            "audita esto",
            **_round_kwargs(
                dest,
                transport,
                commit_sha=sha40,
                challenge_nonce="N-FUTURO",
            ),
        )
    assert transport.calls == []
    assert _rows(dest) == []


# --------------------------------------------------------------------------- #
# CONTROL NEGATIVO: task_type NO de gobierno sigue igual que hoy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task_type", ["triage", "prose", "code-gen", "translation"])
def test_non_governance_task_types_still_write_without_pair(tmp_path, task_type):
    """CONTROL NEGATIVO del DoD: un task_type fuera de
    `GOVERNANCE_TASK_TYPES` escribe su fila sin par, exactamente como hoy.

    Mutation: bloquear todas las rondas sin par (sin mirar el conjunto) ->
    estas rondas fallan -> RED.
    """
    transport = _FakeTransport(replies=["respuesta"])
    ed.run_loop_round(
        "p_chal",
        "revisa",
        **_round_kwargs(
            tmp_path,
            transport,
            task_type=task_type,
            phase="premise_check",
        ),
    )
    rows = _rows(tmp_path)
    assert len(rows) == 1, (
        f"task_type no-gobierno {task_type} sin par debe escribir como hoy; "
        f"filas={len(rows)}"
    )
    assert len(transport.calls) == 1


# --------------------------------------------------------------------------- #
# Frontera con 040i: la fase de gobierno sigue dejando su fila de traza
# --------------------------------------------------------------------------- #


def test_government_phase_trace_row_of_040i_is_untouched(tmp_path, monkeypatch):
    """La barrera de 066t NO reemplaza ni desordena la de 040i: una fase de
    gobierno sin nonce sigue bloqueando DESDE el wrapper CLI y dejando su
    fila de traza `missing-nonce` (registro de intento, excluida de muestra
    por WOT-2026-086b). Fija la precedencia: 040i primero, 066t despues,
    para que un refactor no mueva la barrera y pierda el rastro en silencio.

    Mutation: mover el gate de 066t al wrapper CLI antes del check de fase
    (o suprimir la traza de 040i) -> la fila missing-nonce desaparece -> RED.
    """
    monkeypatch.setattr(ed, "load_motor_config", lambda: _config())
    transport = _FakeTransport(replies=["no deberia llegar"])
    monkeypatch.setattr(ed, "send_to_profile", transport)
    payload = tmp_path / "payload.txt"
    payload.write_text("material publico", encoding="utf-8")
    rc = ed.main(
        [
            "loop-round",
            "--profile",
            "p_chal",
            "--content-file",
            str(payload),
            "--ticket",
            "WOT-TEST-066t",
            "--task-type",
            "contract-audit",
            "--rol",
            "challenger",
            "--phase",
            "CONTRACT_AUDIT",
            "--loop-id",
            "L066T",
            "--backend-key",
            "BA01",
            "--data-sensitivity",
            "public",
            "--project-root",
            str(tmp_path),
        ]
    )
    assert rc != 0
    rows = _rows(tmp_path)
    assert len(rows) == 1, "040i conserva SU fila de traza missing-nonce"
    assert rows[0]["failure_mode"] == "missing-nonce"
