"""Barrier/contract tests de WOT-2026-067m.

Superficie doble:
  - `scripts/archive_arranques.py`  -- clasifica por CITACION (DEC-067L-001), MUEVE
    los no citados a `_archive/` e indexa (DEC-067L-002).
  - `scripts/check_arranques_index.py` -- el guard que cuadra INDEX <-> disco en AMBAS
    direcciones; `archive()` lo invoca tras cada mudanza (defensa) y `prepush_check`
    lo cablea en el cierre.

Rojo de mutacion (DoD (h)): `test_archive_flow_enforces_index_consistency` se pone
ROJO si se retira la llamada al guard dentro de `archive()`: un `_archive/` con un
fichero sin fila dejaria de abortar y la mudanza quedaria sin indexar.

HERMETICIDAD (vector git): cada proyecto temporal hace `git init` en SU raiz y
`_init_repo` verifica que `git rev-parse --show-toplevel` resuelve a esa MISMA raiz.
Si el walk-up alcanzara el repo real, el test aborta -- no mide el arbol de la maquina.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, _ROOT / "scripts" / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses resuelve `cls.__module__` via sys.modules; sin registrarlo,
    # exec_module sobre un dataclass revienta con 'NoneType has no __dict__'.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


aa = _load("archive_arranques")
cai = _load("check_arranques_index")

_GIT = shutil.which("git") or "git"
_INDEX_EMPTY = "| Archivo | Fecha | SHA256 | Motivo |\n|---|---|---|---|\n"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    """`git init` en la raiz temporal + verifica que el toplevel es ESA raiz.

    La verificacion es el vector de hermeticidad: si un walk-up alcanzara el repo
    real, `rev-parse --show-toplevel` no devolveria `root` y el test pararia.
    """
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    probe = _git(root, "rev-parse", "--show-toplevel")
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve() == root.resolve(), (
        "walk-up de git alcanzo OTRO repo: el test NO es hermetico"
    )


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", ".")
    result = _git(root, "commit", "-q", "-m", message)
    assert result.returncode == 0, result.stderr


def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    arranques = tmp_path / "orchestrator_pipeline" / "arranques"
    arranques.mkdir(parents=True)
    for name, content in files.items():
        (arranques / name).write_text(content, encoding="utf-8")
    (tmp_path / ".agent" / "collaboration").mkdir(parents=True)
    return tmp_path


def _arranques(tmp_path: Path) -> Path:
    return tmp_path / "orchestrator_pipeline" / "arranques"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------------ hermeticidad
def test_git_toplevel_is_the_tmp_project(tmp_path):
    _make_project(tmp_path, {"ARRANQUE_x.md": "x\n"})
    _init_repo(tmp_path)
    top = _git(tmp_path, "rev-parse", "--show-toplevel").stdout.strip()
    assert Path(top).resolve() == tmp_path.resolve()


def test_dry_run_reports_denominator_without_moving(tmp_path):
    _make_project(tmp_path, {"ARRANQUE_a.md": "a\n", "ARRANQUE_b.md": "b\n"})
    (tmp_path / ".agent" / "collaboration" / "backlog.md").write_text(
        "cita ARRANQUE_a desde el backlog vivo\n", encoding="utf-8"
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, dry_run=True)

    assert report.denominator == 2
    assert report.cited == ["ARRANQUE_a.md"]
    assert report.uncited == ["ARRANQUE_b.md"]
    assert not report.moved
    assert (_arranques(tmp_path) / "ARRANQUE_a.md").exists()
    assert (_arranques(tmp_path) / "ARRANQUE_b.md").exists()
    assert not (_arranques(tmp_path) / "_archive").exists()


def test_cli_dry_run_publishes_denominator(tmp_path, capsys):
    _make_project(tmp_path, {"ARRANQUE_a.md": "a\n", "ARRANQUE_b.md": "b\n"})
    (tmp_path / ".agent" / "collaboration" / "backlog.md").write_text(
        "cita ARRANQUE_a\n", encoding="utf-8"
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    rc = aa.main(["--project-root", str(tmp_path), "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "denominador: 2" in out
    assert "CITADOS: 1" in out
    assert "NO CITADOS: 1" in out


def test_uncited_file_moves_with_identical_sha256(tmp_path):
    _make_project(tmp_path, {"ARRANQUE_libre.md": "contenido libre\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")
    root_file = _arranques(tmp_path) / "ARRANQUE_libre.md"
    before = _sha256(root_file)

    report = aa.archive(tmp_path)

    assert report.moved == ["ARRANQUE_libre.md"]
    assert not root_file.exists(), "el no citado debe DESAPARECER de la raiz"
    moved = _arranques(tmp_path) / "_archive" / "ARRANQUE_libre.md"
    assert moved.exists(), "el no citado debe APARECER en _archive/"
    assert _sha256(moved) == before, "el contenido debe ser byte-identico (sha256)"


def test_negative_control_commit_cited_file_is_not_moved(tmp_path):
    """Un fichero citado SOLO desde un mensaje de commit publicado NO se mueve.

    Es el caso que un lector distraido pierde: no aparece en `backlog.md`, solo en
    `git log`. Si la superficie de commits no se leyera, se moveria evidencia citada.
    """
    _make_project(tmp_path, {"ARRANQUE_referenciado.md": "evidencia\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")
    empty = _git(
        tmp_path,
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "chore: cita ARRANQUE_referenciado en el mensaje publicado",
    )
    assert empty.returncode == 0, empty.stderr

    report = aa.archive(tmp_path)

    assert "ARRANQUE_referenciado.md" in report.cited
    assert not report.moved
    assert (_arranques(tmp_path) / "ARRANQUE_referenciado.md").exists()
    assert not (_arranques(tmp_path) / "_archive" / "ARRANQUE_referenciado.md").exists()


def test_index_has_one_row_per_moved_file(tmp_path):
    files = {f"ARRANQUE_n{i}.md": f"{i}\n" for i in range(3)}
    _make_project(tmp_path, files)
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, today="2026-09-10")

    index = _arranques(tmp_path) / "_archive" / "INDEX.md"
    rows = cai.parse_index_filenames(index)
    assert len(rows) == 3, "una fila por fichero movido"
    assert set(rows) == set(report.moved)
    text = index.read_text(encoding="utf-8")
    assert text.count("2026-09-10") == 3, "cada fila lleva su fecha"
    assert text.count(aa.MOTIVO) == 3, "cada fila lleva su motivo"


def test_guard_flags_file_without_row(tmp_path):
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir(parents=True)
    (archive / "ARRANQUE_huerfano.md").write_text("x\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(_INDEX_EMPTY, encoding="utf-8")

    findings = cai.check_index_consistency(_arranques(tmp_path))

    assert len(findings) == 1
    assert "ARRANQUE_huerfano.md" in findings[0]
    assert "SIN fila" in findings[0]


def test_guard_flags_row_without_file(tmp_path):
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir(parents=True)
    (archive / "INDEX.md").write_text(
        _INDEX_EMPTY + "| ARRANQUE_fantasma.md | 2026-09-10 | aa | motivo |\n",
        encoding="utf-8",
    )

    findings = cai.check_index_consistency(_arranques(tmp_path))

    assert len(findings) == 1
    assert "ARRANQUE_fantasma.md" in findings[0]
    assert "ausente" in findings[0]


def test_guard_passes_when_index_matches_disk(tmp_path):
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir(parents=True)
    (archive / "ARRANQUE_ok.md").write_text("x\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(
        _INDEX_EMPTY + "| ARRANQUE_ok.md | 2026-09-10 | aa | motivo |\n",
        encoding="utf-8",
    )

    assert cai.check_index_consistency(_arranques(tmp_path)) == []


def test_guard_skips_when_no_archive(tmp_path):
    _arranques(tmp_path).mkdir(parents=True)
    assert cai.check_index_consistency(_arranques(tmp_path)) == []
    assert cai.main(["--project-root", str(tmp_path)]) == 0


def test_archive_flow_enforces_index_consistency(tmp_path):
    """Rojo con la llamada al guard retirada de `archive()`.

    El `_archive/` arranca con un fichero sin fila (inconsistente). `archive()`
    mueve el no citado, indexa y DESPUES invoca el guard; al no cuadrar, ABORTA.
    Si se retira esa invocacion, `archive()` retorna y este test se pone ROJO.
    """
    _make_project(tmp_path, {"ARRANQUE_libre.md": "y\n"})
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir()
    (archive / "ARRANQUE_huerfano.md").write_text("x\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(_INDEX_EMPTY, encoding="utf-8")
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    with pytest.raises(aa.ArchiveError):
        aa.archive(tmp_path)


# ------------------------------------------------------------------ seguridad de movimiento
def test_archive_refuses_to_overwrite_existing_history(tmp_path):
    _make_project(tmp_path, {"ARRANQUE_libre.md": "nuevo\n"})
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir()
    (archive / "ARRANQUE_libre.md").write_text("ya existia\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(_INDEX_EMPTY, encoding="utf-8")
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    with pytest.raises(aa.ArchiveError):
        aa.archive(tmp_path)
    # El historico NO se sobrescribe.
    assert (archive / "ARRANQUE_libre.md").read_text(encoding="utf-8") == "ya existia\n"
