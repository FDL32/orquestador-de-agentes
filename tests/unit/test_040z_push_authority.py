"""Tests WOT-2026-040z: autoridad de sesion cableada en el push."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_push_authority as cpa


def _declare(root: Path, tipo: str) -> Path:
    session_dir = root / ".agent" / "runtime" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "session_type.json"
    path.write_text(
        json.dumps({"tipo": tipo, "declared_at": "2026-10-25T00:00:00+00:00"}),
        encoding="utf-8",
    )
    return path


MAIN_REFS = ["refs/heads/main"]
BRANCH_REFS = ["refs/heads/feature-x"]


def test_040z_diseno_push_a_main_bloquea(tmp_path: Path) -> None:
    """Mutation DoD: declarada diseno + push a main -> rc != 0 con
    instrucciones exactas de redeclaracion."""
    _declare(tmp_path, "diseno")
    rc = cpa.run(tmp_path, stdin_remote_refs=MAIN_REFS, env={})
    assert rc == 1


def test_040z_desarrollo_push_a_main_pasa(tmp_path: Path) -> None:
    _declare(tmp_path, "desarrollo")
    rc = cpa.run(tmp_path, stdin_remote_refs=MAIN_REFS, env={})
    assert rc == 0


def test_040z_sin_declaracion_es_warn_no_bloquea(tmp_path: Path) -> None:
    """Decision (b): sesiones legacy sin declaracion -> WARN rc 0."""
    rc = cpa.run(tmp_path, stdin_remote_refs=MAIN_REFS, env={})
    assert rc == 0


def test_040z_diseno_push_a_otra_rama_pasa(tmp_path: Path) -> None:
    _declare(tmp_path, "diseno")
    rc = cpa.run(tmp_path, stdin_remote_refs=BRANCH_REFS, env={})
    assert rc == 0


def test_040z_escape_design_push_reason_deja_rastro(tmp_path: Path) -> None:
    """Decision (a): escape = DESIGN_PUSH_REASON no vacio, registrado en el
    log auditable; motivo vacio NO escapa."""
    _declare(tmp_path, "diseno")
    log_path = tmp_path / ".agent" / "runtime" / "session" / "design_push_log.jsonl"

    rc = cpa.run(
        tmp_path, stdin_remote_refs=MAIN_REFS, env={"DESIGN_PUSH_REASON": "  "}
    )
    assert rc == 1  # motivo vacio: no escapa

    rc = cpa.run(
        tmp_path,
        stdin_remote_refs=MAIN_REFS,
        env={"DESIGN_PUSH_REASON": "hotfix coordinado con la orquestadora"},
    )
    assert rc == 0
    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["reason"] == "hotfix coordinado con la orquestadora"
    assert entries[-1]["mechanism"] == "DESIGN_PUSH_REASON"


def test_040z_fallback_premote_branch(tmp_path: Path) -> None:
    """Sin stdin (invocacion manual), PRE_COMMIT_REMOTE_BRANCH=main detecta."""
    _declare(tmp_path, "diseno")
    rc = cpa.run(
        tmp_path, stdin_remote_refs=[], env={"PRE_COMMIT_REMOTE_BRANCH": "main"}
    )
    assert rc == 1
    rc = cpa.run(
        tmp_path, stdin_remote_refs=[], env={"PRE_COMMIT_REMOTE_BRANCH": "feature-x"}
    )
    assert rc == 0


def test_040z_hook_wired_in_pre_commit_pre_push() -> None:
    """DoD minimo de la orquestadora: el hook esta en .pre-commit-config.yaml
    con stages: [pre-push], always_run y pass_filenames false."""
    config = (
        Path(__file__).resolve().parent.parent.parent / ".pre-commit-config.yaml"
    ).read_text(encoding="utf-8")
    assert "check-push-authority" in config
    assert "check_push_authority.py" in config
    entry_idx = config.index("- id: check-push-authority")
    block = config[entry_idx : entry_idx + 400]
    assert "stages: [pre-push]" in block
    assert "always_run: true" in block
    assert "pass_filenames: false" in block


def test_040z_bootstrap_declaration_writes_session_type(tmp_path: Path) -> None:
    """Decision (b): --session-type explicito escribe session_type.json con
    rastro; sin el flag no se escribe nada (nunca se adivina)."""
    from scripts import destination_context as dc

    dest = tmp_path / "dest"
    (dest / ".agent" / "config").mkdir(parents=True)
    (dest / ".agent" / "config" / "motor_destination_link.json").write_text(
        "{}", encoding="utf-8"
    )
    # Sin --session-type: no hay fichero.
    rc = dc.main(["--bootstrap", "--project-root", str(dest)])
    assert rc == 0
    assert not (dest / ".agent" / "runtime" / "session" / "session_type.json").exists()
    # Con --session-type: fichero con rastro.
    rc = dc.main(
        ["--bootstrap", "--project-root", str(dest), "--session-type", "desarrollo"]
    )
    assert rc == 0
    data = json.loads(
        (dest / ".agent" / "runtime" / "session" / "session_type.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["tipo"] == "desarrollo"
    assert "declared_at" in data and "declared_by" in data
    # Valor invalido: rechazado.
    rc = dc.main(
        ["--bootstrap", "--project-root", str(dest), "--session-type", "improvisado"]
    )
    assert rc == 1


def test_040z_r2_feature_main_y_tags_main_no_son_main(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): endswith('/main') era falso positivo;
    igualdad exacta con refs/heads/main."""
    _declare(tmp_path, "desarrollo")
    assert (
        cpa.run(
            tmp_path,
            stdin_remote_refs=["refs/heads/feature/main", "refs/tags/main"],
            env={},
        )
        == 0
    )


def test_040z_r2_fallback_stale_no_aplica_con_refs_en_stdin(
    tmp_path: Path,
) -> None:
    """Ronda 2 (hallazgo Codex): si el stdin trae refs, PRE_COMMIT_REMOTE_BRANCH
    stale no bloquea un push real a feature-x."""
    _declare(tmp_path, "diseno")
    rc = cpa.run(
        tmp_path,
        stdin_remote_refs=["refs/heads/feature-x"],
        env={"PRE_COMMIT_REMOTE_BRANCH": "main"},
    )
    assert rc == 0


def test_040z_r2_tipo_desconocido_o_ausente_bloquea(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): declaracion con tipo desconocido o ausente no
    es autoridad (fail-closed): pide redeclarar."""
    session_dir = tmp_path / ".agent" / "runtime" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "session_type.json"
    path.write_text(json.dumps({"tipo": "improvisado"}), encoding="utf-8")
    assert cpa.run(tmp_path, stdin_remote_refs=MAIN_REFS, env={}) == 1
    path.write_text(json.dumps({"declared_at": "t"}), encoding="utf-8")
    assert cpa.run(tmp_path, stdin_remote_refs=MAIN_REFS, env={}) == 1
