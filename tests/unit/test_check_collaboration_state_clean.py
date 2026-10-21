#!/usr/bin/env python3
"""Tests de la barrera de reintroduccion WOT-2026-026x (c).

No son cosmeticos: cada caso MUTA el fixture (trackeado gitignored con `git add -f`,
linea activa en MANIFEST.distribute, o un directorio que no es repo) y exige que el
guard devuelva rc!=0 NOMBRANDO la superficie violada -- y rc=0 cuando se retira. La
mutacion define el contrato (AGENTS: "barrera verificada: un guard nuevo no cuenta
hasta demostrar que bloquea el fallo que promete bloquear").
"""

from __future__ import annotations

import subprocess
from pathlib import Path


try:  # ruta canonic del guard, igual que la costura de prepush_check.py
    from scripts.check_collaboration_state_clean import find_violations, main
except ImportError:  # pragma: no cover - fallback segun sys.path del runner
    from check_collaboration_state_clean import find_violations, main

COLLAB_DIR = ".agent/collaboration"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


def _init_repo(repo: Path) -> None:
    """Repo git con identidad y un commit inicial (para que `ls-files` funcione)."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")


def _write_manifest(repo: Path, body: str) -> None:
    (repo / "MANIFEST.distribute").write_text(body, encoding="utf-8")


def test_green_clean_repo(tmp_path: Path) -> None:
    """Motor limpio: 0 trackeados bajo collaboration y MANIFEST solo comentarios -> rc=0."""
    _init_repo(tmp_path)
    _write_manifest(
        tmp_path,
        "# Collaboration (retirado, WOT-2026-025b)\n# .agent/collaboration/work_plan.md\n",
    )
    assert find_violations(tmp_path) == {}
    assert main(["--motor-root", str(tmp_path)]) == 0


def test_m_track_reintroduction(tmp_path: Path) -> None:
    """Reintroducir tracking (gitignored + `git add -f`) -> VIOLACION nombrando el fichero."""
    _init_repo(tmp_path)
    _write_manifest(tmp_path, "# sin entradas activas\n")
    (tmp_path / ".gitignore").write_text(f"{COLLAB_DIR}/\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-m", "ignore collaboration")

    target = tmp_path / COLLAB_DIR / "work_plan.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# WOT-2026-022c estado operativo real\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", "--", f"{COLLAB_DIR}/work_plan.md")
    _git(tmp_path, "commit", "-m", "reintroducir estado operativo")

    violations = find_violations(tmp_path)
    assert "tracked" in violations
    assert any("work_plan.md" in rel for rel in violations["tracked"])
    assert main(["--motor-root", str(tmp_path)]) == 1


def test_m_declare_reintroduction(tmp_path: Path) -> None:
    """Re-declarar una ruta de collaboration como distribuible -> VIOLACION nombrandola."""
    _init_repo(tmp_path)
    _write_manifest(tmp_path, "scripts/x.py\n.agent/collaboration/work_plan.md\n")

    violations = find_violations(tmp_path)
    assert "declared" in violations
    assert ".agent/collaboration/work_plan.md" in violations["declared"]
    assert main(["--motor-root", str(tmp_path)]) == 1


def test_fail_closed_when_not_a_repo(tmp_path: Path) -> None:
    """Directorio que NO es repo -> no puede certificar -> VIOLACION (fail-closed, no verde vacuo)."""
    stray = tmp_path / "no_git"
    stray.mkdir(parents=True)
    _write_manifest(stray, "# nada\n")
    violations = find_violations(stray)
    assert violations.get("tracked"), "debia fail-closed ante raiz sin .git"
    assert main(["--motor-root", str(stray)]) == 1


def test_guard_is_wired_into_closeout() -> None:
    """Barrera CABLEADA (AGENTS 'barrera cableada'): prepush_check la importa estaticamente y la registra.

    check_guard_wiring exige un camino que corra solo; este test fija que el cable
    no se desconecta en un refactor. Raiz calculada desde el propio test (no existe
    fixture repo_root).
    """
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "scripts" / "prepush_check.py").read_text(encoding="utf-8")
    assert "from scripts.check_collaboration_state_clean import find_violations" in src
    assert "results.append(run_collaboration_state_clean_check" in src
