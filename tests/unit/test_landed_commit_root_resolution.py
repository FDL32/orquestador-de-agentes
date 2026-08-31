"""WOT-2026-054e: `_ticket_landed_by_archived_commit` must resolve the audit
git root PER ROW ORIGIN, not by a fixed constant.

Defect (measured by the destination's versioned probe
`tests/integration/test_ctl_013y_landed_commit_root.py` in Crear_Texto_LLM,
rc=1 on 19232c0): the function READS the destino archive (`get_collab_dir()`)
but audits those SHAs against `_MOTOR_ROOT`. A commit that only exists in the
destino repo has no git object in the motor, the landed guard answers WARN
(fail-closed by design -- NON-GOAL here), and the WOT-2026-024q exemption never
applies to tickets with `delivery_authority: repo_destino`: a silent false red
that reads as "not landed" forever.

These fixtures build TWO real local git repos with real origin/* refs (short
paths under tmp_path, Windows MAX_PATH). Tests are hermetic: no test reaches
the machine's repositories.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_agent_dir = PROJECT_ROOT / ".agent"
if str(_agent_dir) not in sys.path:
    sys.path.insert(0, str(_agent_dir))

import agent_controller  # noqa: E402


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
    # the clone's origin IS this repo: allow pushing into the checked-out branch
    _git(repo, "config", "receive.denyCurrentBranch", "ignore")
    (repo / "README.md").write_text("# repo", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")


def _pushed_clone(src: Path) -> Path:
    """Clone src and push its history back: src gains a real origin/main."""
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
    """Destino-only and motor-only delivered commits, one shared archive.

    motor has its own pushed origin; destino's archive cites BOTH kinds of sha
    (the dogfooded case: destino rows citing motor commits must keep working).
    """
    home = tmp_path / "w"
    motor = home / "m"
    dest = home / "d"
    _init_repo(motor)
    _init_repo(dest)
    motor = _pushed_clone(motor)
    dest = _pushed_clone(dest)
    motor_sha = _commit_in(motor, "wot2026541m")
    # the delivery lands: pushed, so it IS an ancestor of origin/main (the
    # fixture models a CLOSED flight, not one mid grouped-push)
    _git(motor, "push", "origin", "main")
    dest_sha = _commit_in(dest, "ctl202613y")
    _git(dest, "push", "origin", "main")
    return {
        "motor": motor,
        "dest": dest,
        "motor_sha": motor_sha,
        "dest_sha": dest_sha,
    }


def _landed(world: dict, monkeypatch, ticket_id: str, sha: str) -> bool:
    archive = (
        world["dest"] / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    )
    collab = world["dest"] / ".agent" / "collaboration"
    monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: collab)
    monkeypatch.setattr(agent_controller, "_MOTOR_ROOT", world["motor"])
    assert archive.exists()
    return agent_controller._ticket_landed_by_archived_commit(ticket_id)


def test_destination_only_sha_lands_via_destino_root(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row lives in the DESTINO archive and cites a DESTINO-only sha: it was
    audited against the motor (WARN, dead end). The fix resolves the home per
    row origin, so it lands. Rojo previo: fails without the fix."""
    _archive_row(world["dest"], "CTL-2026-013y", world["dest_sha"][:9])
    assert _landed(world, monkeypatch, "CTL-2026-013y", world["dest_sha"]) is True


def test_motor_sha_keeps_landing_against_motor(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-regression of the other direction: the destino archive row citing a
    MOTOR sha (dogfooded case) still audits against the motor and stays True.
    Discriminates 'resolve per origin' from 'swap the constant' -- pointing
    everything at the destino would flip this test red."""
    _archive_row(world["dest"], "WOT-2026-541m", world["motor_sha"][:9])
    assert _landed(world, monkeypatch, "WOT-2026-541m", world["motor_sha"]) is True


def test_sha_absent_everywhere_stays_fail_closed(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NON-GOAL guard: a sha with no git object in EITHER root keeps the WARN
    verdict (never ERROR, never OK) and the function keeps returning False.
    Fixing the root must not relax the verdict."""
    ghost = secrets.token_hex(20)
    _archive_row(world["dest"], "WOT-2026-542k", ghost)
    assert _landed(world, monkeypatch, "WOT-2026-542k", ghost) is False
