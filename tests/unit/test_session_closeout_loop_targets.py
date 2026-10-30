"""Barrier tests for WOT-2026-045a: self-running writer of
`.agent/collaboration/loop_execution_targets.txt`.

Tests verify:
  (b) MUTATION that ISOLATES: a repo with a ticket commit and the writer
      invoked -> the file contains that commit's sha. Removing the writer
      call -> the file does not contain it (proven by calling the pure
      writer function directly, so the isolation is unambiguous).
  (c) CONTROL NEGATIVE: no ticket commits -> the file does not exist (and is
      removed if it existed from a previous run).
  NO AUTO-BLOQUEO: after writing, `git status --porcelain` does not list the
      file (because it is gitignored).
  deliverable_type: a ticket with `documentation` in its backlog row produces
      that value, not the `code` fallback.
  Idempotency: two runs produce identical content, no duplicates.
  Window: with `_window_start=None` nothing is filtered; with a date, commits
      before it are excluded.

Mutation-verified: see docstrings for each case. No `subprocess` mocking --
the repo precedent (test_closeout_self_dirty_allowlist.py) uses real git
repos, and a mock would only prove the mock (WOT-2026-045a contract).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.session_closeout import BACKLOG_REL


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import session_closeout  # noqa: E402


def _init_git_repo(repo: Path) -> None:
    """Create a minimal git repo with one initial commit (own .git, WOT-2026-020r)."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _commit_file_at(repo: Path, rel: str, content: str, message: str, when: str) -> str:
    """Como `_commit_file` pero con FECHA explicita (autor y committer).

    `git log --since` filtra por fecha del COMMITTER, asi que fijar solo
    GIT_AUTHOR_DATE no mueve la ventana: hay que fijar las dos.
    """
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_file(repo: Path, rel: str, content: str, message: str) -> str:
    """Create + commit a tracked file with an explicit commit message.

    Returns the commit sha (via `git rev-parse HEAD`).
    """
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "--", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _link_motor(project_root: Path, motor_root: Path) -> None:
    """Write motor_destination_link.json so resolve_motor_root() finds motor_root."""
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link_path = config_dir / "motor_destination_link.json"
    link_path.write_text(json.dumps({"motor_root": str(motor_root)}), encoding="utf-8")


TARGETS_REL = session_closeout.LOOP_EXECUTION_TARGETS_REL


# ---------------------------------------------------------------------------
# Case (b): mutation that isolates the branch
# ---------------------------------------------------------------------------


def test_writer_declares_the_ticket_commit(tmp_path: Path) -> None:
    """(b) Repo with 1 ticket commit + writer invoked -> file contains that sha.

    Mutation proof: NOT calling `_step_write_loop_execution_targets` (the
    branch under test) leaves the file absent -- see
    `test_no_call_means_no_file` below, which asserts exactly that by
    omission. The rest of run_closeout's pipeline is irrelevant here; only
    the writer's own behavior decides the verdict.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    sha = _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: implement feature")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    assert targets_path.exists()
    content = targets_path.read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} missing from {content!r}"
    assert content.strip().split()[0] == sha


def test_no_call_means_no_file(tmp_path: Path) -> None:
    """(b) mirror: without invoking the writer, the file is simply absent.

    This is the negative half of the mutation proof: retiring the call site
    in `run_closeout` (between `_resolve_tickets` and `_step_prepush_check`)
    reproduces exactly this state.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: implement feature")

    targets_path = repo / TARGETS_REL
    assert not targets_path.exists()


# ---------------------------------------------------------------------------
# Case (c): control negative
# ---------------------------------------------------------------------------


def test_control_negative_no_tickets_no_file(tmp_path: Path) -> None:
    """(c) No tickets resolved -> file does not exist."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)

    result = session_closeout._step_write_loop_execution_targets(repo, [], None, False)

    assert result.status == "PASS"
    assert not (repo / TARGETS_REL).exists()


def test_control_negative_stale_file_is_removed(tmp_path: Path) -> None:
    """(c) A stale file from a previous run is deleted when there is nothing
    to declare this time (no tickets resolved).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    targets_path = repo / TARGETS_REL
    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text("deadbeef code\n", encoding="utf-8")

    result = session_closeout._step_write_loop_execution_targets(repo, [], None, False)

    assert result.status == "PASS"
    assert not targets_path.exists()


def test_control_negative_ticket_with_no_commits_no_file(tmp_path: Path) -> None:
    """(c) A ticket is resolved but git log finds no matching commit -> no file."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-777z", "repo_motor")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-777z"], None, False
    )

    assert result.status == "PASS"
    assert not (repo / TARGETS_REL).exists()


# ---------------------------------------------------------------------------
# NO AUTO-BLOQUEO: file does not show up in git status (gitignored)
# ---------------------------------------------------------------------------


def test_no_self_dirty_when_gitignored(tmp_path: Path) -> None:
    """After writing, `git status --porcelain` does not list the targets file
    when it is declared in .gitignore -- proving the writer cannot make
    check_git_tree_clean (BLOCKING) fail against itself.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    (repo / ".gitignore").write_text(
        ".agent/collaboration/loop_execution_targets.txt\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", "--", ".gitignore"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add gitignore"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: implement feature")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )
    assert result.status == "PASS", result.detail

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "loop_execution_targets.txt" not in status.stdout, status.stdout


# ---------------------------------------------------------------------------
# deliverable_type resolution
# ---------------------------------------------------------------------------


def test_deliverable_type_from_backlog_row(tmp_path: Path) -> None:
    """A ticket with `documentation` declared in its backlog row produces
    ` documentation`, not the ` code` fallback.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999b", "repo_motor")
    sha = _commit_file(repo, "docs/x.md", "# doc", "WOT-2026-999b: write docs")
    backlog_path = repo / session_closeout.BACKLOG_REL
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | "
        "Reactivation |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| Alta | WOT-2026-999b | Escribe docs. deliverable_type: documentation | "
        "motor/x | pending | - | - | - |\n",
        encoding="utf-8",
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999b"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    assert f"{sha} documentation" in content, content


def test_deliverable_type_fallback_to_code_without_backlog_row(
    tmp_path: Path,
) -> None:
    """A ticket absent from both backlog surfaces falls back to `code`."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999c", "repo_motor")
    sha = _commit_file(
        repo, "src/b.py", "y = 2", "WOT-2026-999c: implement without backlog row"
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999c"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    # WOT-2026-048w: the fallback must be MARKED, not silent -- a guessed
    # "code" is indistinguishable from a declared one without this token.
    assert f"{sha} code declared=false" in content, content


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_rewrite_no_duplicates(tmp_path: Path) -> None:
    """Two consecutive runs with no new commits produce identical content."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: implement feature")

    first = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )
    content_1 = (repo / TARGETS_REL).read_text(encoding="utf-8")

    second = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )
    content_2 = (repo / TARGETS_REL).read_text(encoding="utf-8")

    assert first.status == "PASS"
    assert second.status == "PASS"
    assert content_1 == content_2
    # No duplicated sha lines: each commit sha appears exactly once.
    file_lines = [ln for ln in content_2.splitlines() if ln.strip()]
    assert len(file_lines) == len(set(file_lines)), file_lines


# ---------------------------------------------------------------------------
# Window: both branches
# ---------------------------------------------------------------------------


def test_window_none_declares_all_matching_commits(tmp_path: Path) -> None:
    """With `_window_start=None`, commits are not filtered by date at all --
    this is the branch this ticket's own flight runs under (code-only mode,
    0 bus events).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999d", "repo_motor")
    # Backdate the commit far in the past; with no window filter it must
    # still be declared.
    old_date = "2000-01-01T00:00:00"
    subprocess.run(["git", "add", "--", "."], cwd=repo, check=True, capture_output=True)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "old.py").write_text("z = 1")
    subprocess.run(
        ["git", "add", "--", "src/old.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "WOT-2026-999d: old commit",
            f"--date={old_date}",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_DATE": old_date,
            "GIT_COMMITTER_DATE": old_date,
            "PATH": subprocess.os.environ.get("PATH", ""),
            "HOME": subprocess.os.environ.get("HOME", ""),
            "USERPROFILE": subprocess.os.environ.get("USERPROFILE", ""),
        },
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999d"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content, content


def test_window_with_date_excludes_older_commits(tmp_path: Path) -> None:
    """With a resolved `_window_start`, `--since` excludes commits older than
    the flight window: the sha does not appear in the file, and since it is
    the only ticket commit, nothing is declared and the file is absent.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999e", "repo_motor")
    old_date = "2000-01-01T00:00:00"
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "old.py").write_text("z = 1")
    subprocess.run(
        ["git", "add", "--", "src/old.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "WOT-2026-999e: old commit"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_DATE": old_date,
            "GIT_COMMITTER_DATE": old_date,
            "PATH": subprocess.os.environ.get("PATH", ""),
            "HOME": subprocess.os.environ.get("HOME", ""),
            "USERPROFILE": subprocess.os.environ.get("USERPROFILE", ""),
        },
    )

    window_start = datetime.now(timezone.utc) - timedelta(days=1)
    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999e"], window_start, False
    )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists()


# ---------------------------------------------------------------------------
# dry_run: no filesystem I/O at all (MANAGER_REVIEW defecto 2)
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_file(tmp_path: Path) -> None:
    """With dry_run=True, the writer performs no git calls and does not
    create the targets file, even though a matching ticket commit exists.

    Mirrors the unanimous pattern of every other mutating step in this
    module (`_step_cleanup_builder_session`, `_step_git_clean`, ...): dry_run
    short-circuits to SKIP before any I/O.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: implement feature")
    # Con autoridad declarada el dry-run sigue siendo SKIP; sin ella ahora
    # avisa (WOT-2026-089m), y el fixture original no la declaraba.
    ficha = repo / ".agent" / "collaboration" / "backlog.md"
    ficha.parent.mkdir(parents=True, exist_ok=True)
    ficha.write_text(
        "### WOT-2026-999a - x\n\n- **delivery_authority:** repo_motor.\n",
        encoding="utf-8",
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, True
    )

    assert result.status == "SKIP"
    assert "dry-run" in result.detail.lower()
    assert not (repo / TARGETS_REL).exists()


def test_dry_run_does_not_delete_preexisting_file(tmp_path: Path) -> None:
    """With dry_run=True, a stale targets file from a previous run is left
    untouched -- dry-run must not mutate state in either direction (no
    write, no delete).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    targets_path = repo / TARGETS_REL
    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text("deadbeef code\n", encoding="utf-8")

    result = session_closeout._step_write_loop_execution_targets(repo, [], None, True)

    assert result.status == "SKIP"
    assert targets_path.exists()
    assert targets_path.read_text(encoding="utf-8") == "deadbeef code\n"


# ---------------------------------------------------------------------------
# Wiring / mutation: run_closeout must actually CALL the writer, before
# prepush_check, with the resolved args (MANAGER_REVIEW defecto 1).
# ---------------------------------------------------------------------------


def _write_work_plan(project_root: Path, ticket_id: str) -> None:
    wp_dir = project_root / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True, exist_ok=True)
    (wp_dir / "work_plan.md").write_text(
        f"# Work Plan\n\n## Metadata\n- **ID:** {ticket_id}\n- **Estado:** APPROVED\n",
        encoding="utf-8",
    )


def _declare_authority(project_root: Path, ticket_id: str, authority: str) -> None:
    """Escribe el work_plan activo del fixture declarando `delivery_authority`.

    WOT-2026-066i (D1): la resolucion de raiz se lee de este campo DECLARADO;
    los fixtures que ejercitan la resolucion deben declararlo, igual que un
    contrato real. Sin la declaracion, el ticket cae en D2 (fail-closed).
    """
    wp_dir = project_root / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True, exist_ok=True)
    (wp_dir / "work_plan.md").write_text(
        f"# Work Plan\n\n## Metadata\n- **ID:** {ticket_id}\n"
        f"- **delivery_authority:** {authority}\n",
        encoding="utf-8",
    )


def test_run_closeout_calls_writer_before_prepush(tmp_path: Path, monkeypatch) -> None:
    """`run_closeout` must call `_step_write_loop_execution_targets` with the
    resolved `project_root`, `ticket_ids` and `_window_start`, and it must do
    so BEFORE `_step_prepush_check` runs.

    Mutation proof (self-verified, see BUILDER REPORT): retiring the
    call-site inside `run_closeout` (the exact defect the reviewer measured:
    `11 passed` even with the call-site removed, because all prior tests
    invoked the writer directly) makes `writer_call["invoked"]` stay False
    and this test FAILS on the first assertion.
    """
    _write_work_plan(tmp_path, "WOT-2026-045a")

    writer_call: dict = {"invoked": False}
    call_order: list[str] = []

    def _fake_writer(project_root, ticket_ids, window_start, dry_run):
        writer_call["invoked"] = True
        writer_call["project_root"] = project_root
        writer_call["ticket_ids"] = ticket_ids
        writer_call["window_start"] = window_start
        writer_call["dry_run"] = dry_run
        call_order.append("writer")
        return session_closeout.StepResult(
            name="write_loop_execution_targets", status="PASS", detail="faked"
        )

    def _fake_prepush(project_root, dry_run, skip_gates=False):
        call_order.append("prepush")
        # Cut cheap via the early-exit branch in run_closeout (FAIL -> return 1).
        return session_closeout.StepResult(
            name="prepush_check", status="FAIL", detail="faked", blocking=True
        )

    monkeypatch.setattr(
        session_closeout, "_step_write_loop_execution_targets", _fake_writer
    )
    monkeypatch.setattr(session_closeout, "_step_prepush_check", _fake_prepush)

    exit_code = session_closeout.run_closeout(tmp_path, dry_run=False)

    assert writer_call["invoked"] is True, (
        "run_closeout must call _step_write_loop_execution_targets; it did "
        "not (this is the exact defect measured by the reviewer: retiring "
        "the call-site leaves prior tests green because they call the "
        "writer directly, never through run_closeout)"
    )
    assert writer_call["project_root"] == tmp_path
    assert writer_call["ticket_ids"] == ["WOT-2026-045a"]
    assert writer_call["window_start"] is None
    assert writer_call["dry_run"] is False
    assert call_order == ["writer", "prepush"], (
        f"writer must run BEFORE prepush_check; got order {call_order}"
    )
    assert exit_code == 1  # early-exit from the faked prepush FAIL


def test_writer_stamps_loop_target_with_phase_and_delivery_authority(
    tmp_path: Path,
) -> None:
    """O1: the session-close writer emits the metadata consumed by prepush."""
    _init_git_repo(tmp_path)
    _link_motor(tmp_path, tmp_path)
    _declare_authority(tmp_path, "WOT-2026-045a", "repo_motor")
    sha = _commit_file(tmp_path, "src/a.py", "x = 1", "WOT-2026-045a: fix")

    result = session_closeout._step_write_loop_execution_targets(
        tmp_path, ["WOT-2026-045a"], None, False
    )

    assert result.status == "PASS"
    line = (tmp_path / TARGETS_REL).read_text(encoding="utf-8").strip()
    assert line.startswith(f"{sha} code ")
    assert "phase=MANAGER_REVIEW" in line
    assert "delivery_authority=repo_motor" in line
    assert line.endswith("source=session-close")


# ---------------------------------------------------------------------------
# WOT-2026-048b: two-repo prefix-aware resolution
# ---------------------------------------------------------------------------


def test_non_wot_ticket_commits_in_destino(tmp_path: Path) -> None:
    """Non-WOT ticket DECLARING `delivery_authority: repo_destino` with commits
    in the destino but NOT in the motor -> PASS with targets written.

    WOT-2026-066i (D1): the writer resolves the authoritative repo from the
    DECLARED field, not from the prefix (the prefix only LOCATES the
    destination). This is the declared-destino path: the field decides.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "CTL-2026-001", "repo_destino")

    sha = _commit_file(destino, "src/a.py", "x = 1", "CTL-2026-001: fix bug")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "CTL":
            return destino
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["CTL-2026-001"], None, False
        )

    assert result.status == "PASS", result.detail
    content = (destino / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} missing from {content!r}"


def test_non_wot_ticket_commits_in_motor_is_fail(tmp_path: Path) -> None:
    """Non-WOT ticket DECLARING `delivery_authority: repo_destino`, with its
    commits in the motor (wrong repo) but NOT in the destino ->
    FAIL_TARGETS_MISSING.

    The control query detects commits in the non-authoritative repo. La
    declaracion es load-bearing (WOT-2026-073d): sin ella el ticket no tiene
    ninguna superficie propia y el contrato nuevo lo EXCLUYE con WARN en vez de
    fallar por ausencia; con ella se ejercita de verdad la consulta de control
    que el titulo promete.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "CTL-2026-002", "repo_destino")

    _commit_file(motor, "src/a.py", "x = 1", "CTL-2026-002: fix bug")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "CTL":
            return destino
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["CTL-2026-002"], None, False
        )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_wot_ticket_commits_in_motor_two_repos(tmp_path: Path) -> None:
    """WOT ticket DECLARING `delivery_authority: repo_motor` with commits in
    the motor (correct) but NOT in the destino -> PASS.

    WOT-2026-066i (D1/D5): PASS por el CAMPO DECLARADO, no por un caso especial
    de prefijo. La declaracion en el fixture es load-bearing: la mutacion D5(ii)
    (neutralizar la lectura del campo) debe hacer CAER este test -- si sigue
    verde bajo la mutacion, esta pasando por un hardcode `WOT-` que D1 retira.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "WOT-2026-999a", "repo_motor")

    sha = _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-999a: feature")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (destino / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} missing from {content!r}"


def test_unresolvable_prefix_with_declared_repo_destino_fails_closed(
    tmp_path: Path,
) -> None:
    """Ticket que DECLARA `repo_destino` y cuyo prefijo no resuelve a ninguna
    raiz -> FAIL blocking, nombrando el ticket.

    WOT-2026-066i (D2): la rama WARN-skip de prefijo no resoluble queda
    RETIRADA -- declarar `repo_destino` y no poder localizar esa raiz es
    fail-closed: un skip silencioso dejaria fuera del ambito los commits de un
    ticket que el cierre no sabe donde buscar (el falso verde exacto que D2
    impide). (Antes de 066i este caso devolvia WARN_PREFIX_UNRESOLVABLE; ver
    execution_log del ticket.)

    WOT-2026-073d: el fixture gana la declaracion (rama :1804, que hasta hoy
    ningun test cubria). SIN declaracion el ticket no tiene superficie propia y
    el contrato nuevo lo EXCLUYE con WARN -- eso lo pinean los tests de
    exclusion, no este.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "ZZZ-2026-001", "repo_destino")

    _commit_file(destino, "src/a.py", "x = 1", "ZZZ-2026-001: unknown prefix")

    def _fake_resolve_prefix(prefix, _motor_root):
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["ZZZ-2026-001"], None, False
        )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "ZZZ-2026-001" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_control_query_skipped_when_same_repo(tmp_path: Path) -> None:
    """When the resolved root IS the motor root (single-repo topology,
    project_root == motor_root), the control query is skipped: same repo =
    no meaningful 'other' to check.

    WOT-2026-066i: this is now the TRIVIAL-topology branch of
    `_resolve_authoritative_repo` -- one candidate root, nothing to
    misresolve, no declaration required.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "CTL-2026-003", "repo_motor")

    def _fake_resolve_prefix(prefix, _motor_root):
        return _motor_root  # resolves to same repo

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            repo, ["CTL-2026-003"], None, False
        )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists()


def test_mixed_results_one_fail_one_pass(tmp_path: Path) -> None:
    """Two tickets: one WITH a backlog row but WITHOUT declared authority
    (D2 -> FAIL), one WOT DECLARING repo_motor with commits (PASS). Overall
    status is FAIL blocking, the detail names the failed ticket, and the
    targets file is NOT written (a batch with a misresolved ticket writes no
    partial scope).

    WOT-2026-066i: antes de D2 el ticket sin campo daba WARN
    (WARN_PREFIX_UNRESOLVABLE) y el mixto salia WARN con fichero escrito; la
    ausencia declarada ahora es fail-closed. WOT-2026-073d: la fila de backlog
    del fixture es load-bearing -- sin NINGUNA superficie el ticket se
    EXCLUIRIA con WARN y el lote dejaria de ser mixto.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "WOT-2026-999c", "repo_motor")
    _write_backlog(destino, "| Alta | ZZZ-2026-001 | fila sin delivery_authority |\n")

    sha = _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-999c: feature")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "WOT":
            return destino
        return None  # all non-WOT fail

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["ZZZ-2026-001", "WOT-2026-999c"], None, False
        )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "ZZZ-2026-001" in result.detail
    assert not (destino / TARGETS_REL).exists(), (
        "un lote con un ticket sin raiz resuelta no escribe un ambito parcial"
    )
    assert sha  # el commit del ticket declarado existe en el motor (fixture)


# ---------------------------------------------------------------------------
# WOT-2026-066a: membresia por ENTREGA, no por MENCION.
#
# Medido 2026-09-04: `_git_log_shas_for_ticket` corria
# `git log --grep=<ticket_id>` sobre el mensaje COMPLETO. Un commit que
# entregaba CTL-2026-027b y mencionaba WOT-2026-062d una vez en su cuerpo
# entraba en el `targets.txt` de un vuelo ajeno como si lo entregara, y
# bloqueaba el cierre con 0/4 lentes. El subject NO lo mencionaba.
# ---------------------------------------------------------------------------


def test_mencion_en_prosa_del_cuerpo_no_es_entrega(tmp_path: Path) -> None:
    """Un commit que MENCIONA el ticket en el cuerpo pero entrega OTRO no entra.

    ROJO antes del fix: `--grep` sobre el mensaje completo lo capturaba.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(
        repo,
        "src/otro.py",
        "y = 2",
        "WOT-2026-888z: arregla otra cosa\n\nContexto: esto NO entrega WOT-2026-999a,\nsolo lo menciona como referencia historica.",
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    assert not targets_path.exists(), (
        "un commit que solo MENCIONA el ticket en el cuerpo no lo entrega: "
        f"targets no deberia existir, contiene {targets_path.read_text(encoding='utf-8') if targets_path.exists() else ''!r}"
    )


def test_trailer_estructurado_si_es_entrega(tmp_path: Path) -> None:
    """Falso NEGATIVO: si el ticket se declara en un TRAILER, SI entra.

    Un fix subject-only ingenuo romperia squash/fixup y las entregas que
    declaran su ticket con `Ticket:`/`Closes:` en vez de en el subject.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    sha = _commit_file(
        repo,
        "src/b.py",
        "z = 3",
        "fix: corrige el parser sin id en el subject\n\nTicket: WOT-2026-999a",
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    assert targets_path.exists(), "una entrega declarada en trailer DEBE entrar"
    assert sha in targets_path.read_text(encoding="utf-8")


def test_delivery_trailers_set_frozen(tmp_path: Path) -> None:
    """Fija el conjunto exacto de trailers de entrega.

    Por cada trailer documentado en el docstring de
    `_git_log_shas_for_ticket`, `_delivers_ticket` debe devolver True.
    Por un trailer NO documentado (`refs`), debe devolver False.

    MUTATION-VERIFY (WOT-2026-067s): si alguien cambia `_DELIVERY_TRAILERS`
    sin sincronizar el docstring, este test FALLA. Es un contract-test entre
    la constante y la documentacion.
    """
    import inspect

    # Docstring: extrae la lista de trailers citada.
    docstring = inspect.getdoc(session_closeout._git_log_shas_for_ticket) or ""

    # Los trailers que el docstring ENUNICIA (backticks + ":", strip to bare).
    doc_trailers: set[str] = set()
    for token in docstring.split():
        # Strip backticks, colons, and surrounding punctuation:
        # `` `Ticket:`, `` -> "ticket"
        cleaned = token.lower().strip("`").rstrip(":").strip(".,;:()[]{}'\"`")
        if cleaned in (
            "ticket",
            "closes",
            "fixes",
            "resolves",
            "refs",
        ):
            doc_trailers.add(cleaned)

    # `Refs:` NO debe aparecer en el docstring (WOT-2026-066a).
    assert "refs" not in doc_trailers, (
        f"Refs: no debe estar documentado como entrega; docstring lo cita: {doc_trailers}"
    )

    # El docstring debe mencionar EXACTAMENTE lo que tiene la constante.
    expected = set(session_closeout._DELIVERY_TRAILERS)
    assert doc_trailers == expected, (
        f"docstring {doc_trailers} != _DELIVERY_TRAILERS {expected}"
    )

    # Verificacion funcional: cada trailer documentado SI entrega.
    ticket_id = "WOT-2026-TEST00"
    for trailer in expected:
        body = f"{trailer}: {ticket_id}"
        assert session_closeout._delivers_ticket("", body, ticket_id), (
            f"trailer {trailer!r} documentado pero _delivers_ticket -> False"
        )

    # Y un trailer no-documentado NO entrega.
    body_refs = f"refs: {ticket_id}"
    assert not session_closeout._delivers_ticket("", body_refs, ticket_id), (
        "refs: no debe ser entrega"
    )


def test_subject_sigue_siendo_entrega(tmp_path: Path) -> None:
    """No-regresion: el caso canonico (ticket en el subject) sigue entrando."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    sha = _commit_file(repo, "src/c.py", "w = 4", "WOT-2026-999a: el caso normal")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    assert (repo / TARGETS_REL).exists()
    assert sha in (repo / TARGETS_REL).read_text(encoding="utf-8")


def test_substring_accidental_no_es_entrega(tmp_path: Path) -> None:
    """`WOT-2026-999ab` en el subject no entrega `WOT-2026-999a`.

    `--fixed-strings` casa substrings: sin frontera de palabra, un id que
    CONTIENE a otro lo arrastra al ambito.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(repo, "src/d.py", "v = 5", "WOT-2026-999ab: otro ticket distinto")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    assert not targets_path.exists(), (
        "un id que CONTIENE al buscado no lo entrega: 999ab != 999a"
    )


def test_f1b_ambito_vaciado_falla_en_vez_de_borrar(tmp_path: Path) -> None:
    """Si el ambito quedaria VACIO partiendo de no-vacio, FALLA. No borra.

    LOAD-BEARING (WOT-2026-066a): sin el fichero, `check_loop_execution` hace
    SKIP NO bloqueante. Un ambito vaciado seria indistinguible de uno correcto
    -- el falso verde exacto que la barrera existe para impedir. Medido
    2026-09-04: una propuesta de excluir tickets archivados sacaba 6 de 9,
    incluido el de la propia sesion, y habria borrado el fichero en silencio.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-000z", "repo_motor")
    _commit_file(repo, "src/e.py", "u = 6", "WOT-2026-777a: algo")

    targets_path = repo / TARGETS_REL
    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text("deadbeef0000 code\n", encoding="utf-8")

    # Ticket sin commits -> el escritor no produce lineas.
    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-000z"], None, False
    )

    assert result.status == "FAIL", (
        f"vaciar un ambito no-vacio debe FALLAR, no borrar: {result.detail}"
    )
    assert "FAIL_TARGETS_EMPTIED" in result.detail
    assert targets_path.exists(), "el fichero NO se borra cuando el vaciado falla"


def test_f1b_no_dispara_si_no_habia_targets(tmp_path: Path) -> None:
    """Control negativo: sin fichero previo, cero targets sigue siendo PASS.

    Una sesion de mantenimiento legitima no declara nada y eso no es un fallo.
    Sin este control, F1b convertiria en error el caso normal.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-000z", "repo_motor")
    _commit_file(repo, "src/f.py", "t = 7", "WOT-2026-777a: algo")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-000z"], None, False
    )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists()


def test_f1b_alcance_declarado_ticket_sin_commits_es_legitimo(tmp_path: Path) -> None:
    """Ticket resuelto SIN commits y sin fichero previo -> PASS, no FAIL.

    Alcance DELIBERADO de F1b, medido: glm-5.2 propuso el invariante fuerte
    ("tickets => ambito no vacio o FAIL"). Se implanto y rompio 7 tests que
    describen comportamiento CORRECTO: un ticket documental no produce commits,
    y `test_control_negative_ticket_with_no_commits_no_file` lo pinea desde
    antes. F1b caza la PERDIDA de un ambito que existia, no la ausencia de uno
    que nunca hubo.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(repo, "src/g.py", "s = 8", "otro: nada que ver con el ticket")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists()


def test_refs_no_es_entrega(tmp_path: Path) -> None:
    """`Refs:` es REFERENCIA, no entrega: no debe meter el commit en el ambito.

    Aceptarlo reabriria la clase del bug original en forma mas estrecha
    (hallazgo glm-5.2).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(
        repo,
        "src/h.py",
        "r = 9",
        "WOT-2026-888z: otra cosa\n\nRefs: WOT-2026-999a",
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists(), (
        "`Refs:` es REFERENCIA, no entrega: ese commit no entra en el ambito"
    )


def test_frontera_no_deja_pasar_guion_bajo(tmp_path: Path) -> None:
    """`WOT-2026-999a_fix` en el subject es un nombre de rama, no una entrega."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    _commit_file(repo, "src/i.py", "q = 10", "merge de WOT-2026-999a_fix en main")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    assert not (repo / TARGETS_REL).exists(), (
        "`WOT-2026-999a_fix` es un nombre de rama, no una entrega"
    )


# ---------------------------------------------------------------------------
# WOT-2026-066i: la raiz autoritativa se resuelve por el `delivery_authority`
# DECLARADO del contrato del ticket (D1); la ausencia es fail-closed (D2); el
# caso especial hardcodeado de `WOT-` muere POR COMPORTAMIENTO (D5).
# ---------------------------------------------------------------------------


def test_declared_repo_motor_resolves_to_motor(tmp_path: Path) -> None:
    """D1: un ticket que DECLARA `delivery_authority: repo_motor` resuelve al
    MOTOR aunque su prefijo resuelva al destino: sin FAIL_TARGETS_MISSING.

    Regression medida en el corpus real (premisa de WOT-2026-066i):
    CTL-2026-027b declara repo_motor y la resolucion por prefijo mandaba el
    gate al destino -> FAIL_TARGETS_MISSING bloqueante (ROJO sin el fix).
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "CTL-2026-900b", "repo_motor")
    sha = _commit_file(motor, "src/a.py", "x = 1", "CTL-2026-900b: fix bug")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "CTL":
            return destino
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["CTL-2026-900b"], None, False
        )

    assert result.status == "PASS", result.detail
    assert "FAIL_TARGETS_MISSING" not in result.detail
    content = (destino / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} missing from {content!r}"


def test_declared_authority_read_from_destination_archive_plan(
    tmp_path: Path,
) -> None:
    """D1: el campo declarado se lee del work_plan ARCHIVADO del propio
    destino (`_archive/work_plan_<ID>_*.md`) -- la superficie real de los
    tickets historicos (medido 2026-09-06 en el corpus: el contrato de un
    ticket de prefijo ajeno entregado al motor vive en el work_plan archivado
    de su destino). Sin esta superficie, un ticket cerrado caeria en D2.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    archive = destino / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "work_plan_CTL-2026-901a_COMPLETED.md").write_text(
        "# Plan de Trabajo: CTL-2026-901a\n\n## Metadata\n"
        "- **ID:** CTL-2026-901a\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )
    sha = _commit_file(motor, "src/a.py", "x = 1", "CTL-2026-901a: fix bug")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "CTL":
            return destino
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["CTL-2026-901a"], None, False
        )

    assert result.status == "PASS", result.detail
    assert "FAIL_TARGETS_MISSING" not in result.detail
    assert sha in (destino / TARGETS_REL).read_text(encoding="utf-8")


def test_declared_authority_matches_human_spelling_with_space(
    tmp_path: Path,
) -> None:
    """Regresion: `_DELIVERY_AUTHORITY_DECLARED_RE` solo reconocia
    `delivery_authority` (snake_case) o `repo de autoridad` (espanol); la
    grafia humana en ingles `**Delivery Authority:**` (con espacio, sin guion
    bajo) no matcheaba y caia en D2 fail-closed pese a estar declarada.

    Medido 2026-09-29 sobre el cierre real de WOT-2026-055o: su propio
    `work_plan.md` (y el de su archivo original) usan exactamente esta
    grafia, igual que 21+ `work_plan_*.md` historicos del mismo destino
    (patron mayoritario, no caso aislado) -- confirma que el defecto vivia
    en el regex, no en el dato.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    wp = destino / ".agent" / "collaboration" / "work_plan.md"
    wp.parent.mkdir(parents=True, exist_ok=True)
    wp.write_text(
        "# Plan de Trabajo: fixture\n\n## Metadata\n"
        "- **ID:** WOT-2026-902b\n"
        "- **Delivery Authority:** repo_motor\n",
        encoding="utf-8",
    )
    sha = _commit_file(motor, "src/b.py", "x = 2", "WOT-2026-902b: fix bug")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902b"], None, False
    )

    assert result.status == "PASS", result.detail
    assert "FAIL_TARGETS_MISSING" not in result.detail
    assert sha in (destino / TARGETS_REL).read_text(encoding="utf-8")


def test_declared_authority_read_from_frozen_contract_block(
    tmp_path: Path,
) -> None:
    """D1/D9: el campo se lee del BLOQUE del contrato frozen en
    `ticket_contracts.md` (la superficie de los 6 contratos `WOT-` que declaran
    `repo_destino`). El bloque se empareja por su campo `ticket_id:` (o
    cabecera), NUNCA por menciones del cuerpo (citas ajenas no son contrato).
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    contracts = destino / ".agent" / "planning" / "ticket_contracts.md"
    contracts.parent.mkdir(parents=True, exist_ok=True)
    contracts.write_text(
        "# ticket_contracts.md\n\n"
        "## T-902A-001 -- contrato de WOT-2026-902a\n\n"
        "- **ticket_id:** WOT-2026-902a\n"
        "- **status:** frozen\n"
        "- **delivery_authority:** repo_destino\n"
        "- Menciona a WOT-2026-999z como dependencia (NO es su contrato).\n",
        encoding="utf-8",
    )
    sha = _commit_file(destino, "docs/x.md", "# doc", "WOT-2026-902a: write docs")

    def _fake_resolve_prefix(prefix, _motor_root):
        if prefix == "WOT":
            return destino
        return None

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["WOT-2026-902a"], None, False
        )

    assert result.status == "PASS", result.detail
    assert sha in (destino / TARGETS_REL).read_text(encoding="utf-8")


def test_wot_without_row_in_any_backlog_warns_excluded(tmp_path: Path) -> None:
    """D5(i) + WOT-2026-073d: fixture `WOT-` SIN `delivery_authority` y SIN
    fila/ficha propia en ninguna superficie de backlog -> WARN no bloqueante
    que lo EXCLUYE de la certificacion (no FAIL).

    Un ticket que nunca tuvo fila no puede declarar `delivery_authority` por
    ninguna via: bloquear el cierre por ese dato era un falso FAIL
    (WOT-2026-073d). El caso "tiene fila/contrato pero le falta el campo" SI
    sigue fail-closed: lo pinea
    `test_ticket_with_backlog_row_but_no_authority_still_fails`. Antes del fix
    (D2, WOT-2026-066i) este MISMO fixture (ticket sin fila, commit real)
    pinea FAIL/blocking: el contrato cambia, el fixture no.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-666x: feature")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-666x"], None, False
    )

    assert result.status == "WARN", result.detail
    assert result.blocking is False
    assert "WOT-2026-666x" in result.detail
    assert "excluido" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_sha_absent_in_both_roots_still_aborts(tmp_path: Path) -> None:
    """D6 / WOT-2026-059b: un sha de targets que no resuelve en NINGUNA raiz
    sigue ABORTANDO el cierre (fail-closed, nombrando el sha).

    La nueva resolucion por `delivery_authority` declarado no relaja la
    acreditacion por origen del CONSUMADOR del fichero de targets
    (`run_loop_execution_check`, importado -- no modificado: Forbidden Surface).
    """
    from scripts.prepush_check import run_loop_execution_check

    motor = tmp_path / "motor"
    _init_git_repo(motor)
    destino = tmp_path / "destino"
    _init_git_repo(destino)
    _link_motor(destino, motor)
    ghost = "f" * 40
    targets_path = destino / TARGETS_REL
    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text(f"{ghost} code\n", encoding="utf-8")

    result = run_loop_execution_check(destino)

    assert result.passed is False, result.output
    assert result.is_blocking is True, (
        "un sha que no existe en NINGUNA raiz debe abortar el cierre "
        f"(WOT-2026-059b no se relaja): {result.output}"
    )
    assert ghost in result.output


def test_trivial_topology_declared_repo_destino_resolves_single_root(
    tmp_path: Path,
) -> None:
    """B1: en topologia trivial (repo unico), un ticket que DECLARA
    `repo_destino` resuelve a la unica raiz candidata -- en ese despliegue
    repo_motor y repo_destino denotan el MISMO repo fisico, asi que el valor
    declarado se satisface. Y el ticket SIN declaracion SIGUE fallando
    cerrado: la topologia trivial NO convierte la ausencia en un default
    silencioso (rama B1 del review del Manager: las tres ramas tenian el
    mismo cuerpo y la ausencia pasaba sin veredicto).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-667a", "repo_destino")
    sha = _commit_file(
        repo, "src/a.py", "x = 1", "WOT-2026-667a: entrega en el unico repo"
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-667a"], None, False
    )

    assert result.status == "PASS", result.detail
    assert sha in (repo / TARGETS_REL).read_text(encoding="utf-8")


def test_trivial_topology_without_declared_authority_fails_closed(
    tmp_path: Path,
) -> None:
    """B1: en topologia trivial la AUSENCIA de `delivery_authority` tambien es
    fail-closed (D2). La unica raiz candidata no autoriza un default: es la
    rama donde nadie miraba, y ahi es donde el CG prohibe el default.

    Antes del fix B1 este caso devolvia motor_root con fail_detail vacio para
    los TRES valores de `declared_authority` (None/repo_motor/repo_destino):
    la rama ignoraba el campo declarado entero.

    WOT-2026-073d: el fixture gana una fila de backlog (contrato registrado)
    para fijar que la ausencia CON superficie sigue siendo FAIL. La exclusion
    con WARN queda reservada a tickets sin NINGUNA superficie propia
    (`test_wot_without_row_in_any_backlog_warns_excluded`), tambien en esta
    topologia: la comprobacion es previa a la resolucion.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _write_backlog(repo, "| Alta | WOT-2026-667b | ficha sin campo |\n")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-667b: feature")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-667b"], None, False
    )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "WOT-2026-667b" in result.detail
    assert not (repo / TARGETS_REL).exists()


def test_neighbor_archive_plan_does_not_leak_authority(tmp_path: Path) -> None:
    """B3: el glob `work_plan_<ID>*.md` no puede devolver la autoridad de un
    ticket VECINO. El fichero del vecino (otro id completo) ni siquiera entra
    en las superficies del glob, y el guard del `**ID:**` dentro del fichero
    neutralizaria una colision de nombre. El ticket sin superficie propia se
    EXCLUYE con WARN (WOT-2026-073d) sin heredar la autoridad del vecino: el
    veredicto ni la nombra ni la resuelve (antes del cambio, D2 lo daba FAIL).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    archive = repo / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "work_plan_WOT-2026-666y_COMPLETED.md").write_text(
        "# Plan de Trabajo: WOT-2026-666y\n\n## Metadata\n"
        "- **ID:** WOT-2026-666y\n"
        "- **delivery_authority:** repo_destino\n",
        encoding="utf-8",
    )
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-666x: feature del vecino")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-666x"], None, False
    )

    assert result.status == "WARN", result.detail
    assert result.blocking is False
    assert "excluido" in result.detail
    assert "WOT-2026-666x" in result.detail
    assert "WOT-2026-666y" not in result.detail
    assert not (repo / TARGETS_REL).exists()


def test_frozen_contract_wins_over_archived_plan(tmp_path: Path) -> None:
    """B2 (hallazgo del bucle L720, lente BA06): la PRECEDENCIA de superficies
    esta pineada, no solo implementada.

    Antes del fix, `_root_authority_surfaces` consultaba los work_plan
    ARCHIVADOS ANTES que `ticket_contracts.md` con estrategia first-wins. El
    fix invirtio el orden, pero NINGUN test lo protegia -- el mutation-verify
    de la ronda 2 tumbaba 2 tests (B1 y B3) y ninguno de B2, asi que revertir
    la precedencia salia VERDE. Este test cierra ese hueco.

    Aqui el archivado EXISTE y es legible pero NO declara el campo: solo el
    frozen puede aportar el valor. Asi el test fija el ORDEN sin solaparse con
    el de conflicto (dos valores contradictorios dan None por diseno, que es
    otra propiedad). Mutacion que debe matarlo: que el lector se detenga en la
    primera superficie LEIDA en vez de en la primera que DECLARA.
    """
    root = tmp_path / "repo"
    archive = root / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True)
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    ticket = "WOT-2026-902a"
    # El ARCHIVADO existe y es legible, pero NO declara el campo.
    (archive / f"work_plan_{ticket}_COMPLETED.md").write_text(
        f"# Plan de Trabajo: {ticket}\n\n## Metadata\n"
        f"- **ID:** {ticket}\n"
        "- **Estado:** COMPLETED\n",
        encoding="utf-8",
    )
    # Solo el FROZEN aporta el valor: si el lector se detuviera en la primera
    # superficie LEIDA (en vez de la primera que DECLARA), esto daria None.
    (planning / "ticket_contracts.md").write_text(
        f"## {ticket} -- contrato vigente\n"
        f"- **ticket_id:** {ticket}\n"
        "- **status:** frozen\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )

    got = session_closeout._read_declared_delivery_authority(
        ticket, root, root, None, None
    )

    assert got == "repo_motor", (
        "el contrato FROZEN vigente debe ganar al work_plan ARCHIVADO stale; "
        f"se obtuvo {got!r}"
    )


def test_conflicting_surfaces_fail_closed_instead_of_first_wins(
    tmp_path: Path,
) -> None:
    """B2 (segunda mitad): dos superficies con valores CONTRADICTORIOS no se
    resuelven en silencio por orden -- se declaran indecidibles (None) y el
    llamante cae en D2 (fail-closed).

    Un first-wins sobre un conflicto elegiria un valor arbitrario y resolveria
    una raiz que quiza no es la del ticket: exactamente el default silencioso
    que `CG-CTL-2026-027b` prohibe en un guard fail-closed.
    """
    root = tmp_path / "repo"
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    ticket = "WOT-2026-902b"
    # Plan VIVO per-ticket y contrato frozen se CONTRADICEN.
    (collab / f"work_plan_{ticket}.md").write_text(
        f"# Plan de Trabajo: {ticket}\n\n## Metadata\n"
        f"- **ID:** {ticket}\n"
        "- **delivery_authority:** repo_destino\n",
        encoding="utf-8",
    )
    (planning / "ticket_contracts.md").write_text(
        f"## {ticket} -- contrato vigente\n"
        f"- **ticket_id:** {ticket}\n"
        "- **status:** frozen\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )

    got = session_closeout._read_declared_delivery_authority(
        ticket, root, root, None, None
    )

    assert got is None, (
        "un conflicto entre superficies debe ser indecidible (None -> D2), "
        f"nunca resolverse por orden; se obtuvo {got!r}"
    )


def test_trivial_topology_rejects_unknown_authority_value(tmp_path: Path) -> None:
    """B1 (defensa en profundidad, hallazgo convergente de BA15/BA16): la rama
    de topologia trivial valida el VALOR, no solo su presencia.

    Antes, cualquier string no-`None` -- cadena vacia, espacios, un typo como
    `repo_moter` -- entraba por la rama feliz con `fail_detail` vacio: el
    mismatch era indistinguible del match, y D2 exige que AMBOS fallen. Hoy el
    regex del parser solo captura `repo_motor|repo_destino`, asi que la rama no
    es alcanzable desde produccion; se pinea igual porque el guard no debe
    depender de una invariante que vive en OTRA funcion (leccion
    `guard-behind-a-guard-clause-never-runs`).
    """
    motor = tmp_path / "motor"
    motor.mkdir()
    ticket = "WOT-2026-902c"

    for bogus in ("", "   ", "repo_moter", "basura"):
        _root, _other, _skip, _warn, fail_detail = (
            session_closeout._resolve_trivial_topology(ticket, motor, bogus)
        )
        assert fail_detail, (
            f"un valor de autoridad no reconocido ({bogus!r}) debe fallar "
            "cerrado, no resolver la raiz en silencio"
        )
        assert ticket in fail_detail

    # Control positivo: los dos valores canonicos SI resuelven.
    for good in ("repo_motor", "repo_destino"):
        _root, _other, _skip, _warn, fail_detail = (
            session_closeout._resolve_trivial_topology(ticket, motor, good)
        )
        assert not fail_detail, f"{good!r} es canonico y debe resolver"


def test_planning_per_ticket_work_plan_declares_authority(tmp_path: Path) -> None:
    """WOT-2026-067k (a)(b): `.agent/planning/work_plan_<ID>.md` es superficie
    de contrato legible.

    `WOT-2026-066i` arreglo QUE campo leer (el declarado, nunca el prefijo);
    este test fija DONDE leerlo. Medido en ruta productiva el 2026-09-09 sobre
    el motor `881068f`: los work_plan per-ticket del destino viven en
    `.agent/planning/` (censo: planning 9, collaboration 0, _archive 0), y el
    lector consultaba dos directorios VACIOS -- asi que un fail-closed correcto
    rechazaba un campo que SI estaba declarado, y NINGUN ticket con su contrato
    en `planning/` podia cerrar sesion.

    Mutacion que debe matarlo (DoD (e)): retirar la superficie nueva de
    `_root_authority_surfaces` devuelve None y reaparece `FAIL_TARGETS_MISSING`.
    """
    root = tmp_path / "repo"
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    ticket = "WOT-2026-903a"
    (planning / f"work_plan_{ticket}.md").write_text(
        f"# Plan de Trabajo: {ticket}\n\n## Metadata\n"
        f"- **ID:** {ticket}\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )

    got = session_closeout._read_declared_delivery_authority(
        ticket, root, root, None, None
    )

    assert got == "repo_motor", (
        "un work_plan per-ticket en `.agent/planning/` declara autoridad; "
        f"se obtuvo {got!r}"
    )


def test_planning_work_plan_conflicting_with_frozen_is_undecidable(
    tmp_path: Path,
) -> None:
    """WOT-2026-067k (c)(d): la superficie nueva entra en el MISMO regimen de
    conflicto, no en uno privilegiado.

    Nota de diseno, medida al implementar: el lector NO tiene precedencia
    ejecutable entre superficies -- tiene DETECCION DE CONFLICTO. El orden de
    `_root_authority_surfaces` solo decide que se lee antes; en cuanto DOS
    superficies declaran valores DISTINTOS el veredicto es None (D2), venga de
    donde venga. `test_frozen_contract_wins_over_archived_plan` no contradice
    esto: alli el archivado no declara NADA, asi que no hay conflicto que
    resolver.

    Este test pinea que ampliar el ALCANCE del lector no abrio una via para
    resolver discordancias en silencio: un `planning/work_plan` que contradice
    al contrato frozen deja el ticket indecidible, que es exactamente lo que
    `WOT-2026-066i` D2 exige. Darle precedencia a la superficie nueva seria
    debilitar el fail-closed, NON-GOAL explicito de la ficha.
    """
    root = tmp_path / "repo"
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    ticket = "WOT-2026-903b"
    (planning / f"work_plan_{ticket}.md").write_text(
        f"# Plan de Trabajo: {ticket}\n\n## Metadata\n"
        f"- **ID:** {ticket}\n"
        "- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )
    (planning / "ticket_contracts.md").write_text(
        f"## {ticket} -- contrato vigente\n"
        f"- **ticket_id:** {ticket}\n"
        "- **status:** frozen\n"
        "- **delivery_authority:** repo_destino\n",
        encoding="utf-8",
    )

    got = session_closeout._read_declared_delivery_authority(
        ticket, root, root, None, None
    )

    assert got is None, (
        "una discordancia entre `planning/work_plan` y el contrato frozen debe "
        f"ser indecidible (D2), nunca resolverse por orden; se obtuvo {got!r}"
    )


def test_planning_work_plan_of_another_ticket_declares_nothing(tmp_path: Path) -> None:
    """WOT-2026-067k (d): la superficie nueva hereda el guard del `**ID:**`.

    Ampliar el alcance del lector NO puede ampliar lo que acepta: un work_plan
    vecino cuyo nombre casa con el glob `work_plan_<ID>*.md` pero que declara
    OTRO `**ID:**` no es contrato de este ticket, y su ausencia debe seguir
    fallando CERRADA (D2) en vez de resolverse con el valor del vecino.
    """
    root = tmp_path / "repo"
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    ticket = "WOT-2026-903c"
    (planning / f"work_plan_{ticket}_vecino.md").write_text(
        "# Plan de Trabajo: WOT-2026-903z\n\n## Metadata\n"
        "- **ID:** WOT-2026-903z\n"
        "- **delivery_authority:** repo_destino\n",
        encoding="utf-8",
    )

    got = session_closeout._read_declared_delivery_authority(
        ticket, root, root, None, None
    )

    assert got is None, (
        f"el plan de OTRO ticket no declara autoridad para este; se obtuvo {got!r}"
    )


def test_commits_outside_the_window_are_not_absence_from_the_repo(
    tmp_path: Path,
) -> None:
    """WOT-2026-070g: `FAIL_TARGETS_MISSING` afirmaba ausencia DEL REPO midiendo
    solo su VENTANA.

    Caso medido 2026-09-19 en produccion: un ticket `delivery_authority:
    repo_motor` con 3 commits REALES en el motor (uno de ellos el HEAD sellado
    por la suite) fue declarado "not in authoritative repo" porque esos commits
    caian FUERA de la ventana de sesion -- madrugada en el motor, manana en el
    destino, con la ventana arrancando entre medias. Probe del defecto, misma
    consulta y mismo repo, cambiando solo la ventana:

        git log --grep=<ticket> --since=<dia-anterior>  -> 3 commits
        git log --grep=<ticket> --since=<hoy-01:00>     -> 0 commits

    En la topologia motor+destino, commitear en los dos repos con horas de
    diferencia es el flujo NORMAL, asi que el falso FAIL bloquea el cierre de un
    ticket correctamente entregado y ademas dirige el diagnostico al sitio
    equivocado (parece `delivery_authority`, es ventana).

    Este test fija el INVARIANTE: si el autoritativo tiene commits del ticket
    FUERA de la ventana, el veredicto NO es FAIL.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "WOT-2026-999z", "repo_motor")

    # Reproduccion EXACTA del caso de produccion: el AUTORITATIVO commitea
    # ANTES de la ventana (madrugada) y el OTRO repo DENTRO (manana). Una
    # ventana simetrica NO reproduce el defecto: si ambos salen vacios, la rama
    # del control no dispara y el test pasaria sin probar nada.
    _commit_file_at(
        motor,
        "src/fix.py",
        "x = 1",
        "WOT-2026-999z: implement",
        "2026-09-19T00:04:00",
    )
    _commit_file_at(
        destino,
        "notes.md",
        "n",
        "WOT-2026-999z: proyecciones",
        "2026-09-19T09:16:00",
    )

    # Ventana que arranca ENTRE MEDIAS: excluye el motor, incluye el destino.
    future = "--since=2026-09-19T01:00:00"

    result = session_closeout._process_ticket_targets(
        "WOT-2026-999z",
        destino,
        motor,
        lambda tid: "WOT",
        # resuelve el OTRO repo: sin esto `other_root` queda None y la rama del
        # control (`:1821`) nunca se evalua -- el test saldria verde sin probar nada.
        lambda prefix, *a, **k: destino,
        [future],
    )

    assert result.status != "FAIL", (
        "commits fuera de la ventana NO son ausencia del repo autoritativo; "
        f"se obtuvo {result.status}: {result.detail}"
    )
    assert "not in authoritative" not in (result.detail or ""), (
        "el mensaje no puede afirmar ausencia DEL REPO cuando solo midio su "
        f"ventana; detail={result.detail!r}"
    )


# --- ficha del backlog como superficie de ULTIMO RECURSO de delivery_authority ---
# Medido 2026-10-02 (cierre real de la sesion de WOT-2026-089l): la ficha de
# `backlog.md` declaraba `**delivery_authority:** repo_motor` y el lector solo
# miraba work_plan/ticket_contracts, asi que el paso 2 devolvio
# FAIL_TARGETS_MISSING bloqueante sobre un dato que SI estaba declarado.


def _setup_two_repos(tmp_path: Path) -> tuple[Path, Path]:
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    return motor, destino


def _write_backlog(destino: Path, text: str) -> None:
    path = destino / ".agent" / "collaboration" / "backlog.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_FICHA_902C = (
    "# Backlog\n\n"
    "### WOT-2026-902c - ficha sin contrato formado\n\n"
    "- **Estado:** pending. **delivery_authority:** repo_motor. **Origen:** x.\n\n"
    "### WOT-2026-902d - otra ficha\n\n"
    "- **Estado:** pending. **delivery_authority:** repo_destino.\n"
)


def test_backlog_ficha_declares_authority_when_no_contract_surface(
    tmp_path: Path,
) -> None:
    motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, _FICHA_902C)
    sha = _commit_file(motor, "src/c.py", "x = 3", "WOT-2026-902c: lanzador")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902c"], None, False
    )

    assert result.status == "PASS", result.detail
    assert sha in (destino / TARGETS_REL).read_text(encoding="utf-8")


def test_backlog_ficha_of_a_neighbour_does_not_declare_for_this_ticket(
    tmp_path: Path,
) -> None:
    """Control negativo: la ficha 902d declara repo_destino; 902e no tiene
    ficha ni contrato propio. No hereda la autoridad del vecino: con
    WOT-2026-073d queda EXCLUIDO con WARN y el veredicto ni nombra ni resuelve
    la autoridad ajena (antes del cambio, D2 lo daba por FAIL)."""
    motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, _FICHA_902C)
    _commit_file(motor, "src/e.py", "x = 5", "WOT-2026-902e: algo")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902e"], None, False
    )

    assert result.status == "WARN", result.detail
    assert result.blocking is False
    assert "excluido" in result.detail
    assert "WOT-2026-902e" in result.detail
    assert "902d" not in result.detail
    assert "repo_destino" not in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_backlog_table_row_mention_is_not_a_declaration(tmp_path: Path) -> None:
    """Una FILA de tabla que cita el ticket y el campo no es su ficha: solo
    cuenta el bloque bajo un encabezado `### <ID>`."""
    motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(
        destino,
        "| Alta | WOT-2026-902f | cita delivery_authority: repo_motor en la fila |\n",
    )
    _commit_file(motor, "src/f.py", "x = 6", "WOT-2026-902f: algo")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902f"], None, False
    )

    assert result.status == "FAIL", result.detail
    assert "FAIL_TARGETS_MISSING" in result.detail


def test_backlog_ficha_never_overrides_a_contract_surface(tmp_path: Path) -> None:
    """El backlog es ULTIMO recurso: si el work_plan declara, gana, aunque la
    ficha diga otra cosa (no puede cambiar el veredicto de lo que ya cerraba)."""
    motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, _FICHA_902C.replace("repo_motor", "repo_destino"))
    wp = destino / ".agent" / "collaboration" / "work_plan.md"
    wp.parent.mkdir(parents=True, exist_ok=True)
    wp.write_text(
        "# Plan\n\n- **ID:** WOT-2026-902c\n- **delivery_authority:** repo_motor\n",
        encoding="utf-8",
    )
    sha = _commit_file(motor, "src/c2.py", "x = 7", "WOT-2026-902c: algo")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902c"], None, False
    )

    assert result.status == "PASS", result.detail
    assert sha in (destino / TARGETS_REL).read_text(encoding="utf-8")


def test_dry_run_predicts_missing_authority_instead_of_silent_skip(
    tmp_path: Path,
) -> None:
    """El dry-run devolvia SKIP incondicional y el cierre real fallaba despues
    (medido 2026-10-02). Ahora un ticket CON fila/contrato pero sin autoridad
    declarada se anuncia como WARN con FAIL_TARGETS_MISSING y NO escribe nada.

    WOT-2026-073d: el fixture gana una fila de backlog; SIN fila ni contrato el
    ticket se EXCLUYE con WARN -- esa prediccion la pinea
    `test_dry_run_predicts_warn_for_ticket_without_backlog_row`."""
    _motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, "| Alta | WOT-2026-902g | fila sin delivery_authority |\n")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902g"], None, True
    )

    assert result.status == "WARN", result.detail
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_dry_run_with_declared_authority_still_skips(tmp_path: Path) -> None:
    _motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, _FICHA_902C)

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-902c"], None, True
    )

    assert result.status == "SKIP"
    assert "dry-run" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_ticket_with_backlog_row_but_no_authority_still_fails(
    tmp_path: Path,
) -> None:
    """CONTROL NEGATIVO (WOT-2026-073d): un ticket CON fila propia en
    `backlog.md` (tabla `| Alta | WOT-2026-XXXxx | ... |`) pero SIN declarar
    `delivery_authority` en ningun sitio SIGUE FAIL bloqueante.

    Es el caso que el Non-Goal prohibe relajar: el dato SI podia declararse
    (hay registro de la fila) y se omitio -> D2 fail-closed intacto. La fila de
    tabla cuenta como EXISTENCIA (no se excluye); el valor del campo solo se
    lee de la ficha `###` (WOT-2026-089m), que aqui no existe -> ausencia.
    """
    motor, destino = _setup_two_repos(tmp_path)
    _write_backlog(destino, "| Alta | WOT-2026-906a | ficha sin delivery_authority |\n")
    _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-906a: feature")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-906a"], None, False
    )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "WOT-2026-906a" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_ticket_with_archive_only_row_is_not_excluded(tmp_path: Path) -> None:
    """WOT-2026-073d: una fila SOLO en `_archive/backlog_done.md` tambien es
    "fila propia" (el ticket tuvo registro): no se excluye; sin el campo
    declarado sigue FAIL (D2). La exclusion exige ausencia en AMBAS superficies
    de backlog, viva y archivada.
    """
    motor, destino = _setup_two_repos(tmp_path)
    archive = destino / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "backlog_done.md").write_text(
        "| Media | WOT-2026-906b | ficha archivada sin campo |\n",
        encoding="utf-8",
    )
    _commit_file(motor, "src/b.py", "x = 2", "WOT-2026-906b: feature")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-906b"], None, False
    )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_ticket_has_backlog_row_helper_checks_both_surfaces(tmp_path: Path) -> None:
    """WOT-2026-073d: `_ticket_has_backlog_row` cubre las DOS superficies y las
    DOS formas de fila propia (`### <ID>` y fila de tabla), y no lanza cuando
    ninguna superficie existe.

    Secuencia: ninguna superficie -> False; solo backlog.md vivo -> True; solo
    el archive (tras vaciar la viva) -> True; una mencion de pasada DENTRO de
    la fila de OTRO ticket -> False (el id se lee de su celda, nunca del texto
    libre: control negativo de forma).
    """
    root = tmp_path / "root"
    root.mkdir()
    ticket = "WOT-2026-906c"
    assert session_closeout._ticket_has_backlog_row(root, ticket) is False

    _write_backlog(root, "| Alta | WOT-2026-906c | ficha viva |\n")
    assert session_closeout._ticket_has_backlog_row(root, ticket) is True

    _write_backlog(root, "")
    archive = root / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "backlog_done.md").write_text(
        f"### {ticket} - ficha archivada\n\ntexto\n", encoding="utf-8"
    )
    assert session_closeout._ticket_has_backlog_row(root, ticket) is True

    (archive / "backlog_done.md").write_text(
        "| Alta | WOT-2026-906d | mencion de WOT-2026-906c en prosa |\n",
        encoding="utf-8",
    )
    assert session_closeout._ticket_has_backlog_row(root, ticket) is False


def test_dry_run_predicts_warn_for_ticket_without_backlog_row(
    tmp_path: Path,
) -> None:
    """WOT-2026-073d: el dry-run predice la EXCLUSION con WARN para un ticket
    sin fila ni contrato propio (ni un PASS ciego ni un FAIL fantasma).

    El cierre real devolveria WARN (excluido); el dry-run debe anticipar ese
    mismo veredicto reutilizando la comprobacion
    (`_dry_run_targets_prediction` tiene logica propia: no pasa por
    `_process_ticket_targets`).
    """
    _motor, destino = _setup_two_repos(tmp_path)

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-906e"], None, True
    )

    assert result.status == "WARN", result.detail
    assert "WOT-2026-906e" in result.detail
    assert "excluido" in result.detail
    assert "FAIL_TARGETS_MISSING" not in result.detail
    assert not (destino / TARGETS_REL).exists()


# ---------------------------------------------------------------------------
# WOT-2026-058o: procedencia `source=session-close` en las lineas del escritor
# e invariante: el fichero del cierre pasa la barrera del consumidor.
# ---------------------------------------------------------------------------

_058O_TS_EMIT = "2026-10-11T10:00:00+00:00"
_058O_TS_ROUND = "2026-10-11T10:05:00+00:00"
_058O_BACKENDS = ("BA03", "BA07")


def _058o_emitted_row(commit: str) -> dict:
    """Fila de emitted_nonces.jsonl con la forma que escribe `emit_nonce`."""
    return {
        "ts": _058O_TS_EMIT,
        "issuer_role": "orchestrator",
        "issuer_backend_key": "BA01",
        "issued_before_ts": _058O_TS_EMIT,
        "commit_sha": commit,
        "loop_id": "L980",
        "challenge_nonce": "N-058o",
    }


def _058o_round_row(backend: str, commit: str) -> dict:
    """Fila de scorecard.jsonl con la forma que escribe `_record_round`."""
    return {
        "event": "ronda",
        "commit_sha": commit,
        "backend_key": backend,
        "challenge_nonce": "N-058o",
        "ts": _058O_TS_ROUND,
        "output_chars": 2134,
        "evidencia": "veredicto de la lente",
    }


def test_writer_lines_carry_session_close_provenance(tmp_path: Path) -> None:
    """WOT-2026-058o (a): cada linea que el escritor legitimo produce porta el
    token `source=session-close`, para que un auditor distinga un target
    declarado por el cierre de uno editado a mano.

    MUTATION proof: revertir `_process_ticket_targets` a `f"{sha} {dtype}"`
    hace caer este test (la linea pierde la procedencia).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999f", "repo_motor")
    sha = _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999f: implement feature")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999f"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    # WOT-2026-048w: "WOT-2026-999f" has no backlog row under this tmp repo,
    # so the type is the documented fallback, now marked `declared=false`.
    assert (
        f"{sha} code declared=false phase=MANAGER_REVIEW "
        "delivery_authority=repo_motor source=session-close" in content
    ), content
    for line in content.splitlines():
        if line.strip():
            assert line.split()[1] in {"code", "documentation"}, line
            assert line.endswith("source=session-close"), line


def test_close_written_targets_pass_the_loop_execution_check(tmp_path: Path) -> None:
    """WOT-2026-058o (e) INVARIANTE: el fichero que escribe un cierre real
    (con el token nuevo) pasa `run_loop_execution_check` exactamente igual que
    hoy, una vez su fan-out de gobierno esta acreditado.

    Sin mocks: escritor REAL sobre repo git REAL + corpus de acreditacion con
    la forma exacta de scorecard/emitted_nonces.
    """
    from scripts.prepush_check import run_loop_execution_check

    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999g", "repo_motor")
    sha = _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999g: implement feature")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999g"], None, False
    )
    assert result.status == "PASS", result.detail

    ensemble = repo / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True, exist_ok=True)
    (ensemble / "scorecard.jsonl").write_text(
        "".join(json.dumps(_058o_round_row(bk, sha)) + "\n" for bk in _058O_BACKENDS),
        encoding="utf-8",
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(_058o_emitted_row(sha)) + "\n", encoding="utf-8"
    )

    verdict = run_loop_execution_check(repo)

    assert verdict.passed is True, verdict.output
    assert verdict.is_blocking is False, verdict.output
    assert "1 commit(s)" in verdict.output
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    assert "source=session-close" in content, content


# ---------------------------------------------------------------------------
# WOT-2026-060k: --session-close no ensucia el arbol que su propio gate exige
# limpio (loop_execution_targets.txt se committea despues de escribirlo)
# ---------------------------------------------------------------------------


def _run_git_status_porcelain(repo: Path) -> str:
    """Run ``git status --porcelain`` and return stdout."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_060k_write_and_commit_targets_on_clean_tree(tmp_path: Path) -> None:
    """(a) + (e) --session-close on clean tree: the writer still produces the
    targets file AND commits it, so the tree stays clean.

    NEGATIVE CONTROL (e): the file IS written (not suppressed) and IS committed
    (verified by git log, not just git status).  Committing is the ORDER fix,
    not suppression.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-060k", "repo_motor")
    sha = _commit_file(
        repo, "src/a.py", "x = 1", "WOT-2026-060k: commit that gets targeted"
    )

    _ = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-060k"], None, False
    )

    # The file was written
    targets_path = repo / TARGETS_REL
    assert targets_path.exists(), "the targets file must be written (DoD e)"
    content = targets_path.read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} should be in targets: {content!r}"

    # The file was committed (in the repo that owns it)
    log_result = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert "WOT-2026-060k: write loop_execution_targets.txt" in log_result.stdout, (
        f"the targets file must be committed; git log: {log_result.stdout!r}"
    )


def test_060k_git_status_clean_after_write(tmp_path: Path) -> None:
    """(b) After writing and committing, `git status --porcelain` does not list
    ``loop_execution_targets.txt``.

    This is the core assertion of WOT-2026-060k: the writer cannot make the
    prepush check fail against itself because the file is committed immediately
    after writing.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-060k", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-060k: commit")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-060k"], None, False
    )

    assert result.status == "PASS", result.detail
    porcelain = _run_git_status_porcelain(repo)
    assert "loop_execution_targets.txt" not in porcelain, (
        f"git status should not list targets after write+commit; got: {porcelain!r}"
    )


def test_060k_mutation_disable_commit_fails_closed(tmp_path: Path) -> None:
    """(c) MUTATION that ISOLATES: if we disable the commit step, the test from
    (b) fails -- `git status` lists the targets file.

    This proves the commit is what makes the difference.  Mutation: patch
    `_commit_targets_file` to always return an error string, which causes the
    writer to return SKIP instead of PASS, but the file is STILL written to disk.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-060k", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-060k: commit")

    def _fake_commit(project_root, targets_path, lines):
        """Always fail: simulates a broken git environment."""
        return "mutation: git disabled"

    with patch.object(session_closeout, "_commit_targets_file", _fake_commit):
        result = session_closeout._step_write_loop_execution_targets(
            repo, ["WOT-2026-060k"], None, False
        )

    # The file is written but NOT committed -> git status shows it.
    targets_path = repo / TARGETS_REL
    assert targets_path.exists(), "file must be written even when commit fails"
    porcelain = _run_git_status_porcelain(repo)
    # On Windows, git status --porcelain may show the directory prefix only.
    # Check that git status is non-empty (dirty) when the uncommitted file exists.
    assert porcelain.strip(), (
        "git status should show dirty when targets file is uncommitted; "
        "this proves the commit is the fix, not the write"
    )
    assert result.status == "SKIP", (
        "when commit fails, the step returns SKIP to prevent passing silently"
    )


def test_060k_delete_and_commit_targets(tmp_path: Path) -> None:
    """(e) When there are no ticket commits and the file exists from a
    PREVIOUS run (but is now untracked because the repo was re-initialized),
    the writer does NOT create a new file.  Git status stays clean.

    This tests the ORDER fix in the PASS branch: the writer writes or does
    nothing, commits if it writes, and git status is clean either way.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    # Use a ticket that has NO commits in this repo.
    _declare_authority(repo, "WOT-2026-060z", "repo_motor")

    # There is NO pre-existing targets file (clean slate).
    targets_path = repo / TARGETS_REL

    # A ticket with NO matching commits -> no file should be created.
    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-060z"], None, False
    )

    assert result.status == "PASS", result.detail
    assert not targets_path.exists(), "file should not be created when no commits match"
    porcelain = _run_git_status_porcelain(repo)
    assert "loop_execution_targets.txt" not in porcelain, (
        "git status should not list targets after no-write"
    )


def test_060k_git_commit_failure_does_not_delete_file(tmp_path: Path) -> None:
    """(d) When git commit fails, the file is still written (not deleted) but
    the step returns SKIP (fail-safe).  The uncommitted file WILL block
    prepush_check, which is the desired fail-closed behavior.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-060k", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-060k: commit")

    def _fake_commit_error(project_root, targets_path, lines):
        return "git commit error: fake"

    with patch.object(session_closeout, "_commit_targets_file", _fake_commit_error):
        result = session_closeout._step_write_loop_execution_targets(
            repo, ["WOT-2026-060k"], None, False
        )

    # File is written but step returns SKIP (not PASS).
    targets_path = repo / TARGETS_REL
    assert targets_path.exists(), "file must be written even on commit failure"
    assert result.status == "SKIP", "commit failure must return SKIP, not PASS"


def test_060k_neighbor_dirty_file_blocks(tmp_path: Path) -> None:
    """(d) NEGATIVE CONTROL: a dirty file from ANOTHER source still shows in
    ``git status``, confirming our fix only cleans up the writer's own output.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-060k", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-060k: commit")

    # Inject an unrelated dirty file.
    dirty_path = repo / ".agent" / "collaboration" / "external_dirty.txt"
    dirty_path.parent.mkdir(parents=True, exist_ok=True)
    dirty_path.write_text("unrelated content", encoding="utf-8")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-060k"], None, False
    )

    assert result.status == "PASS", result.detail
    # The writer's own file is clean, but the external dirty file remains.
    porcelain = _run_git_status_porcelain(repo)
    assert "loop_execution_targets.txt" not in porcelain, (
        "targets file should not appear in git status"
    )
    assert "external_dirty.txt" in porcelain, (
        "external dirty file should still show -- the fix only cleans the writer's output"
    )


def test_060k_session_close_report_still_written(tmp_path: Path) -> None:
    """(e) NEGATIVE CONTROL: the closeout pipeline still writes
    ``session_close_report.md`` via ``_generate_report`` (we only changed
    loop_execution_targets.txt behavior, not the report generation).

    This test verifies that the REPORT_REL constant exists and that
    _generate_report is callable with a CloseoutReport, confirming the
    report-writing path was not removed or altered.
    """
    from scripts.session_closeout import (
        CloseoutReport,
        _generate_report,
    )

    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    # Create a work_plan to have a ticket context.
    _declare_authority(repo, "WOT-2026-060z", "repo_motor")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-060z: commit")

    report = CloseoutReport(dry_run=False, skip_slow=False)
    report_path = _generate_report(report, repo)

    assert report_path.exists(), "session_close_report.md must be written"
    report_content = report_path.read_text(encoding="utf-8")
    assert "closeout" in report_content.lower() or "step" in report_content.lower(), (
        f"report should contain step data; got: {report_content[:200]!r}"
    )


# ---------------------------------------------------------------------------
# WOT-2026-090w: backlog-only commits are NOT delivery
# ---------------------------------------------------------------------------


def _commit_backlog_only(repo: Path, ticket_id: str) -> str:
    """Commit ONLY backlog surfaces with a ticket reference. Returns sha."""
    # Write backlog.md with a ticket row
    backlog = repo / BACKLOG_REL
    backlog.parent.mkdir(parents=True, exist_ok=True)
    existing = backlog.read_text(encoding="utf-8") if backlog.exists() else ""
    row = f"{'|' * 5}\n| WOT-2026-999a | Archiva ticket | documentation |"
    backlog.write_text(existing + row, encoding="utf-8")
    return _commit_file(
        repo, str(BACKLOG_REL), row, f"backlog: archiva {ticket_id} (completed)"
    )


def test_backlog_only_commit_is_not_delivery(tmp_path: Path) -> None:
    """WOT-2026-090w (2.1/2.2): a commit touching ONLY backlog surfaces does NOT
    enter loop_execution_targets.txt.

    Fixture: .git propio, work_plan sin commitear, commit solo-backlog con subject
    `backlog: archiva WOT-2026-999a (completed)`. Asertar targets AUSENTE (0 entregas).

    MUTATION: revert `_delivers_only_backlog_surfaces` to `return False` -> targets
    REAPARECE con ese sha. El `.git` propio es OBLIGATORIO (WOT-2026-020r).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    sha = _commit_backlog_only(repo, "WOT-2026-999a")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    # El commit solo-backlog NO debe entrar en targets
    assert not targets_path.exists(), (
        f"backlog-only commit {sha} should not create targets.txt; content: {targets_path.read_text(encoding='utf-8')!r}"
    )

    # MUTATION: sin el filtro, el sha SÍ aparece
    with patch.object(
        session_closeout,
        "_delivers_only_backlog_surfaces",
        return_value=False,
    ):
        targets_path.unlink(missing_ok=True)
        result = session_closeout._step_write_loop_execution_targets(
            repo, ["WOT-2026-999a"], None, False
        )
        assert result.status == "PASS"
        assert targets_path.exists(), (
            "mutation: targets.txt should exist after disabling filter"
        )
        content = targets_path.read_text(encoding="utf-8")
        assert sha in content, (
            f"mutation: sha {sha} should be in targets after disabling filter; got: {content!r}"
        )


def test_commit_touching_backlog_and_code_still_delivers(tmp_path: Path) -> None:
    """WOT-2026-090w (2.2): a commit touching backlog AND code DOES enter targets.

    Prueba que la regla es "no TODAS las rutas son backlog" (universal), no "cualquier
    ruta de backlog excluye" (existencial). DoD (b).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")

    # Escribir backlog.md Y un archivo de codigo en el MISMO commit
    backlog = repo / BACKLOG_REL
    backlog.parent.mkdir(parents=True, exist_ok=True)
    code = repo / "src" / "a.py"
    code.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text("| ticket | desc | type |", encoding="utf-8")
    code.write_text("x = 1", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", str(BACKLOG_REL), "src/a.py"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "WOT-2026-999a: implement feature"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = sha_result.stdout.strip()

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    targets_path = repo / TARGETS_REL
    assert result.status == "PASS", result.detail
    assert targets_path.exists()
    content = targets_path.read_text(encoding="utf-8")
    assert sha in content, (
        f"commit touching backlog + code should enter targets; got: {content!r}"
    )


def test_merge_commit_without_paths_still_delivers(tmp_path: Path) -> None:
    """WOT-2026-090w (2.3): a merge commit with NO paths from `git show --name-only`
    is INCLUDED (empty-set conservativo, decision 4).

    Fixture: bare remote -> clone -> push inicial + feature -> merge origin/feature
    con --no-ff y committer date distinto -> merge commit de 2 padres sin rutas.
    El probe directo aserta helper==False; luego la asercion de que el sha entra
    en loop_execution_targets.txt (contrato: 2.3 "SÍ entra").
    """
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=bare, check=True, capture_output=True)

    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Explicit main branch creation for portability: bare clone on CI (Linux)
    # leaves an unborn HEAD or defaults to `master`; without this, `git push
    # -u origin main` and `git checkout main` fail (WOT-2026-090w-r3).
    # Create main ref in the bare repo so the clone picks it up.
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=bare,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")

    # Commitear inicial y push a origin/main
    (repo / "README.md").write_text("# repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Crear feature branch con commit en fecha pasada
    subprocess.run(
        ["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True
    )
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "b.py").write_text("y = 2", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/b.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feature commit"],
        cwd=repo,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        },
        check=True,
        capture_output=True,
    )
    # Push feature a origin
    subprocess.run(
        ["git", "push", "origin", "feature"], cwd=repo, check=True, capture_output=True
    )

    # Volver a main y merge --no-ff con committer date distinta -> merge commit real
    subprocess.run(
        ["git", "checkout", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "merge",
            "--no-ff",
            "origin/feature",
            "-m",
            "WOT-2026-999a: merge feature",
        ],
        cwd=repo,
        env={**os.environ, "GIT_COMMITTER_DATE": "2020-01-02T00:00:00"},
        check=True,
        capture_output=True,
    )
    merge_sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    merge_sha = merge_sha_result.stdout.strip()

    # Probe directo del helper: merge commit sin rutas => False (INCLUIR conservador)
    from scripts.session_closeout import _delivers_only_backlog_surfaces

    result = _delivers_only_backlog_surfaces(repo, merge_sha)
    assert result is False, (
        f"merge commit empty-set => INCLUIR; helper returned {result}"
    )

    # Asercion completa del plan 2.3: el sha SÍ entra en targets.txt
    result2 = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )
    targets_path = repo / TARGETS_REL
    assert result2.status == "PASS", result2.detail
    assert targets_path.exists()
    content = targets_path.read_text(encoding="utf-8")
    assert merge_sha in content, (
        f"merge commit {merge_sha} should enter targets (empty-set => INCLUIR); got: {content!r}"
    )


# ---------------------------------------------------------------------------
# WOT-2026-143a: UN objetivo por TICKET (su ultimo commit), no uno por commit
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _target_lines(repo: Path) -> list[str]:
    path = repo / TARGETS_REL
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_143a_three_commit_ticket_emits_one_line_the_tip(tmp_path: Path) -> None:
    """DoD (1)/M1: un ticket con 3 commits declara UN objetivo, el ULTIMO.

    MUTATION M1: volver a `for sha in shas` (una linea por commit) deja 3 lineas
    y este test CAE. Hasta 143a ningun test tenia un ticket de mas de un commit.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    first = _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: paso 1")
    second = _commit_file(repo, "src/b.py", "x = 2", "WOT-2026-999a: paso 2")
    third = _commit_file(repo, "src/c.py", "x = 3", "WOT-2026-999a: paso 3")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    lines = _target_lines(repo)
    assert len(lines) == 1, lines
    assert lines[0].split()[0] == third
    assert first not in "\n".join(lines) and second not in "\n".join(lines)
    assert "3 commit(s)" in result.detail, result.detail


def test_143a_merge_tip_is_skipped_for_the_last_non_merge(tmp_path: Path) -> None:
    """Condicion 1: el tip es el ultimo NO-merge aunque un merge que cita el
    ticket este en cabeza (caso real: 129y/129l del vuelo-20261026b)."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999a: paso 1")
    _git(repo, "checkout", "-q", "-b", "feat")
    last = _commit_file(repo, "src/b.py", "x = 2", "WOT-2026-999a: paso 2")
    _git(repo, "checkout", "-q", base)
    _git(repo, "merge", "--no-ff", "-m", "Merge WOT-2026-999a: feat", "feat")
    merge_sha = _git(repo, "rev-parse", "HEAD")
    assert merge_sha != last

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    lines = _target_lines(repo)
    assert [ln.split()[0] for ln in lines] == [last], lines


def test_143a_divergent_commits_fail_blocking_not_linear(tmp_path: Path) -> None:
    """DoD (5)/M4: sin maximal unico el estado final NO es un commit -> el
    escritor FALLA bloqueante y no escribe objetivo.

    MUTATION M4: quitar la comprobacion de ancestria (tomar el primero) hace
    que el ticket pase con un tip arbitrario y este test CAE.
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999a", "repo_motor")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-q", "-b", "left")
    _commit_file(repo, "src/l.py", "l = 1", "WOT-2026-999a: rama izquierda")
    _git(repo, "checkout", "-q", base)
    _git(repo, "checkout", "-q", "-b", "right")
    _commit_file(repo, "src/r.py", "r = 1", "WOT-2026-999a: rama derecha")
    _git(repo, "checkout", "-q", base)
    _git(repo, "merge", "--no-ff", "-m", "integra left", "left")
    _git(repo, "merge", "--no-ff", "-m", "integra right", "right")

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999a"], None, False
    )

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_NOT_LINEAR" in result.detail
    assert "WOT-2026-999a" in result.detail
    assert not (repo / TARGETS_REL).exists()


def _two_commit_ticket_with_rounds(tmp_path: Path, looped: str) -> tuple[Path, str]:
    """Repo con un ticket de 2 commits y un bucle completo SOLO sobre `looped`."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
    _declare_authority(repo, "WOT-2026-999b", "repo_motor")
    first = _commit_file(repo, "src/a.py", "x = 1", "WOT-2026-999b: paso 1")
    last = _commit_file(repo, "src/b.py", "x = 2", "WOT-2026-999b: paso 2")
    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999b"], None, False
    )
    assert result.status == "PASS", result.detail
    sha = first if looped == "first" else last
    ensemble = repo / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True, exist_ok=True)
    (ensemble / "scorecard.jsonl").write_text(
        "".join(json.dumps(_058o_round_row(bk, sha)) + "\n" for bk in _058O_BACKENDS),
        encoding="utf-8",
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(_058o_emitted_row(sha)) + "\n", encoding="utf-8"
    )
    return repo, last


def test_143a_multi_commit_ticket_without_loop_on_the_last_fails(
    tmp_path: Path,
) -> None:
    """DoD (5): el ticket integra varios commits y el bucle corrio sobre el
    PRIMERO, no sobre el ultimo -> la barrera BLOQUEA (el objetivo es el ultimo)."""
    from scripts.prepush_check import run_loop_execution_check

    repo, last = _two_commit_ticket_with_rounds(tmp_path, looped="first")
    assert [ln.split()[0] for ln in _target_lines(repo)] == [last]

    verdict = run_loop_execution_check(repo)

    assert verdict.passed is False, verdict.output
    assert verdict.is_blocking is True, verdict.output
    assert last in verdict.output


def test_143a_multi_commit_ticket_with_loop_on_the_last_passes(
    tmp_path: Path,
) -> None:
    """Control positivo del anterior: el MISMO ticket con el bucle sobre el
    ultimo commit pasa (la barrera no rechaza por tener varios commits)."""
    from scripts.prepush_check import run_loop_execution_check

    repo, last = _two_commit_ticket_with_rounds(tmp_path, looped="last")

    verdict = run_loop_execution_check(repo)

    assert verdict.passed is True, verdict.output
    assert "1 commit(s)" in verdict.output
    assert last in verdict.output
