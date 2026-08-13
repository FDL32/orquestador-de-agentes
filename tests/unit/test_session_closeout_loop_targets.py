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
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


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
    sha = _commit_file(
        repo, "src/b.py", "y = 2", "WOT-2026-999c: implement without backlog row"
    )

    result = session_closeout._step_write_loop_execution_targets(
        repo, ["WOT-2026-999c"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (repo / TARGETS_REL).read_text(encoding="utf-8")
    assert f"{sha} code" in content, content


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_rewrite_no_duplicates(tmp_path: Path) -> None:
    """Two consecutive runs with no new commits produce identical content."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
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


# ---------------------------------------------------------------------------
# WOT-2026-048b: two-repo prefix-aware resolution
# ---------------------------------------------------------------------------


def test_non_wot_ticket_commits_in_destino(tmp_path: Path) -> None:
    """Non-WOT ticket with commits in the destino (resolved by prefix) but
    NOT in the motor -> PASS with targets written.

    The writer must resolve the authoritative repo by prefix, not always
    use motor_root.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)

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
    """Non-WOT ticket with commits in the motor (wrong repo) but NOT in the
    destino -> FAIL_TARGETS_MISSING.

    The control query detects commits in the non-authoritative repo.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)

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
    """WOT ticket with commits in the motor (correct) but NOT in the
    destino -> PASS. WOT is special: always resolves to motor_root.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)

    sha = _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-999a: feature")

    result = session_closeout._step_write_loop_execution_targets(
        destino, ["WOT-2026-999a"], None, False
    )

    assert result.status == "PASS", result.detail
    content = (destino / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content, f"sha {sha} missing from {content!r}"


def test_unresolvable_prefix_gives_warn(tmp_path: Path) -> None:
    """A ticket with an unresolvable prefix -> WARN, ticket skipped, no file."""
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)

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

    assert result.status == "WARN", result.detail
    assert "WARN_PREFIX_UNRESOLVABLE" in result.detail
    assert not (destino / TARGETS_REL).exists()


def test_control_query_skipped_when_same_repo(tmp_path: Path) -> None:
    """When resolve_prefix returns the same path as motor_root, the control
    query is skipped (same repo = no meaningful 'other' to check).
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)

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


def test_mixed_results_one_warn_one_pass(tmp_path: Path) -> None:
    """Two tickets: one with unresolvable prefix (WARN), one WOT with commits
    (PASS). The overall status is WARN, and the file is written for the
    resolved ticket only.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)

    sha = _commit_file(motor, "src/a.py", "x = 1", "WOT-2026-999c: feature")

    def _fake_resolve_prefix(prefix, _motor_root):
        return None  # all non-WOT fail

    with (
        patch("scripts.prefix_resolver.resolve_prefix", _fake_resolve_prefix),
        patch("scripts.prefix_resolver.extract_prefix", lambda t: t.split("-")[0]),
    ):
        result = session_closeout._step_write_loop_execution_targets(
            destino, ["ZZZ-2026-001", "WOT-2026-999c"], None, False
        )

    assert result.status == "WARN", result.detail
    assert "WARN_PREFIX_UNRESOLVABLE" in result.detail
    content = (destino / TARGETS_REL).read_text(encoding="utf-8")
    assert sha in content
