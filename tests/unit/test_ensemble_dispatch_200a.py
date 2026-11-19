"""WOT-2026-200a: family safety gate before an ensemble lens is spent."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import ensemble_dispatch as ed
from scripts.flight import integrate_ticket as it


TICKET = "WOT-2026-199a"
NONCE = "N-200A"
FICHA_DECL = (
    "autor_modelo: codex|gpt-5.6-luna\nrevisor_modelo: opencode|nan/deepseek-v4-flash\n"
)
FICHA_PENDIENTE = "autor_modelo: PENDIENTE\nrevisor_modelo: PENDIENTE\n"


def _config() -> dict:
    backend = {
        "executable": "",
        "args": [],
        "discovery": {"method": "path_only"},
    }
    return {
        "schema_version": "1.3",
        "backends": {"kilo": backend, "codex": backend},
        "ensemble_profiles": {
            "challenger_kilo_deepseek_flash": {
                "backend": "kilo",
                "channel": "agent",
                "model": "nan/deepseek-v4-flash",
                "backend_key": "BA07",
                "data_sensitivity": "public",
                "write": False,
            },
            "challenger_kilo_qwen_flash": {
                "backend": "kilo",
                "channel": "agent",
                "model": "nan/qwen3.8-flash",
                "backend_key": "BA02",
                "data_sensitivity": "public",
                "write": False,
            },
            "challenger_kilo_glm_flash": {
                "backend": "kilo",
                "channel": "agent",
                "model": "nan/glm5.3-flash",
                "backend_key": "BA03",
                "data_sensitivity": "public",
                "write": False,
            },
            "challenger_codex": {
                "backend": "codex",
                "channel": "agent",
                "model": "gpt-5.6-luna",
                "backend_key": "BA05",
                "data_sensitivity": "public",
                "write": False,
            },
            "challenger_kilo_fuera_de_mapa": {
                "backend": "kilo",
                "channel": "agent",
                "model": "nan/modelo-fuera-del-mapa-200a",
                "backend_key": "BA99",
                "data_sensitivity": "public",
                "write": False,
            },
        },
    }


class _FakeTransport:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return "veredicto de la lente"


def _rows(dest: Path) -> list[dict]:
    path = dest / ed.SCORECARD_REL
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _file_sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@dataclass
class World:
    motor: Path
    dest: Path
    sha: str


def _world(tmp_path: Path, ficha: str | None = FICHA_DECL) -> World:
    motor = tmp_path / "motor"
    (motor / ".agent" / "rules" / "common").mkdir(parents=True)
    (motor / ".agent" / "rules" / "common" / "vuelo_pilares.md").write_text(
        "| Pilar | Regla | Estado |\n|---|---|---|\n| P33 | familias | RATIFICADA |\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(motor)], check=True)
    subprocess.run(["git", "-C", str(motor), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(motor), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(motor), "add", "."], check=True)
    subprocess.run(["git", "-C", str(motor), "commit", "-qm", "seed"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(motor), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dest = tmp_path / "dest"
    (dest / ".agent" / "collaboration").mkdir(parents=True)
    (dest / ".agent" / "config").mkdir(parents=True)
    (dest / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )
    if ficha is not None:
        (dest / ".agent" / "collaboration" / f"FICHA_{TICKET}.md").write_text(
            ficha, encoding="utf-8"
        )
    ed.emit_nonce(
        dest,
        commit_sha=sha,
        loop_id="L200A",
        issuer_role="orchestrator",
        issuer_backend_key="BA01",
        nonce=NONCE,
    )
    return World(motor, dest, sha)


def _argv(world: World, profile: str, backend_key: str, *extra: str) -> list[str]:
    payload = world.dest.parent / "payload.txt"
    payload.write_text("material publico", encoding="utf-8")
    return [
        "loop-round",
        "--profile",
        profile,
        "--content-file",
        str(payload),
        "--ticket",
        TICKET,
        "--task-type",
        "contract-audit",
        "--rol",
        "challenger",
        "--phase",
        "CONTRACT_AUDIT",
        "--loop-id",
        "L200A",
        "--backend-key",
        backend_key,
        "--data-sensitivity",
        "public",
        "--commit-sha",
        world.sha,
        "--challenge-nonce",
        NONCE,
        "--project-root",
        str(world.dest),
        *extra,
    ]


def _cli(monkeypatch, argv, transport, config=None):
    monkeypatch.setattr(ed, "load_motor_config", lambda: config or _config())
    monkeypatch.setattr(ed, "send_to_profile", transport)
    return ed.main(argv)


def test_m01_lente_de_la_familia_del_revisor_se_rechaza(tmp_path, monkeypatch, capsys):
    """M-01: a reviewer-family lens is blocked before transport and scoring."""
    world = _world(tmp_path)
    transport = _FakeTransport()
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            transport,
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "[BLOCKED]" in err and "comparte familia" in err and "revisor" in err
    assert transport.calls == [] and _rows(world.dest) == []


def test_m02_lente_de_la_familia_del_autor_se_rechaza(tmp_path, monkeypatch, capsys):
    """M-02: an author-family lens is blocked before transport and scoring."""
    world = _world(tmp_path)
    transport = _FakeTransport()
    assert _cli(monkeypatch, _argv(world, "challenger_codex", "BA05"), transport) == 1
    err = capsys.readouterr().err
    assert "[BLOCKED]" in err and "codex" in err and "autor" in err
    assert transport.calls == []


def test_m03_el_rechazo_ocurre_antes_de_gastar_cupo(tmp_path, monkeypatch, capsys):
    """M-03: a blocked lens changes neither scorecard nor nonce ledger."""
    world = _world(tmp_path)
    transport = _FakeTransport()
    score = world.dest / ed.SCORECARD_REL
    ledger = world.dest / ed.EMITTED_NONCES_REL
    before = (_file_sha(score), _file_sha(ledger))
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            transport,
        )
        == 1
    )
    assert (_file_sha(score), _file_sha(ledger)) == before
    assert transport.calls == []
    assert _rows(world.dest) == []


def test_m04_el_mensaje_nombra_lente_familia_y_rol(tmp_path, monkeypatch, capsys):
    """M-04: each block names the lens identity, family, and matched role."""
    for profile, key, words in (
        ("challenger_kilo_deepseek_flash", "BA07", ("BA07", "deepseek", "revisor")),
        ("challenger_codex", "BA05", ("codex", "autor")),
    ):
        world = _world(tmp_path / key)
        assert _cli(monkeypatch, _argv(world, profile, key), _FakeTransport()) == 1
        err = capsys.readouterr().err
        assert all(word in err for word in words)


def test_m05_lente_de_familia_distinta_pasa_sin_aviso(tmp_path, monkeypatch, capsys):
    """M-05 control: a distinct family is dispatched and recorded."""
    world = _world(tmp_path)
    transport = _FakeTransport()
    assert (
        _cli(monkeypatch, _argv(world, "challenger_kilo_qwen_flash", "BA02"), transport)
        == 0
    )
    assert len(_rows(world.dest)) == 1 and len(transport.calls) == 1
    assert "familia no verificable" not in capsys.readouterr().err


def test_m06_ficha_ausente_avisa_y_sigue(tmp_path, monkeypatch, capsys):
    """M-06: an absent ficha warns once and still dispatches."""
    world = _world(tmp_path, ficha=None)
    transport = _FakeTransport()
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            transport,
        )
        == 0
    )
    lines = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "familia no verificable" in line
    ]
    assert len(_rows(world.dest)) == 1 and len(transport.calls) == 1
    assert len(lines) == 1 and "ficha ausente" in lines[0]


def test_m07_declaracion_pendiente_avisa_y_sigue(tmp_path, monkeypatch, capsys):
    """M-07: pending declarations warn and do not block the round."""
    world = _world(tmp_path, ficha=FICHA_PENDIENTE)
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            _FakeTransport(),
        )
        == 0
    )
    assert (
        len(_rows(world.dest)) == 1
        and "familia no verificable" in capsys.readouterr().err
    )


def test_m08_lente_con_familia_sin_resolver_avisa_y_sigue(
    tmp_path, monkeypatch, capsys
):
    """M-08: an unmapped lens warns with its model and continues."""
    world = _world(tmp_path)
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_fuera_de_mapa", "BA99"),
            _FakeTransport(),
        )
        == 0
    )
    err = capsys.readouterr().err
    assert len(_rows(world.dest)) == 1 and "familia no verificable" in err
    assert "nan/modelo-fuera-del-mapa-200a" in err


def test_m09_solo_lo_verificado_bloquea_con_declaracion_parcial(
    tmp_path, monkeypatch, capsys
):
    """M-09: only the role with a resolved declaration participates in blocking."""
    world = _world(
        tmp_path, "autor_modelo: codex|gpt-5.6-luna\nrevisor_modelo: PENDIENTE\n"
    )
    assert (
        _cli(monkeypatch, _argv(world, "challenger_codex", "BA05"), _FakeTransport())
        == 1
    )
    assert "[BLOCKED]" in capsys.readouterr().err
    world = _world(
        tmp_path / "b",
        "autor_modelo: PENDIENTE\nrevisor_modelo: opencode|nan/deepseek-v4-flash\n",
    )
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_qwen_flash", "BA02"),
            _FakeTransport(),
        )
        == 0
    )
    assert (
        len(_rows(world.dest)) == 1
        and "familia no verificable" in capsys.readouterr().err
    )


def _escribe_evidencia(
    dest: Path, sha: str, backend: str, model: str, backend_key: str
) -> None:
    ledger = dest / ed.EMITTED_NONCES_REL
    event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    row = {
        "event": "ronda",
        "commit_sha": sha,
        "backend_key": backend_key,
        "backend": backend,
        "model": model,
        "challenge_nonce": NONCE,
        "ts": event["ts"],
        "output_chars": 100,
        "evidencia": "veredicto de la lente",
        "task_type": "contract-audit",
        "loop_id": "L200A",
    }
    path = dest / ed.SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_m10_el_veredicto_es_el_de_integrate_ticket(tmp_path, monkeypatch, capsys):
    """M-10: the live integrate_ticket family verdict is the oracle."""
    world_a = _world(tmp_path / "a")
    _escribe_evidencia(
        world_a.dest, world_a.sha, "kilo", "nan/deepseek-v4-flash", "BA07"
    )
    assert it.check_family(TICKET, world_a.sha, world_a.dest, world_a.motor)[0] == 1
    assert (
        _cli(
            monkeypatch,
            _argv(world_a, "challenger_kilo_deepseek_flash", "BA07"),
            _FakeTransport(),
        )
        == 1
    )
    world_b = _world(tmp_path / "b")
    _escribe_evidencia(world_b.dest, world_b.sha, "kilo", "nan/qwen3.8-flash", "BA02")
    assert it.check_family(TICKET, world_b.sha, world_b.dest, world_b.motor)[0] == 0
    assert (
        _cli(
            monkeypatch,
            _argv(world_b, "challenger_kilo_qwen_flash", "BA02"),
            _FakeTransport(),
        )
        == 0
    )
    monkeypatch.setitem(ed.MODEL_FAMILY_MAP, ("kilo", "nan/deepseek-v4-flash"), "qwen")
    assert it.check_family(TICKET, world_a.sha, world_a.dest, world_a.motor)[0] == 0
    assert (
        _cli(
            monkeypatch,
            _argv(world_a, "challenger_kilo_deepseek_flash", "BA07"),
            _FakeTransport(),
        )
        == 0
    )


def test_m11_el_override_reviewer_model_manda_sobre_la_ficha(
    tmp_path, monkeypatch, capsys
):
    """M-11: reviewer override controls a pending reviewer declaration."""
    world = _world(tmp_path / "a", FICHA_PENDIENTE)
    assert (
        _cli(
            monkeypatch,
            _argv(
                world,
                "challenger_kilo_deepseek_flash",
                "BA07",
                "--reviewer-model",
                "opencode|nan/deepseek-v4-flash",
            ),
            _FakeTransport(),
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "[BLOCKED]" in err and "revisor" in err
    world = _world(tmp_path / "b", FICHA_PENDIENTE)
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            _FakeTransport(),
        )
        == 0
    )
    assert "familia no verificable" in capsys.readouterr().err


def test_m12_el_override_author_model_manda_sobre_la_ficha(
    tmp_path, monkeypatch, capsys
):
    """M-12: author override controls a pending author declaration."""
    world = _world(tmp_path / "a", FICHA_PENDIENTE)
    assert (
        _cli(
            monkeypatch,
            _argv(
                world,
                "challenger_codex",
                "BA05",
                "--author-model",
                "codex|gpt-5.6-luna",
            ),
            _FakeTransport(),
        )
        == 1
    )
    assert "autor" in capsys.readouterr().err
    world = _world(tmp_path / "b", FICHA_PENDIENTE)
    assert (
        _cli(monkeypatch, _argv(world, "challenger_codex", "BA05"), _FakeTransport())
        == 0
    )
    assert (
        len(_rows(world.dest)) == 1
        and "familia no verificable" in capsys.readouterr().err
    )


def test_m13_un_override_mal_formado_es_error_de_uso_rc2(tmp_path, monkeypatch, capsys):
    """M-13: malformed override syntax is argparse usage error rc 2."""
    for flag in ("--reviewer-model", "--author-model"):
        world = _world(tmp_path / flag.strip("-"))
        with pytest.raises(SystemExit) as exc:
            _cli(
                monkeypatch,
                _argv(world, "challenger_kilo_qwen_flash", "BA02", flag, "sin-barra"),
                _FakeTransport(),
            )
        assert exc.value.code == 2
        assert "backend|model" in capsys.readouterr().err
        assert _rows(world.dest) == []


def test_m14_la_ruta_watchdog_por_subproceso_propaga_el_bloqueo(tmp_path):
    """M-14: watchdog child preserves the family block before privacy preflight."""
    world = _world(tmp_path)
    cmd = [
        sys.executable,
        str(Path(ed.__file__).resolve()),
        *_argv(
            world,
            "challenger_kilo_deepseek_flash",
            "BA07",
            "--watchdog-s",
            "150",
            "--data-sensitivity",
            "private",
        ),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=180, cwd=tmp_path
    )
    assert (
        result.returncode == 1
        and "[BLOCKED]" in result.stderr
        and "comparte familia" in result.stderr
    )
    assert _rows(world.dest) == []


def test_m15_los_flags_nuevos_llegan_al_hijo_del_watchdog(tmp_path):
    """M-15: watchdog forwards overrides, and absence reaches privacy preflight."""
    world = _world(tmp_path / "a", FICHA_PENDIENTE)
    base = _argv(
        world,
        "challenger_kilo_deepseek_flash",
        "BA07",
        "--watchdog-s",
        "150",
        "--data-sensitivity",
        "private",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(ed.__file__).resolve()),
            *base,
            "--reviewer-model",
            "opencode|nan/deepseek-v4-flash",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
    )
    assert (
        result.returncode == 1
        and "[BLOCKED]" in result.stderr
        and "revisor" in result.stderr
    )
    assert _rows(world.dest) == []
    world = _world(tmp_path / "b", FICHA_PENDIENTE)
    base = _argv(
        world,
        "challenger_kilo_deepseek_flash",
        "BA07",
        "--watchdog-s",
        "150",
        "--data-sensitivity",
        "private",
    )
    result = subprocess.run(
        [sys.executable, str(Path(ed.__file__).resolve()), *base],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
    )
    assert len(_rows(world.dest)) == 1 and _rows(world.dest)[0][
        "failure_mode"
    ].startswith("privacy_preflight_blocked")
    assert (
        "familia no verificable" in result.stderr
        and "comparte familia" not in result.stderr
    )


def test_m16_el_contrato_documenta_bloqueo_flags_y_regla():
    """M-16: the loop contract names the block, flags, and ficha declaration."""
    root = Path(__file__).resolve().parents[2]
    text = (root / "prompts" / "ensemble_loop.md").read_text(encoding="utf-8")
    for literal in ("[BLOCKED]", "--author-model", "--reviewer-model", "autor_modelo"):
        assert literal in text, f"falta literal contractual {literal}"


def test_m17_ficha_no_utf8_avisa_y_sigue(tmp_path, monkeypatch, capsys):
    """V1-D2: a non-UTF8 ficha is 'familia no verificable' (warn), not a crash."""
    world = _world(tmp_path)
    ficha = world.dest / ".agent" / "collaboration" / f"FICHA_{TICKET}.md"
    ficha.write_bytes(b"\xff\xfe\x00\x00basura no-utf8")
    transport = _FakeTransport()
    assert (
        _cli(
            monkeypatch,
            _argv(world, "challenger_kilo_deepseek_flash", "BA07"),
            transport,
        )
        == 0
    )
    err = capsys.readouterr().err
    assert len(_rows(world.dest)) == 1 and len(transport.calls) == 1
    assert "familia no verificable" in err and "ficha ilegible" in err
