"""WOT-2026-202a: loop-round lens substitution inherits author/reviewer model family overrides."""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import ensemble_dispatch as ed


TICKET = "WOT-2026-202a"
NONCE = "N-202A"
FICHA_PENDIENTE = "autor_modelo: PENDIENTE\nrevisor_modelo: PENDIENTE\n"


def _config() -> dict:
    backend = {
        "executable": "",
        "args": [],
        "discovery": {"method": "path_only"},
    }
    return {
        "schema_version": "1.3",
        "backends": {
            "kilo": backend,
            "codex": backend,
            "opencode": backend,
            "nan_api": backend,
        },
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
            "challenger_opencode_glm_flash": {
                "backend": "opencode",
                "channel": "agent",
                "model": "opencode-go/glm-5.3-flash",
                "backend_key": "BA06",
                "data_sensitivity": "public",
                "write": False,
            },
            "challenger_nan_deepseek": {
                "backend": "nan_api",
                "channel": "agent",
                "model": "nan/deepseek-v4-flash",
                "backend_key": "BA12",
                "data_sensitivity": "public",
                "write": False,
            },
        },
        "ensemble_registry": {
            "roles": {"U4": {"nivel": "medio"}, "U8": {"nivel": "alto"}},
            "uso_maximo_por_tipo": {"medio": 7000, "alto": 7000},
            "backend_keys": {
                key: {"status": "active", "nivel": "medio"}
                for key in ("BA02", "BA03", "BA05", "BA06", "BA07", "BA12")
            },
        },
    }


class _FakeTransport:
    def __init__(self, failure_on: set[str] | None = None):
        self.calls: list[dict] = []
        self.failure_on = failure_on or set()

    def __call__(self, profile_name, messages, **kwargs):
        self.calls.append(
            {
                "profile_name": profile_name,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        if profile_name in self.failure_on:
            raise ed.TransportError(
                f"HTTPError | HTTP 524 | connection failure on {profile_name}",
                status=524,
                body="Gateway Timeout",
            )
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


@dataclass
class World:
    motor: Path
    dest: Path
    sha: str


def _world(tmp_path: Path, ficha: str | None = FICHA_PENDIENTE) -> World:
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


def test_d01_sustitucion_transporte_hereda_override_reviewer_model(
    tmp_path, monkeypatch, capsys
):
    """d-01: transport fallback inherits --reviewer-model override and blocks substitute."""
    world = _world(tmp_path / "d01", FICHA_PENDIENTE)
    argv = _argv(
        world,
        "challenger_kilo_qwen_flash",
        "BA02",
        "--reviewer-model",
        "opencode|nan/deepseek-v4-flash",
    )
    transport = _FakeTransport(failure_on={"challenger_kilo_qwen_flash"})
    monkeypatch.setattr(
        ed,
        "resolve_similar_fallback",
        lambda *a, **k: "challenger_kilo_deepseek_flash",
    )

    rc = _cli(monkeypatch, argv, transport)

    assert rc != 0
    err = capsys.readouterr().err
    assert "[BLOCKED]" in err
    assert "BA07" in err
    assert "deepseek" in err
    assert "revisor" in err


def test_d02_sustitucion_transporte_hereda_override_author_model(
    tmp_path, monkeypatch, capsys
):
    """d-02: transport fallback inherits --author-model override and blocks substitute."""
    world = _world(tmp_path / "d02", FICHA_PENDIENTE)
    argv = _argv(
        world,
        "challenger_kilo_qwen_flash",
        "BA02",
        "--author-model",
        "codex|gpt-5.6-luna",
    )
    transport = _FakeTransport(failure_on={"challenger_kilo_qwen_flash"})
    monkeypatch.setattr(
        ed, "resolve_similar_fallback", lambda *a, **k: "challenger_codex"
    )

    rc = _cli(monkeypatch, argv, transport)

    assert rc != 0
    err = capsys.readouterr().err
    assert "[BLOCKED]" in err
    assert "BA05" in err
    assert "codex" in err
    assert "autor" in err


@pytest.mark.parametrize(
    ("override_kw", "override_val", "expected_role"),
    [
        (
            "reviewer_model",
            "opencode|nan/deepseek-v4-flash",
            "revisor",
        ),
        (
            "author_model",
            "opencode|nan/deepseek-v4-flash",
            "autor",
        ),
    ],
)
def test_d03_sustitucion_sintesis_hereda_overrides_y_bloquea_sustituto(
    tmp_path, monkeypatch, override_kw, override_val, expected_role
):
    """d-03: synthesis nan-leader fallback inherits both overrides and blocks substitute."""
    world = _world(tmp_path / f"d03_{expected_role}", FICHA_PENDIENTE)
    config = _config()

    def _failing_transport(profile_name, messages, **kwargs):
        if profile_name == "challenger_opencode_glm_flash":
            raise RuntimeError("unexpected synthesis crash")
        return "veredicto sintetizado"

    monkeypatch.setattr(ed, "send_to_profile", _failing_transport)
    monkeypatch.setattr(
        ed,
        "_get_best_nan_for_task",
        lambda *a, **k: ("challenger_nan_deepseek", "lider"),
    )

    overrides = {override_kw: override_val}
    # Calling run_loop_round directly as declared in FICHA section 4 / d-03
    with pytest.raises(ed.DispatchBlockedError) as exc_info:
        ed.run_loop_round(
            profile_name="challenger_opencode_glm_flash",
            content="material publico",
            config=config,
            project_root=world.dest,
            ticket=TICKET,
            task_type="code-gen",
            rol="challenger",
            phase="close",
            loop_id="L200A",
            backend_key="BA06",
            sensitivity="public",
            ronda=0,
            context_kind="diff",
            transport=None,
            session_id="S1",
            commit_sha=world.sha,
            challenge_nonce=NONCE,
            _tried_profiles=frozenset(),
            **overrides,
        )

    err = str(exc_info.value)
    assert "BA12" in err or "deepseek" in err
    assert expected_role in err
    rows = _rows(world.dest)
    assert not any(r.get("backend_key") == "BA12" for r in rows)


def test_d04_rechazo_sustituto_no_gasta_cupo(tmp_path, monkeypatch, capsys):
    """d-04: rejected substitute does not spend budget (0 substitute rows, 1 transport call)."""
    world = _world(tmp_path / "d04", FICHA_PENDIENTE)
    argv = _argv(
        world,
        "challenger_kilo_qwen_flash",
        "BA02",
        "--reviewer-model",
        "opencode|nan/deepseek-v4-flash",
    )
    transport = _FakeTransport(failure_on={"challenger_kilo_qwen_flash"})
    monkeypatch.setattr(
        ed,
        "resolve_similar_fallback",
        lambda *a, **k: "challenger_kilo_deepseek_flash",
    )

    rc = _cli(monkeypatch, argv, transport)
    assert rc != 0

    rows = _rows(world.dest)
    assert len(rows) == 1
    assert rows[0]["backend_key"] == "BA02"
    assert not any(r["backend_key"] == "BA07" for r in rows)
    assert len(transport.calls) == 1
    assert transport.calls[0]["profile_name"] == "challenger_kilo_qwen_flash"


def test_d05_sustituto_de_familia_distinta_con_override_corre(
    tmp_path, monkeypatch, capsys
):
    """d-05: positive control - substitute of different family runs normally with override."""
    world = _world(tmp_path / "d05", FICHA_PENDIENTE)
    argv = _argv(
        world,
        "challenger_kilo_qwen_flash",
        "BA02",
        "--reviewer-model",
        "opencode|nan/deepseek-v4-flash",
    )
    transport = _FakeTransport(failure_on={"challenger_kilo_qwen_flash"})
    monkeypatch.setattr(
        ed, "resolve_similar_fallback", lambda *a, **k: "challenger_kilo_glm_flash"
    )

    rc = _cli(monkeypatch, argv, transport)
    assert rc == 0
    err = capsys.readouterr().err
    assert "[BLOCKED]" not in err

    rows = _rows(world.dest)
    assert len(rows) == 2
    assert rows[0]["backend_key"] == "BA02"
    assert rows[1]["backend_key"] == "BA03"
    assert len(transport.calls) == 2
    assert transport.calls[0]["profile_name"] == "challenger_kilo_qwen_flash"
    assert transport.calls[1]["profile_name"] == "challenger_kilo_glm_flash"


def test_d06_sin_overrides_con_ficha_pendiente_sustitucion_sigue_y_avisa(
    tmp_path, monkeypatch, capsys
):
    """d-06: positive control - without overrides and pending ficha, substitution proceeds and warns."""
    world = _world(tmp_path / "d06", FICHA_PENDIENTE)
    argv = _argv(
        world,
        "challenger_kilo_qwen_flash",
        "BA02",
    )
    transport = _FakeTransport(failure_on={"challenger_kilo_qwen_flash"})
    monkeypatch.setattr(
        ed,
        "resolve_similar_fallback",
        lambda *a, **k: "challenger_kilo_deepseek_flash",
    )

    rc = _cli(monkeypatch, argv, transport)
    assert rc == 0
    err = capsys.readouterr().err
    assert "[BLOCKED]" not in err
    assert "familia no verificable" in err

    rows = _rows(world.dest)
    assert len(rows) == 2
    assert rows[0]["backend_key"] == "BA02"
    assert rows[1]["backend_key"] == "BA07"


def test_d07_ninguna_llamada_a_run_loop_round_omite_author_y_reviewer_model():
    """d-07: static AST check ensures every call to run_loop_round in ensemble_dispatch passes overrides."""
    source_path = Path(ed.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    calls: list[tuple[int, dict[str, ast.AST]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "run_loop_round")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_loop_round"
            )
        ):
            kw_map = {kw.arg: kw.value for kw in node.keywords}
            calls.append((node.lineno, kw_map))

    # Sanity: at least _cmd_loop_round, _retry_with_similar_fallback, _retry_with_nan_leader_fallback
    assert len(calls) >= 3, (
        f"Expected at least 3 calls to run_loop_round, found {len(calls)}"
    )

    defective_calls = []
    for lineno, kw_map in calls:
        for required_kw in ("author_model", "reviewer_model"):
            if required_kw not in kw_map:
                defective_calls.append((lineno, f"missing keyword {required_kw}"))
            else:
                val = kw_map[required_kw]
                if isinstance(val, ast.Constant):
                    defective_calls.append(
                        (lineno, f"{required_kw} is constant literal {val.value!r}")
                    )
                elif not (
                    (isinstance(val, ast.Name) and val.id == required_kw)
                    or (
                        isinstance(val, ast.Call)
                        and isinstance(val.func, ast.Name)
                        and val.func.id == "getattr"
                    )
                ):
                    defective_calls.append(
                        (
                            lineno,
                            f"{required_kw} value is neither Name({required_kw}) nor getattr",
                        )
                    )

    assert not defective_calls, (
        f"Calls to run_loop_round with defective overrides: {defective_calls}"
    )
