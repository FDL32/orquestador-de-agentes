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
import json
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


def _make_project(
    tmp_path: Path, files: dict[str, str], *, live_backlog: str | None = ""
) -> Path:
    """Proyecto temporal con `arranques/` y la superficie de citacion VIVA.

    `live_backlog=None` OMITE `backlog.md` a proposito, para los tests que pinean
    el fail-closed de WOT-2026-067n. Por defecto se crea VACIO: existe (el censo
    puede correr) y no cita a nadie, que es el fixture neutro que casi todos los
    tests quieren.
    """
    arranques = tmp_path / "orchestrator_pipeline" / "arranques"
    arranques.mkdir(parents=True)
    for name, content in files.items():
        (arranques / name).write_text(content, encoding="utf-8")
    collaboration = tmp_path / ".agent" / "collaboration"
    collaboration.mkdir(parents=True)
    if live_backlog is not None:
        (collaboration / "backlog.md").write_text(live_backlog, encoding="utf-8")
    return tmp_path


def _arranques(tmp_path: Path) -> Path:
    return tmp_path / "orchestrator_pipeline" / "arranques"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_p7():
    spec = importlib.util.spec_from_file_location(
        "p7_retire_for_161n", _ROOT / "scripts" / "flight" / "p7_retire.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    _make_project(tmp_path, {"ARRANQUE_libre.md": "contenido libre\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")
    root_file = _arranques(tmp_path) / "ARRANQUE_libre.md"
    before = _sha256(root_file)

    report = aa.archive(tmp_path, min_age_seconds=0)

    assert report.moved == []
    assert root_file.exists(), "el proponente no debe retirar el fichero"
    assert not (_arranques(tmp_path) / "_archive").exists()
    assert report.proposal == [
        {"rel": "orchestrator_pipeline/arranques/ARRANQUE_libre.md", "sha256": before}
    ]


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

    report = aa.archive(tmp_path, min_age_seconds=0)

    assert "ARRANQUE_referenciado.md" in report.cited
    assert not report.moved
    assert not report.proposal
    assert (_arranques(tmp_path) / "ARRANQUE_referenciado.md").exists()
    assert not (_arranques(tmp_path) / "_archive" / "ARRANQUE_referenciado.md").exists()


def test_index_has_one_row_per_moved_file(tmp_path):
    files = {f"ARRANQUE_n{i}.md": f"{i}\n" for i in range(3)}
    _make_project(tmp_path, files)
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, today="2026-09-10", min_age_seconds=0)

    assert report.proposal and len(report.proposal) == 3
    assert not (_arranques(tmp_path) / "_archive" / "INDEX.md").exists()
    assert cai.check_index_consistency(_arranques(tmp_path)) == []


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
    """La propuesta no toca INDEX y el guard sigue sin hallazgos."""
    _make_project(tmp_path, {"ARRANQUE_libre.md": "y\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, min_age_seconds=0)
    assert report.proposal
    assert cai.check_index_consistency(_arranques(tmp_path)) == []


# ------------------------------------------------------------------ seguridad de movimiento
def test_archive_refuses_to_overwrite_existing_history(tmp_path):
    _make_project(tmp_path, {"ARRANQUE_libre.md": "nuevo\n"})
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir()
    (archive / "ARRANQUE_libre.md").write_text("ya existia\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(_INDEX_EMPTY, encoding="utf-8")
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, min_age_seconds=0)
    assert report.proposal
    assert (archive / "ARRANQUE_libre.md").read_text(encoding="utf-8") == "ya existia\n"


def test_collision_late_in_the_batch_leaves_no_file_moved(tmp_path):
    """Rojo de WOT-2026-067n: una colision TARDIA no puede dejar mudanza parcial.

    El test hermano (`..._refuses_to_overwrite_existing_history`) usa UN solo
    fichero, asi que la colision cae en la primera iteracion y no hay nada movido
    todavia: no puede ALCANZAR esta rama. Aqui la colision cae en el SEGUNDO, con
    el primero ya movido -- el estado que `check_index_consistency` declara
    imposible ("el `_archive/` nace CONSISTENTE").
    """
    _make_project(
        tmp_path, {"ARRANQUE_aaa.md": "primero\n", "ARRANQUE_zzz.md": "segundo\n"}
    )
    archive = _arranques(tmp_path) / "_archive"
    archive.mkdir()
    (archive / "ARRANQUE_zzz.md").write_text("ya existia\n", encoding="utf-8")
    (archive / "INDEX.md").write_text(_INDEX_EMPTY, encoding="utf-8")
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, min_age_seconds=0)
    assert len(report.proposal) == 2

    # El historico previo sigue intacto y ningun proponente lo modifica.
    assert (archive / "ARRANQUE_zzz.md").read_text(encoding="utf-8") == "ya existia\n"
    # NINGUN fichero se mueve y el INDEX sigue cuadrando.
    assert (_arranques(tmp_path) / "ARRANQUE_aaa.md").exists(), (
        "el proponente no debe retirar el primer fichero"
    )
    assert not (archive / "ARRANQUE_aaa.md").exists()
    # El fichero sembrado no cambia y la propuesta no escribe el INDEX.
    findings = cai.check_index_consistency(_arranques(tmp_path))
    assert not [f for f in findings if "ARRANQUE_aaa" in f], findings


def test_citation_on_unmerged_branch_is_preserved(tmp_path):
    """Rojo de WOT-2026-067n: `git log` sin `--all` solo alcanza HEAD.

    Un arranque citado UNICAMENTE desde una rama no fusionada se clasificaria
    NO-CITADO y se moveria: perdida de evidencia, justo lo que DEC-067L-001
    prohibe. Control POSITIVO: el fichero no citado en ninguna parte SI se mueve,
    para que el test no pueda pasar por la via trivial de "no mueve nada".
    """
    _make_project(
        tmp_path, {"ARRANQUE_rama.md": "en rama\n", "ARRANQUE_huerfano.md": "nadie\n"}
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init sin citar ninguno")

    _git(tmp_path, "checkout", "-q", "-b", "rama-sin-fusionar")
    (tmp_path / "nota.md").write_text("x\n", encoding="utf-8")
    _commit_all(tmp_path, "cita ARRANQUE_rama.md desde una rama NO fusionada")
    _git(tmp_path, "checkout", "-q", "main")

    report = aa.archive(tmp_path, dry_run=True)

    assert "ARRANQUE_rama.md" in report.cited, (
        "la cita vive en una rama no fusionada: `git log` sin `--all` no la ve"
    )
    assert report.uncited == ["ARRANQUE_huerfano.md"]


def test_missing_live_backlog_aborts_instead_of_censusing_partially(tmp_path):
    """Rojo de WOT-2026-067n: la superficie VIVA ausente es fail-CLOSED.

    Saltarla en silencio dejaba el censo incompleto y podia mover un arranque
    citado solo desde `backlog.md` -- perdida de evidencia. La rama de `git log`
    ya abortaba en ese caso; esta no.
    """
    _make_project(tmp_path, {"ARRANQUE_x.md": "x\n"}, live_backlog=None)
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")
    assert not (tmp_path / ".agent" / "collaboration" / "backlog.md").exists()

    with pytest.raises(aa.ArchiveError, match="VIVA ausente"):
        aa.archive(tmp_path, dry_run=True)


def test_index_in_root_is_not_archivable(tmp_path):
    """`INDEX.md` en la RAIZ no puede clasificarse como archivable.

    Si lo fuera, la mudanza lo dejaria caer sobre el indice de `_archive/`.
    """
    _make_project(
        tmp_path, {"ARRANQUE_a.md": "a\n", "INDEX.md": "no soy un arranque\n"}
    )
    (tmp_path / ".agent" / "collaboration" / "backlog.md").write_text(
        "sin citas\n", encoding="utf-8"
    )
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, dry_run=True)

    assert report.denominator == 1, "INDEX.md no entra en el denominador"
    assert report.uncited == ["ARRANQUE_a.md"]


# ------------------------------------------------------------------ guarda de trabajo activo (WOT-2026-089p)
def test_dirty_uncited_file_is_skipped_not_archived(tmp_path):
    """Rojo de WOT-2026-089p: un NO-CITADO sin commitear NUNCA se mueve.

    Caso real que motiva la guarda: un bucle de gobierno clasifico como
    NO-CITADO el prompt de arranque ACTIVO de la sesion, que todavia no se
    habia commiteado. Sin esta guarda, `archive()` lo moveria igual que a
    cualquier otro historico.
    """
    _make_project(tmp_path, {})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init vacio")
    # Se crea DESPUES del commit inicial -> queda untracked (sucio).
    (_arranques(tmp_path) / "ARRANQUE_en_curso.md").write_text(
        "trabajo activo\n", encoding="utf-8"
    )

    report = aa.archive(tmp_path, min_age_seconds=0)

    assert report.moved == []
    assert "ARRANQUE_en_curso.md" in report.skipped
    assert "ARRANQUE_en_curso.md" not in report.archivable
    assert (_arranques(tmp_path) / "ARRANQUE_en_curso.md").exists()


def test_fresh_uncited_file_is_skipped_until_min_age(tmp_path):
    """Rojo de WOT-2026-089p: un NO-CITADO COMMITEADO pero reciente tampoco se mueve.

    Cubre el caso que la guarda de `git status` sola NO resuelve: un fichero ya
    commiteado (limpio) pero escrito hace minutos, que sigue siendo la
    referencia activa de la sesion en curso.
    """
    _make_project(tmp_path, {"ARRANQUE_reciente.md": "recien commiteado\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path)  # min_age_seconds=MIN_AGE_SECONDS (default real)

    assert report.moved == []
    assert "ARRANQUE_reciente.md" in report.skipped
    assert "ARRANQUE_reciente.md" not in report.archivable
    assert (_arranques(tmp_path) / "ARRANQUE_reciente.md").exists()


def test_proposal_entries_have_exact_p7_shape(tmp_path):
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    _make_project(tmp_path, {"ARRANQUE_shape.md": "shape\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    report = aa.archive(tmp_path, min_age_seconds=0)

    assert report.proposal
    assert all(set(entry) == {"rel", "sha256"} for entry in report.proposal)


def test_proposal_round_trip_is_accepted_and_bad_digest_is_rejected(tmp_path, capsys):
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    _make_project(tmp_path, {"ARRANQUE_roundtrip.md": "roundtrip\n"})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")
    report = aa.archive(tmp_path, min_age_seconds=0)
    list_path = tmp_path / "proposal.json"
    list_path.write_text(json.dumps(report.proposal), encoding="utf-8")
    digest = _sha256(list_path)
    p7 = _load_p7()
    archive_root = tmp_path.parent / f"{tmp_path.name}_external"
    archive_root.mkdir()
    args = [
        "--archive-root",
        str(archive_root),
        "--family",
        "arranques",
        "--origin",
        str(tmp_path),
        "--list",
        str(list_path),
        "--list-sha256",
        digest,
        "--dry-run",
    ]
    assert p7.main(args) == 0
    assert p7.main([*args[:-2], "0" * 64, "--dry-run"]) == 1
    assert "hash de lista no aprobado" in capsys.readouterr().err
    assert (
        tmp_path / "orchestrator_pipeline" / "arranques" / "ARRANQUE_roundtrip.md"
    ).exists()


def test_validate_proposal_rejects_empty_and_missing_sha256(tmp_path):
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    with pytest.raises(aa.ArchiveError):
        aa.validate_proposal([], tmp_path)
    with pytest.raises(aa.ArchiveError):
        aa.validate_proposal([{"rel": "x.md"}], tmp_path)


def test_validate_proposal_rejects_junction_ancestor(tmp_path):
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "x.md").write_text("x\n", encoding="utf-8")
    junction = tmp_path / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J no disponible: {result.stderr}")
    with pytest.raises(aa.ArchiveError):
        aa.validate_proposal(
            [{"rel": "junction/x.md", "sha256": _sha256(target / "x.md")}],
            tmp_path,
        )


def test_archive_main_denominator_zero_is_red(tmp_path, capsys):
    """[NON-REVERSE-CLASSICAL: redireccion de contrato a p7_retire]."""
    _make_project(tmp_path, {})
    _init_repo(tmp_path)
    _commit_all(tmp_path, "init")

    assert aa.archive(tmp_path).denominator == 0
    assert aa.main(["--project-root", str(tmp_path)]) == 1
    assert "VERDE VACUO" in capsys.readouterr().err
    assert not (_arranques(tmp_path) / "_archive").exists()
