from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import check_publication_gate as gate


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_repo(
    base: Path, name: str, email: str = "123+bot@users.noreply.github.com"
) -> Path:
    repo = base / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", email)
    _git(repo, "config", "user.name", "Bot")
    (repo / "README.md").write_text("# limpio\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    return repo


def test_clean_repo_is_listo(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "proyecto_limpio")
    report = gate.run_gate(repo, [], ["usuarioinexistente9x"], [])
    assert report["verdict"] == "LISTO"
    assert (
        gate.main(["--repo-root", str(repo), "--pii-term", "usuarioinexistente9x"]) == 0
    )


def test_copia_folder_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "proyecto - copia")
    report = gate.run_gate(repo, [], ["x9z"], [])
    assert report["verdict"] == "BLOCKED"
    assert any(c["check"] == "name" and not c["ok"] for c in report["checks"])


def test_dirty_tree_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "proyecto_sucio")
    (repo / "wip.txt").write_text("sin commitear\n", encoding="utf-8")
    report = gate.run_gate(repo, [], ["x9z"], [])
    assert any(c["check"] == "tree_clean" and not c["ok"] for c in report["checks"])
    assert report["verdict"] == "BLOCKED"


def test_personal_metadata_email_blocks_and_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    """El check de metadata es el UNICO que caza autores/committers (classify
    solo escanea blobs). MUTATION: sin el check, el gate daria falso verde."""
    repo = _make_repo(tmp_path, "proyecto_meta", email="persona@dominioprivado.es")
    report = gate.run_gate(repo, [], ["x9z"], [])
    meta = next(c for c in report["checks"] if c["check"] == "metadata")
    assert not meta["ok"] and "persona@dominioprivado.es" in meta["evidence"]
    assert report["verdict"] == "BLOCKED"

    # MUTATION: neutralizar el check -> falso verde (demuestra la barrera)
    monkeypatch.setattr(
        gate,
        "check_metadata",
        lambda repo, allow: {"check": "metadata", "ok": True, "evidence": []},
    )
    mutated = gate.run_gate(repo, [], ["x9z"], [])
    assert mutated["verdict"] == "LISTO"


def test_dirty_sibling_blocks_unidad(tmp_path: Path) -> None:
    """El caso UNIDAD original de 016m: repo limpio + hermano con PII -> BLOCKED."""
    repo = _make_repo(tmp_path, "principal")
    hermano = _make_repo(tmp_path, "hermano")
    (hermano / "leak.md").write_text(
        "ruta: C:\\Users\\pepito\\Dropbox\\datos\n", encoding="utf-8"
    )
    _git(hermano, "add", "leak.md")
    _git(hermano, "commit", "-m", "leak en el hermano")

    report = gate.run_gate(repo, [hermano], ["pepito"], [])
    assert report["verdict"] == "BLOCKED"
    assert report["siblings"][0]["ok"] is False
    # el principal por si solo esta limpio
    solo = gate.run_gate(repo, [], ["pepito"], [])
    assert solo["verdict"] == "LISTO"


def test_loose_pattern_catches_slug_variant(tmp_path: Path) -> None:
    """El patron laxo caza la forma slug Users-term que un scan de rutas no ve."""
    repo = _make_repo(tmp_path, "proyecto_slug")
    (repo / "log.md").write_text(
        "sesion: c--Users-pepito-Proyectos\n", encoding="utf-8"
    )
    _git(repo, "add", "log.md")
    _git(repo, "commit", "-m", "slug")
    report = gate.run_gate(repo, [], ["pepito"], [])
    loose = next(c for c in report["checks"] if c["check"] == "loose_pattern")
    assert not loose["ok"]
    assert report["verdict"] == "BLOCKED"


def test_no_hardcoded_username_in_source() -> None:
    """DoD #4: el motor no lleva el username del autor hardcodeado."""
    src = Path(gate.__file__).read_text(encoding="utf-8")
    assert "fdl" not in src.lower().replace("default_pii_terms", "")
