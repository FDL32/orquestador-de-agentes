"""WOT-2026-059c: `emit-nonce` FALLA CERRADO ante un --commit-sha que no resuelve.

Discriminating tests contra la ruta productiva REAL (`main()` del CLI), con un
git real como motor falso (patron `init_git_repo` de test_pre_handoff_guard) y
un destino-falso con `motor_destination_link.json`. NO se mockea el git-run de
la validacion: la mutacion (retirar la validacion / neutralizar el helper) debe
hacer caer el test de verdad.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

import ensemble_dispatch as ed  # noqa: E402


def _init_git_repo(repo_path: Path) -> None:
    """Motor falso: un repo git real con un commit (patron init_git_repo)."""
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("# Test Repo", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _link_motor(destino: Path, motor: Path) -> None:
    link_dir = destino / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}, ensure_ascii=False),
        encoding="utf-8",
    )


def _ledger(destino: Path) -> Path:
    return destino / ".agent" / "runtime" / "ensemble" / "emitted_nonces.jsonl"


def _emit(destino: Path, commit_sha: str) -> int:
    argv = [
        "emit-nonce",
        "--commit-sha",
        commit_sha,
        "--loop-id",
        "LX",
        "--issuer-backend-key",
        "BA01",
        "--project-root",
        str(destino),
    ]
    return ed.main(argv)


@pytest.fixture
def motor(tmp_path) -> Path:
    import shutil

    m = tmp_path / "fake_motor"
    _init_git_repo(m)
    yield m
    shutil.rmtree(m, ignore_errors=True)


@pytest.fixture
def destino(tmp_path, motor: Path) -> Path:
    d = tmp_path / "destino"
    d.mkdir(parents=True, exist_ok=True)
    _link_motor(d, motor)
    return d


def _read_ledger(destino: Path) -> list[dict]:
    p = _ledger(destino)
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rejects_unresolvable_sha(motor: Path, destino: Path) -> None:
    full = _git(motor, "rev-parse", "HEAD").stdout.strip()
    assert full, "premise: el motor falso tiene un commit"
    assert len(full) == 40
    before = len(_read_ledger(destino))
    rc = _emit(destino, "deadbee")
    assert rc == 1, "un sha que no resuelve debe FALLA CERRADO (exit != 0)"
    after = _read_ledger(destino)
    assert len(after) == before, (
        "ningun nonce puede entrar al ledger apuntando a un commit inexistente"
    )


def test_rejects_full_nonexistent_sha(motor: Path, destino: Path) -> None:
    bogus = "f" * 40
    assert _git(motor, "cat-file", "-e", bogus).returncode != 0
    rc = _emit(destino, bogus)
    assert rc == 1


def test_normalizes_abbreviated_sha(motor: Path, destino: Path) -> None:
    full = _git(motor, "rev-parse", "HEAD").stdout.strip()
    short = full[:10]
    rc = _emit(destino, short)
    assert rc == 0
    rows = _read_ledger(destino)
    assert rows, "premise: la emision escribio una fila"
    assert rows[-1]["commit_sha"] == full, (
        "un sha abreviado valido debe NORMALIZARSE a la forma canonica plena "
        "que el validador compara (no registrarse tal cual)"
    )


def test_full_sha_passes_unchanged(motor: Path, destino: Path) -> None:
    full = _git(motor, "rev-parse", "HEAD").stdout.strip()
    rc = _emit(destino, full)
    assert rc == 0
    rows = _read_ledger(destino)
    assert rows[-1]["commit_sha"] == full, (
        "control negativo (d): un sha canonico valido se registra exactamente igual"
    )


def test_rejects_object_that_is_not_a_commit(motor: Path, destino: Path) -> None:
    blob = _git(motor, "rev-parse", "HEAD:README.md").stdout.strip()
    assert blob, "premise: hay un blob"
    rc = _emit(destino, blob)
    assert rc == 1, "un objeto que NO es commit no puede registrarse como commit_sha"
    rows = _read_ledger(destino)
    assert not any(r.get("commit_sha") == blob for r in rows)


def test_rejects_without_motor_link(tmp_path, capsys) -> None:
    d = tmp_path / "no_link"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".agent").mkdir()
    rc = _emit(d, "deadbee")
    assert rc == 1
    err = capsys.readouterr().err
    assert "UNKNOWN" in err, "sin link el rechazo debe etiquetarse UNKNOWN, no INVALIDO"


def test_git_broken_reports_unknown_never_invalid(
    motor: Path, destino: Path, monkeypatch, capsys
) -> None:
    real_run = subprocess.run

    def _broken(argv, *a, **k):
        if "rev-parse" in argv:
            raise OSError("git no ejecutable (simulado)")
        return real_run(argv, *a, **k)

    monkeypatch.setattr(ed.subprocess, "run", _broken)
    rc = _emit(destino, "deadbee")
    assert rc == 1
    err = capsys.readouterr().err
    assert "UNKNOWN" in err, "un git que no arranca es DESCONOCIDO (WOT-2026-059b)"
    assert "no resuelve a un commit del motor" not in err, (
        "un fallo de infraestructura NUNCA debe reportarse como 'sha inexistente'"
    )
