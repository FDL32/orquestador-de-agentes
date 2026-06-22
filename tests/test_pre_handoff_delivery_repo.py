"""Gate de cierre debe resolver el repo por delivery_authority (LEA topology fix).

Contrato: en topologia motor-externo + entrega en repo_destino, el deliverable
`code` (commit productivo + suite canonica) vive en el DESTINO, no en el motor.
Las dos barreras de cierre deben evaluarse contra el repo de entrega:

- `assert_canonical_suite_green` lee el `last-run.json` del repo de entrega y
  compara contra el HEAD de ESE repo.
- `assert_ticket_commit_visible` busca el commit del ticket en el repo de entrega.

Antes del fix, ambas asumian el motor: con --motor-root el commit_visible fallaba
(busca en motor); sin --motor-root el canonical_suite fallaba (sha motor vs HEAD
destino). Ningun commit del Builder satisfacia ambas a la vez.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pre_handoff_guard as guard  # noqa: E402

from tests.test_pre_handoff_guard import init_git_repo  # noqa: E402


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=30
    )


def _head(repo: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()


def _write_last_run(repo: Path, sha: str, *, status="finished", exit_code=0) -> None:
    p = repo / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "status": status,
                "exit_code": exit_code,
                "level": "all",
                "args_mode": "default_discovery",
                "tested_commit_sha": sha,
            }
        ),
        encoding="utf-8",
    )


def _commit(repo: Path, msg: str) -> str:
    f = repo / "f.txt"
    f.write_text(msg)
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", msg], cwd=repo)
    return _head(repo)


def _resolve(project_root: Path, motor_root, da: str) -> Path:
    """Resolutor bajo prueba: el repo de entrega segun delivery_authority."""
    return guard.resolve_delivery_root(
        project_root=project_root, motor_root=motor_root, delivery_authority=da
    )


# --- resolve_delivery_root ---


def test_resolve_delivery_root_destino_is_project_root(tmp_path: Path):
    motor, dest = tmp_path / "motor", tmp_path / "dest"
    assert _resolve(dest, motor, "repo_destino") == dest


def test_resolve_delivery_root_motor_is_motor_root(tmp_path: Path):
    motor, dest = tmp_path / "motor", tmp_path / "dest"
    assert _resolve(dest, motor, "repo_motor") == motor


def test_resolve_delivery_root_none_motor_falls_back_to_project(tmp_path: Path):
    dest = tmp_path / "dest"
    assert _resolve(dest, None, "repo_motor") == dest


# --- canonical_suite against the delivery repo (destino) ---


def test_canonical_suite_green_against_destino_head(tmp_path: Path):
    dest = tmp_path / "dest"
    init_git_repo(dest)
    sha = _commit(dest, "deliverable in destino")
    _write_last_run(dest, sha)  # suite stamped destino HEAD
    ok, diag = guard.assert_canonical_suite_green(dest, "code")
    assert ok, diag
    assert diag["reason"] == "fresh_green"


def test_canonical_suite_stale_when_sha_mismatches_destino_head(tmp_path: Path):
    dest = tmp_path / "dest"
    init_git_repo(dest)
    _commit(dest, "first")
    _write_last_run(dest, "deadbeef" * 5)  # wrong sha
    ok, diag = guard.assert_canonical_suite_green(dest, "code")
    assert not ok
    assert "stale_run" in diag["reason"]


# --- commit_visible against the delivery repo (destino) ---


def test_commit_visible_finds_ticket_commit_in_destino(tmp_path: Path):
    dest = tmp_path / "dest"
    init_git_repo(dest)
    _commit(dest, "feat(LEA-2026-001b): deliverable")
    ok, diag = guard.assert_ticket_commit_visible(
        ticket_id="LEA-2026-001b",
        deliverable_type="code",
        motor_root=dest,  # delivery repo
    )
    assert ok, diag
    assert diag["reason"] == "commit_visible"


def test_commit_visible_blocks_when_commit_only_in_motor(tmp_path: Path):
    # The ticket commit is in the motor, but delivery is the destino -> the
    # commit_visible check pointed at the destino must NOT find it.
    motor, dest = tmp_path / "motor", tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)
    _commit(motor, "feat(LEA-2026-001b): wrong repo")
    _commit(dest, "unrelated destino commit")
    ok, _ = guard.assert_ticket_commit_visible(
        ticket_id="LEA-2026-001b",
        deliverable_type="code",
        motor_root=dest,
    )
    assert not ok
