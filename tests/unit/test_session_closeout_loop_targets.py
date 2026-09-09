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
    assert f"{sha} code" in content, content


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


def test_unresolvable_prefix_without_declared_authority_fails_closed(
    tmp_path: Path,
) -> None:
    """Ticket con prefijo no resoluble y SIN `delivery_authority` declarado
    -> FAIL blocking, nombrando el ticket.

    WOT-2026-066i (D2): la rama WARN-skip de prefijo no resoluble queda
    RETIRADA -- la ausencia del campo declarado es fail-closed (el censo D5 del
    contrato: los tickets sin campo "caen en D2"). Un skip silencioso dejaria
    fuera del ambito los commits de un ticket que el cierre no sabe donde
    buscar: el falso verde exacto que D2 impide. (Antes de 066i este caso
    devolvia WARN_PREFIX_UNRESOLVABLE; ver execution_log del ticket.)
    """
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
    """Two tickets: one WITHOUT declared authority (D2 -> FAIL), one WOT
    DECLARING repo_motor with commits (PASS). Overall status is FAIL
    blocking, the detail names the failed ticket, and the targets file is
    NOT written (a batch with a misresolved ticket writes no partial scope).

    WOT-2026-066i: antes de D2 el ticket sin campo daba WARN
    (WARN_PREFIX_UNRESOLVABLE) y el mixto salia WARN con fichero escrito; la
    ausencia declarada ahora es fail-closed.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    _init_git_repo(motor)
    _init_git_repo(destino)
    _link_motor(destino, motor)
    _declare_authority(destino, "WOT-2026-999c", "repo_motor")

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


def test_wot_without_declared_authority_fails_closed(tmp_path: Path) -> None:
    """D5(i): fixture `WOT-` SIN `delivery_authority` declarado -> FAIL
    blocking nombrando el ticket.

    Con el caso especial hardcodeado vivo, el ticket resolveria motor_root y
    daria PASS: este test MATA el hardcode por comportamiento (no por grep).
    Bajo D2, la ausencia del campo declarado es fail-closed (un default
    silencioso esta prohibido en un guard fail-closed; WOT-2026-066i D2).
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

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "WOT-2026-666x" in result.detail
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
    """
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _link_motor(repo, repo)
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
    neutralizaria una colision de nombre. El ticket sin declaracion propia
    cae en D2 (FAIL), nunca hereda la del vecino.
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

    assert result.status == "FAIL", result.detail
    assert result.blocking is True
    assert "FAIL_TARGETS_MISSING" in result.detail
    assert "WOT-2026-666x" in result.detail
    assert "WOT-2026-666y" not in result.detail


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
