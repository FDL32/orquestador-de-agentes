"""Tests for WOT-2026-069d: `--move-strays` must not retire TRACKED content
from a published repo by moving it onto a GITIGNORED canonical inbox.

MEDIDO 2026-09-13: `--move-strays` moved 3 TRACKED `.tickets.md` files (5
tracked verified at source) onto a canonical `backlog_inbox/` that was
GITIGNORED in that destino (0 tracked verified there), retiring 586 lines
from a published repo and colliding BLOCKING-vs-BLOCKING with
`Delivery Hygiene Check`. Real-git tests (not synthetic .gitignore parsing):
git itself is the source of truth for tracked/ignored, same pattern as
`test_check_flt_versionable.py`'s `two_repos` fixture.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_inbox_drainage import (
    _is_gitignored,
    _is_tracked,
    _tracked_retraction_conflicts,
    canonical_inbox,
    run_move_strays,
)


CANON_REL = Path(".agent") / "collaboration" / "backlog_inbox"


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_repo(tmp_path: Path) -> Path:
    """Destino real-git con identidad configurada y un commit inicial (HEAD)."""
    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / CANON_REL).mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True, capture_output=True)
    _git(dest, "config", "user.email", "t@example.com")
    _git(dest, "config", "user.name", "t")
    (dest / ".gitkeep").write_text("", encoding="utf-8")
    _git(dest, "add", ".")
    _git(dest, "commit", "-q", "-m", "init")
    return dest


def _touch(path: Path, body: str = "# ficha\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _track(dest: Path, rel_path: str) -> None:
    _git(dest, "add", rel_path)
    _git(dest, "commit", "-q", "-m", f"add {rel_path}")


# --------------------------------------------------------------------------- #
# _is_tracked / _is_gitignored: direct unit tests
# --------------------------------------------------------------------------- #


def test_is_tracked_and_is_gitignored_direct(tmp_path):
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    _touch(dest / stray_rel)
    _track(dest, stray_rel)
    assert _is_tracked(dest, stray_rel) is True
    assert _is_tracked(dest, "never/added.md") is False

    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")
    canon_rel = (CANON_REL / "FP-x.tickets.md").as_posix()
    assert _is_gitignored(dest, canon_rel) is True
    assert _is_gitignored(dest, stray_rel) is False


def test_is_tracked_fails_open_outside_a_git_repo(tmp_path):
    """No git repo at all (no .git/) -- both helpers must fail OPEN (False),
    never raise and never silently claim 'tracked'/'ignored'."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    assert _is_tracked(not_a_repo, "x.md") is False
    assert _is_gitignored(not_a_repo, "x.md") is False


# --------------------------------------------------------------------------- #
# _tracked_retraction_conflicts: the actual predicate
# --------------------------------------------------------------------------- #


def test_conflict_detected_tracked_source_ignored_destination(tmp_path):
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    _touch(dest / stray_rel)
    _track(dest, stray_rel)
    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")
    canon = canonical_inbox(dest)
    strays = [{"path": stray_rel, "basename": "FP-x.tickets.md"}]
    msgs = _tracked_retraction_conflicts(strays, canon, dest)
    assert len(msgs) == 1
    assert "FP-x.tickets.md" in msgs[0]
    assert "GITIGNORADO" in msgs[0]


def test_no_conflict_when_destination_not_ignored(tmp_path):
    """CONTROL NEGATIVO: tracked source, but the canonical destination is NOT
    gitignored -- the move is safe, nothing to declare."""
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    _touch(dest / stray_rel)
    _track(dest, stray_rel)
    canon = canonical_inbox(dest)  # no .gitignore entry for it
    strays = [{"path": stray_rel, "basename": "FP-x.tickets.md"}]
    assert _tracked_retraction_conflicts(strays, canon, dest) == []


def test_no_conflict_when_source_untracked(tmp_path):
    """CONTROL NEGATIVO: the canonical is gitignored, but the stray was never
    tracked in the first place -- no real retraction risk."""
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    _touch(dest / stray_rel)  # never git add'ed
    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")
    canon = canonical_inbox(dest)
    strays = [{"path": stray_rel, "basename": "FP-x.tickets.md"}]
    assert _tracked_retraction_conflicts(strays, canon, dest) == []


# --------------------------------------------------------------------------- #
# run_move_strays: end-to-end, the real DoD (aborts the whole batch, nothing
# moved at all -- same atomicity contract as the other preflight conflicts)
# --------------------------------------------------------------------------- #


def test_move_strays_aborts_when_it_would_retire_tracked_content(tmp_path):
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    stray_path = _touch(dest / stray_rel)
    _track(dest, stray_rel)
    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")

    rc = run_move_strays(dest)

    assert rc != 0
    assert stray_path.exists(), "the tracked file must stay exactly where it was"
    assert _is_tracked(dest, stray_rel) is True, "still tracked, nothing retired"
    assert list((dest / CANON_REL).glob("*.tickets.md")) == []


def test_move_strays_still_proceeds_for_untracked_strays(tmp_path):
    """REGRESSION GUARD: the new check must not break the ordinary case (an
    untracked stray moving onto a gitignored canonical is exactly the
    designed, safe workflow in most destinos)."""
    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    _touch(dest / stray_rel)  # untracked
    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")

    rc = run_move_strays(dest)

    assert rc == 0
    assert list((dest / CANON_REL).glob("*.tickets.md")) != []


def test_mutation_stripping_the_retraction_check_lets_the_dangerous_move_through(
    tmp_path, monkeypatch
):
    """Mutation-verify: patch `_tracked_retraction_conflicts` to a no-op (the
    exact pre-WOT-2026-069d behavior, where `_preflight_conflicts` only knew
    about duplicates/collisions) -> RED, the dangerous move SUCCEEDS and
    retires tracked content. Restored (real function) -> GREEN, it aborts.
    """
    import scripts.check_inbox_drainage as cid

    dest = _git_repo(tmp_path)
    stray_rel = "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md"
    stray_path = _touch(dest / stray_rel)
    _track(dest, stray_rel)
    (dest / ".gitignore").write_text(f"{CANON_REL.as_posix()}/\n", encoding="utf-8")
    _track(dest, ".gitignore")

    monkeypatch.setattr(cid, "_tracked_retraction_conflicts", lambda *a, **k: [])
    rc_red = cid.run_move_strays(dest)
    assert rc_red == 0, "RED: without the guard, the dangerous move succeeds"
    assert not stray_path.exists(), "RED: the tracked file got moved onto gitignored"

    monkeypatch.undo()
    # clean up the leftover at the canonical dir from the RED-phase move, and
    # restore the stray at its original path -- isolates GREEN's abort to the
    # retraction guard alone, not a stale "collision with canonical" leftover.
    (canonical_inbox(dest) / "FP-x.tickets.md").unlink()
    stray_path = _touch(dest / stray_rel)
    _track(dest, stray_rel)

    rc_green = cid.run_move_strays(dest)
    assert rc_green != 0, "GREEN: the real guard aborts the batch"
    assert stray_path.exists(), "GREEN: nothing got retired"
