from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts import hermes_build_context_bundle


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write_motor_fixture(root: Path) -> None:
    (root / "prompts").mkdir(parents=True)
    (root / "AGENTS.md").write_text(
        """# Agents

## Vocabulario canonico
repo_motor y repo_destino.

## CEM v0 - Contrato, Evidencia y Memoria
Evidencia antes que relato.

## Secretos y seguridad
No exponer secretos.

## Siguiente
Fin.
""",
        encoding="utf-8",
    )
    (root / "prompts" / "orchestrator_destination_bootstrap.md").write_text(
        "# Destination Bootstrap\n\nUsa AGENT_PROJECT_ROOT.\n", encoding="utf-8"
    )
    (root / "prompts" / "orchestrator_session_close_chat.md").write_text(
        "# Session Close\n\nEjecuta dry-run antes del cierre.\n", encoding="utf-8"
    )
    (root / "prompts" / "hermes_soul.md").write_text(
        "# Hermes Soul\n\nNo aceptes relato como evidencia.\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "motor"\nversion = "9.17.1"\n', encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")


def test_build_bundle_writes_versioned_hashed_artifacts(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    output = tmp_path / "hermes" / "uploads"
    soul = tmp_path / "hermes" / "soul.md"
    motor.mkdir()
    _write_motor_fixture(motor)

    manifest = hermes_build_context_bundle.build_bundle(
        motor,
        output,
        soul_output=soul,
        generated_at="2026-06-20T12:00:00+00:00",
    )

    context = (output / "01_motor_context.md").read_text(encoding="utf-8")
    closeout = (output / "30_closeout_checklist.md").read_text(encoding="utf-8")
    disk_manifest = json.loads(
        (output / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == disk_manifest
    assert manifest["motor_version"] == "v9.17.1"
    assert len(manifest["source_commit"]) == 40
    assert manifest["source_tree_dirty"] is False
    assert manifest["source_status"] == []
    assert "repo_motor y repo_destino" in context
    assert "Model B" not in context
    assert "Ejecuta dry-run" in closeout
    assert soul.read_text(encoding="utf-8").startswith("# Hermes Soul")
    for record in manifest["generated_files"][:2]:
        path = output / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_build_bundle_fails_when_required_section_is_missing(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    motor.mkdir()
    _write_motor_fixture(motor)
    (motor / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Required section not found"):
        hermes_build_context_bundle.build_bundle(motor, tmp_path / "out")
