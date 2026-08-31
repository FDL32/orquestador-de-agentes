"""WOT-2026-062a: la superficie publica de landed-commits es auditable fuera
del motor, con raices inyectables y sin convertir .agent/ en paquete Python.

El defecto (medido 2026-08-31): _ticket_landed_by_archived_commit
(.agent/agent_controller.py) resuelve la raiz POR ORIGEN de la fila (054e),
pero es privada y su modulo no es un paquete importable: el destino que debe
ACREDITAR ese fix no puede invocarla, asi que su sonda replica la logica a mano
y mide otra cosa. Estos tests cubren la superficie PUBLICA
(scripts/landed_commit_surface.py): importable por un proceso externo con cwd
FUERA del motor, que acepta raices inyectadas, y que concuerda con la
implementacion privada sobre los MISMOS (ticket, sha) pairs (el test de
acuerdo es la barrera contra una segunda implementacion que derive).

Los tres tests de 054e (tests/unit/test_landed_commit_root_resolution.py)
son NO-REGRESION: siguen verdes sin tocarse.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import agent_controller  # noqa: E402
from scripts.landed_commit_surface import ticket_landed_by_archived_commit  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return proc.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)

    _git(repo, "init")

    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")

    _git(repo, "config", "user.email", "t@e.com")

    _git(repo, "config", "user.name", "T")

    _git(repo, "config", "receive.denyCurrentBranch", "ignore")

    (repo / "README.md").write_text("# repo", encoding="utf-8")

    _git(repo, "add", ".")

    _git(repo, "commit", "-m", "init")


def _pushed_clone(src: Path) -> Path:
    """Clone src y push su historia de vuelta: src gana un origin/main real."""

    clone = src.parent / f"{src.name}-clone"

    _git(src.parent, "clone", str(src).replace("\\", "/"), str(clone))

    _git(clone, "config", "user.email", "t@e.com")

    _git(clone, "config", "user.name", "T")

    _git(clone, "push", "-u", "origin", "main")

    return clone


def _commit_in(repo: Path, name: str) -> str:
    (repo / f"{name}.py").write_text("x = 1", encoding="utf-8")

    _git(repo, "add", f"{name}.py")

    _git(repo, "commit", "-m", f"{name}: delivery")

    return _git(repo, "rev-parse", "HEAD")


def _archive_row(dest: Path, ticket_id: str, sha: str) -> None:
    archive = dest / ".agent" / "collaboration" / "_archive"

    archive.mkdir(parents=True, exist_ok=True)

    (archive / "backlog_done.md").write_text(
        "# Backlog -- historico\n\n"
        "| Ticket | Estado | Nota | Evidencia |\n"
        "|--------|--------|------|-----------|\n"
        f"| {ticket_id} | completed | cierre por landed commit | commit:{sha} |\n",
        encoding="utf-8",
    )


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    """Dos repos git reales (motor, destino,, cada uno con su origin/main
    pusheado; un archive estilo-compartido bajo destino citando AMBOS tipos de


    sha (solo-motor y solo-destino, ambos entregados/pusheados).




    """

    home = tmp_path / "w"

    motor = home / "m"

    dest = home / "d"

    _init_repo(motor)

    _init_repo(dest)

    motor = _pushed_clone(motor)

    dest = _pushed_clone(dest)

    motor_sha = _commit_in(motor, "wot2026541m")

    _git(motor, "push", "origin", "main")

    dest_sha = _commit_in(dest, "ctl202613cy")

    _git(dest, "push", "origin", "main")

    return {
        "motor": motor,
        "dest": dest,
        "motor_sha": motor_sha,
        "dest_sha": dest_sha,
    }


def _private_landed(world: dict, monkeypatch, ticket_id: str, sha: str) -> bool:
    archive = (
        world["dest"] / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    )
    collab = world["dest"] / ".agent" / "collaboration"

    monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: collab)

    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", world["motor"])

    assert archive.exists()

    return agent_controller._ticket_landed_by_archived_commit(ticket_id)


def test_public_surface_is_importable_without_package(
    tmp_path: Path, world: dict
) -> None:
    """Un proceso externo (cwd FUERA del motor) importa la superficie via
    sys.path insertion del root del MOTOR -- sin paquete .agent/ -- y la ejecuta
    booleana sobre raices reales inyectadas.
    """
    code = (
        "import sys\n"
        "sys.path.insert(0, " + repr(str(PROJECT_ROOT)) + ")\n"
        "from pathlib import Path\n"
        "from scripts.landed_commit_surface import ticket_landed_by_archived_commit\n"
        "v = ticket_landed_by_archived_commit(\n"
        "    " + repr("WOT-2026-061c") + ",\n"
        "    motor_root=Path(" + repr(str(world["motor"])) + "),\n"
        "    project_root=Path(" + repr(str(world["dest"])) + "),\n"
        ")\n"
        "print('verdict:', v)\n"
        "assert isinstance(v, bool)and v is True\n"
    )

    _archive_row(world["dest"], "WOT-2026-061c", world["motor_sha"])

    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr


def test_public_surface_accepts_injected_roots(world: dict) -> None:
    """Las raices INYECTADAS CAMBIAN el veredicto: un acreditador externo
    controla contra que raiz se pregunta, sin ninguna resolucion interna.」

    """
    _archive_row(world["dest"], "WOT-2026-061c", world["motor_sha"])

    v_correct = ticket_landed_by_archived_commit(
        "WOT-2026-061c",
        motor_root=world["motor"],
        project_root=world["dest"],
    )

    assert v_correct is True

    v_wrong = ticket_landed_by_archived_commit(
        "WOT-2026-061c",
        motor_root=world["dest"],
        project_root=world["dest"],
    )

    assert v_wrong is False


def test_public_surface_agrees_with_private_impl(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Para los MISMOS (ticket, sha) pairs, la superficie publica y la privada
    _ticket_landed_by_archived_commit devuelven EL MISMO veredicto. Esta es la
    barrera entre "expuse la funcion" (una implementacion, dos puertas) y
    "escribi una segunda implementacion que derivara".




    """

    cases = [
        ("CTL-2026-013y", world["dest_sha"]),
        ("WOT-2026-541m", world["motor_sha"]),
        ("WOT-2026-542k", secrets.token_hex(20)),
    ]

    for ticket_id, sha in cases:
        _archive_row(world["dest"], ticket_id, sha)

    for ticket_id, sha in cases:
        public = ticket_landed_by_archived_commit(
            ticket_id, motor_root=world["motor"], project_root=world["dest"]
        )

        private = _private_landed(world, monkeypatch, ticket_id, sha)

        assert public is private, (ticket_id, public, private)
