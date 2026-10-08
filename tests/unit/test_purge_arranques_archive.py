"""Tests de WOT-2026-089p: purga por TTL de `arranques/_archive/`.

HERMETICIDAD (vector git): cada proyecto temporal hace `git init` en SU raiz, igual
que `test_archive_arranques.py` -- sin ello, el censo de re-citacion (`git log --all`)
podria alcanzar el repo real.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, _ROOT / "scripts" / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pa = _load("purge_arranques_archive")
cai = _load("check_arranques_index")

_GIT = shutil_which = __import__("shutil").which("git") or "git"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    probe = _git(root, "rev-parse", "--show-toplevel")
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve() == root.resolve()


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", ".")
    result = _git(root, "commit", "-q", "-m", message)
    assert result.returncode == 0, result.stderr


def _make_archive_project(
    tmp_path: Path, index_rows: list[tuple[str, str, str, str]], files: set[str]
) -> Path:
    """Proyecto con `_archive/INDEX.md` + ficheros en disco + backlog VIVO vacio.

    `index_rows` es (nombre, fecha, sha, motivo). `files` son los nombres que
    existen de verdad en `_archive/` (puede diferir de `index_rows` para
    construir escenarios concretos).
    """
    archive = tmp_path / "orchestrator_pipeline" / "arranques" / "_archive"
    archive.mkdir(parents=True)
    for name in files:
        (archive / name).write_text("contenido\n", encoding="utf-8")
    header = "# Indice\n\n| Archivo | Fecha | SHA256 | Motivo |\n|---|---|---|---|\n"
    body = "".join(f"| {n} | {d} | {s} | {m} |\n" for n, d, s, m in index_rows)
    (archive / "INDEX.md").write_text(header + body, encoding="utf-8")
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "backlog.md").write_text("", encoding="utf-8")
    return tmp_path


def _old_date(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_file_older_than_ttl_without_recitation_is_deleted(tmp_path):
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [("ARRANQUE_viejo.md", old, "aa", "no citado ...")],
        {"ARRANQUE_viejo.md"},
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == ["ARRANQUE_viejo.md"]
    archive = tmp_path / "orchestrator_pipeline" / "arranques" / "_archive"
    assert not (archive / "ARRANQUE_viejo.md").exists()
    index_text = (archive / "INDEX.md").read_text(encoding="utf-8")
    assert "PURGADO" in index_text
    assert old in index_text, "la fecha de mudanza original se conserva en la fila"


def test_file_within_ttl_is_not_touched(tmp_path):
    recent = _old_date(10)
    _make_archive_project(
        tmp_path,
        [("ARRANQUE_reciente.md", recent, "aa", "no citado ...")],
        {"ARRANQUE_reciente.md"},
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.denominator == 0
    archive = tmp_path / "orchestrator_pipeline" / "arranques" / "_archive"
    assert (archive / "ARRANQUE_reciente.md").exists()


def test_recited_file_past_ttl_is_protected(tmp_path):
    """Rojo de WOT-2026-089p: un fichero viejo RE-CITADO desde entonces no se purga.

    Mismo principio que DEC-067L-001 aplicado a la segunda mitad del ciclo de
    vida: si alguien lo cito despues de archivarlo, borrar perderia evidencia
    citada igual que moverlo lo haria en `archive_arranques.py`.
    """
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [("ARRANQUE_recitado.md", old, "aa", "no citado ...")],
        {"ARRANQUE_recitado.md"},
    )
    (tmp_path / ".agent" / "collaboration" / "backlog.md").write_text(
        "cita ARRANQUE_recitado desde el backlog vivo\n", encoding="utf-8"
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.recited == ["ARRANQUE_recitado.md"]
    archive = tmp_path / "orchestrator_pipeline" / "arranques" / "_archive"
    assert (archive / "ARRANQUE_recitado.md").exists()


def test_dry_run_reports_without_deleting(tmp_path):
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [("ARRANQUE_viejo.md", old, "aa", "no citado ...")],
        {"ARRANQUE_viejo.md"},
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90, dry_run=True)

    assert report.denominator == 1
    assert report.purged == []
    archive = tmp_path / "orchestrator_pipeline" / "arranques" / "_archive"
    assert (archive / "ARRANQUE_viejo.md").exists(), "dry-run no debe borrar nada"


def test_already_purged_row_is_idempotent(tmp_path):
    """Una fila ya marcada PURGADO no se re-procesa ni rompe el guard."""
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [
            (
                "ARRANQUE_ya_purgado.md",
                old,
                "aa",
                f"PURGADO {_old_date(1)}: motivo original",
            )
        ],
        set(),  # el fichero YA no existe en disco
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.already_purged == ["ARRANQUE_ya_purgado.md"]


def test_guard_does_not_flag_purged_row_as_orphan(tmp_path):
    """check_index_consistency NO debe fallar sobre una fila PURGADO sin fichero.

    Sin la excepcion (`_purged_filenames`), esta fila se reportaria como "nombra
    un fichero ausente de _archive/" -- un falso positivo sobre la purga misma.
    """
    old = _old_date(200)
    arranques_dir = (
        _make_archive_project(
            tmp_path,
            [
                (
                    "ARRANQUE_purgado.md",
                    old,
                    "aa",
                    f"PURGADO {_old_date(1)}: motivo original",
                )
            ],
            set(),
        )
        / "orchestrator_pipeline"
        / "arranques"
    )

    findings = cai.check_index_consistency(arranques_dir)

    assert findings == []


def test_guard_still_flags_genuine_orphan_row(tmp_path):
    """Control negativo: una fila SIN el prefijo PURGADO sigue siendo hallazgo real."""
    old = _old_date(200)
    arranques_dir = (
        _make_archive_project(
            tmp_path,
            [("ARRANQUE_fantasma.md", old, "aa", "no citado ... (sin purgar)")],
            set(),  # tampoco existe, pero su motivo NO dice PURGADO
        )
        / "orchestrator_pipeline"
        / "arranques"
    )

    findings = cai.check_index_consistency(arranques_dir)

    assert len(findings) == 1
    assert "ARRANQUE_fantasma.md" in findings[0]


def test_cli_json_output_is_single_line(tmp_path, capsys):
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [("ARRANQUE_viejo.md", old, "aa", "no citado ...")],
        {"ARRANQUE_viejo.md"},
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    rc = pa.main(["--project-root", str(tmp_path), "--ttl-days", "90", "--json"])
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert len(out.splitlines()) == 1
    import json

    payload = json.loads(out)
    assert payload["purged"] == ["ARRANQUE_viejo.md"]


def test_path_traversal_row_is_rejected_not_purged(tmp_path):
    """Rojo de WOT-2026-089p (hallazgo Codex, MANAGER_REVIEW): una fila con `../`
    en el nombre NUNCA se borra ni se marca PURGADO -- se reporta aparte y la fila
    queda intacta para revision humana.

    Construye un "canario" FUERA de `_archive/` (en `tmp_path` directamente) para
    probar que `purge()` NO lo toca aunque el INDEX lo nombre via `../`.
    """
    canary = tmp_path / "canario_fuera_del_archive.md"
    canary.write_text("no debe desaparecer\n", encoding="utf-8")
    old = _old_date(200)
    traversal_name = "../../canario_fuera_del_archive.md"
    _make_archive_project(
        tmp_path,
        [(traversal_name, old, "aa", "no citado ...")],
        set(),  # no se crea via `files`: el nombre no es un basename seguro
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.rejected_unsafe == [traversal_name]
    assert canary.exists(), "el fichero FUERA de _archive/ nunca debio tocarse"
    index_text = (
        tmp_path / "orchestrator_pipeline" / "arranques" / "_archive" / "INDEX.md"
    ).read_text(encoding="utf-8")
    assert "PURGADO" not in index_text, "una fila peligrosa no se marca como exito"


def test_absolute_path_row_is_rejected(tmp_path):
    """Una fila con separador de ruta (no solo `../`) tambien se rechaza."""
    old = _old_date(200)
    _make_archive_project(
        tmp_path,
        [("sub/ARRANQUE_x.md", old, "aa", "no citado ...")],
        set(),
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.rejected_unsafe == ["sub/ARRANQUE_x.md"]


def test_already_missing_file_is_not_marked_as_purged(tmp_path):
    """Rojo de WOT-2026-089p (hallazgo Codex): si el fichero YA faltaba de disco
    (perdida previa ajena a esta corrida), NO se fabrica un exito de purga -- la
    fila queda SIN el prefijo PURGADO para que `check_arranques_index` siga
    reportando la inconsistencia real.
    """
    old = _old_date(200)
    arranques_dir = (
        _make_archive_project(
            tmp_path,
            [("ARRANQUE_ya_ausente.md", old, "aa", "no citado ...")],
            set(),  # el fichero NUNCA existio en disco para esta corrida
        )
        / "orchestrator_pipeline"
        / "arranques"
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.purged == []
    assert report.already_missing == ["ARRANQUE_ya_ausente.md"]
    findings = cai.check_index_consistency(arranques_dir)
    assert len(findings) == 1, (
        "la fila SIN prefijo PURGADO debe seguir siendo un hallazgo real del guard"
    )
    assert "ARRANQUE_ya_ausente.md" in findings[0]


def test_missing_index_is_a_noop(tmp_path):
    """Sin `_archive/INDEX.md` todavia (nunca se archivo nada): denominador 0, no error."""
    arranques = tmp_path / "orchestrator_pipeline" / "arranques"
    arranques.mkdir(parents=True)
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "backlog.md").write_text("", encoding="utf-8")
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = pa.purge(tmp_path, ttl_days=90)

    assert report.denominator == 0
    assert report.purged == []
