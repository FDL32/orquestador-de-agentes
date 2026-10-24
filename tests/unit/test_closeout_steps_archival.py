"""Tests for closeout_steps.archival.step_archive_execution_log (WOT-2026-068c).

The step used to translate ANY ``returncode == 0`` of archive_execution_log.py
into ``status="PASS"`` with the static detail ``"Execution log archived"``,
ignoring the producer protocol ``COUNTS archived=N recognized=N present=N``
(WOT-2026-068d): an archiver that runs, does not fail, and recognizes zero
headers (present > 0, recognized == 0) was reported as silent success.

The fakes follow the real fixture pattern of tests/test_session_closeout.py
(run_script_fn returning an object with returncode/stdout/stderr, matching
support.run_script which uses capture_output=True, text=True).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.closeout_steps.archival import step_archive_execution_log
from scripts.session_closeout import StepResult


def fake_run_script_fn(returncode: int, stdout: str):
    """Build a run_script_fn fake with the given returncode and stdout."""

    def run_script_fn(script_name, args, project_root, timeout=60):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return run_script_fn


def _run(run_script_fn) -> StepResult:
    return step_archive_execution_log(
        Path("unused"),
        False,
        run_script_fn=run_script_fn,
        step_result_cls=StepResult,
    )


def test_step_archive_execution_log_warn_on_unrecognized_headers() -> None:
    """present=23, recognized=0 with rc=0: WARN, never a silent PASS.

    REGRESSION (WOT-2026-068c): before the fix this returned PASS with the
    static detail, hiding the real denominator.
    """
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=0 recognized=0 present=23\n"
            "SKIPPED []\n"
            "CONTENT state=nonempty\n",
        )
    )
    assert result.status == "WARN"
    assert "archived=0" in result.detail
    assert "recognized=0" in result.detail
    assert "present=23" in result.detail


def test_step_archive_execution_log_pass_on_empty_log() -> None:
    """present=0 (nothing to archive): PASS -- idempotency is legitimate."""
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=0 recognized=0 present=0\n"
            "SKIPPED []\n"
            "CONTENT state=empty\n",
        )
    )
    assert result.status == "PASS"
    assert "archived=0" in result.detail
    assert "recognized=0" in result.detail
    assert "present=0" in result.detail


def test_step_archive_execution_log_pass_on_recognized_headers() -> None:
    """present=5, recognized=5 (healthy case): PASS.

    POSITIVE CONTROL: without this assert, a wrong implementation like
    ``if present > 0: WARN`` (which ignores `recognized` entirely) would pass
    the other four tests and emit false WARNs for every healthy log in
    production.
    """
    result = _run(
        fake_run_script_fn(
            0,
            "COUNTS archived=5 recognized=5 present=5\n"
            "SKIPPED []\n"
            "CONTENT state=nonempty\n",
        )
    )
    assert result.status == "PASS"
    assert "archived=5" in result.detail
    assert "recognized=5" in result.detail
    assert "present=5" in result.detail


def test_step_archive_execution_log_fallback_missing_protocol() -> None:
    """stdout without a COUNTS line: degrade to the returncode criterion."""
    result = _run(fake_run_script_fn(0, "legacy producer output\n"))
    assert result.status == "PASS"
    assert result.detail == "Execution log archived"


def test_step_archive_execution_log_fallback_malformed_counts_line() -> None:
    """A COUNTS line that does not match the exact regex is the SAME as an
    absent protocol: degrade to returncode, never raise.

    ``re.match`` returns None for a missing `present` field or a non-numeric
    value; the consumer must not assume `match` always exists.
    """
    malformed_lines = (
        "COUNTS archived=0 recognized=0\n",
        "COUNTS archived=abc recognized=0 present=0\n",
    )
    for stdout in malformed_lines:
        result = _run(fake_run_script_fn(0, stdout))
        assert result.status == "PASS", stdout
        assert result.detail == "Execution log archived", stdout


# ---------------------------------------------------------------------------
# step_archive_event_bus (WOT-2026-088f)
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402

from scripts.closeout_steps.archival import (  # noqa: E402
    _archived_ticket_ids_from_stdout,
    step_archive_event_bus,
)


def _archive_stdout(results: list[dict]) -> str:
    return _json.dumps({"status": "ok", "results": results})


def _run_archive_event_bus(run_script_fn, git_add_fn) -> StepResult:
    return step_archive_event_bus(
        Path("unused"),
        False,
        run_script_fn=run_script_fn,
        step_result_cls=StepResult,
        git_add_fn=git_add_fn,
    )


def test_archived_ticket_ids_from_stdout_filters_zero_counts() -> None:
    """A ticket present in the bus with 0 events archived yields no new file."""
    stdout = _archive_stdout(
        [
            {"ticket_id": "WOT-2026-086f", "archived_count": 12},
            {"ticket_id": "WOT-2026-999z", "archived_count": 0},
        ]
    )
    assert _archived_ticket_ids_from_stdout(stdout) == ["WOT-2026-086f"]


def test_archived_ticket_ids_from_stdout_malformed_degrades_to_empty() -> None:
    for bad in (None, "", "not json", _json.dumps({"status": "ok"})):
        assert _archived_ticket_ids_from_stdout(bad) == []


def test_step_archive_event_bus_versions_each_archived_ticket() -> None:
    """REGRESSION target (WOT-2026-088f): the step must 'git add -f' the
    rotated archive of every terminal ticket, not just run the rotation.

    Before the fix, step_archive_event_bus only inspected `returncode`: a
    clean clone that never had the gitignored archive locally failed
    `agent_controller --validate` with 'Missing BUILDER_EXIT/STATE_CHANGED',
    fixed by hand 7 times (dcea6fb, 7190bad, among them) before this test.
    """
    added: list[str] = []

    def fake_git_add(project_root: Path, rel_path: str) -> bool:
        added.append(rel_path)
        return True

    run_script_fn = fake_run_script_fn(
        0,
        _archive_stdout(
            [
                {"ticket_id": "WOT-2026-086f", "archived_count": 21},
                {"ticket_id": "WOT-2026-061e", "archived_count": 5},
            ]
        ),
    )
    result = _run_archive_event_bus(run_script_fn, fake_git_add)

    assert result.status == "PASS"
    assert sorted(added) == [
        ".agent/runtime/events/archive/events.WOT-2026-061e.jsonl",
        ".agent/runtime/events/archive/events.WOT-2026-086f.jsonl",
    ]
    assert "WOT-2026-086f" in result.detail
    assert "WOT-2026-061e" in result.detail


def test_step_archive_event_bus_mutation_without_git_add_no_longer_versions() -> None:
    """MUTATION (DoD b): remove the git-add call -> nothing gets versioned.

    Simulates the pre-fix behavior by injecting a git_add_fn that is never
    meant to be consulted for the detail/status to change -- i.e. proves the
    PASS detail and the paths-added list are driven BY `git_add_fn`'s return,
    not independent of it. A no-op git_add_fn that always reports failure
    must turn the step WARN, the same way the real git subprocess failing
    (e.g. no git repo, no write permission) would.
    """

    def always_fails(project_root: Path, rel_path: str) -> bool:
        return False

    run_script_fn = fake_run_script_fn(
        0, _archive_stdout([{"ticket_id": "WOT-2026-086f", "archived_count": 21}])
    )
    result = _run_archive_event_bus(run_script_fn, always_fails)

    assert result.status == "WARN"
    assert "WOT-2026-086f" in result.detail
    assert "git add -f" in result.detail


def test_step_archive_event_bus_no_terminal_tickets_passes_without_git_add() -> None:
    """Empty rotation (no terminal tickets): PASS, git_add_fn never needed."""
    calls: list[str] = []

    def spy_git_add(project_root: Path, rel_path: str) -> bool:
        calls.append(rel_path)
        return True

    run_script_fn = fake_run_script_fn(
        0, _json.dumps({"status": "no-op", "reason": "no_terminal_tickets"})
    )
    result = _run_archive_event_bus(run_script_fn, spy_git_add)

    assert result.status == "PASS"
    assert calls == []


def test_archived_ticket_ids_from_stdout_rejects_malformed_ticket_id() -> None:
    """F2 (Revisor): a syntactically-wrong ticket_id does not reach git add -f."""
    stdout = _archive_stdout([{"ticket_id": "../../etc/passwd", "archived_count": 1}])
    assert _archived_ticket_ids_from_stdout(stdout) == []


def test_step_archive_event_bus_real_producer_stdout_end_to_end(tmp_path: Path) -> None:
    """REGRESSION (Revisor F1, WOT-2026-088f): consume the REAL, unfabricated
    stdout of ``scripts/archive_event_bus.py --all-terminal`` -- not a
    hand-written fixture.

    Before this test existed, all 11 other tests in this suite passed while
    the fix was a NO-OP in production: ``_archive_stdout`` fabricated the
    DRY-RUN shape (which already carried ``ticket_id``, archive_event_bus.py
    ``_archive_ticket``'s dry-run branch), but the real non-dry-run path
    returns ``EventBus.archive_ticket_events()`` directly, which lacked
    ``ticket_id`` until this same ticket's fix. Fixture drift against the
    real producer masked the bug end-to-end. This test runs the actual
    script as a subprocess against a real temp bus with a real terminal
    ticket and feeds its captured stdout through the real parser.
    """
    import subprocess
    import sys

    from bus.event_bus import EventBus

    events_dir = tmp_path / ".agent" / "runtime" / "events"
    bus = EventBus(events_dir)
    bus.emit(
        event_type="BUILDER_EXIT",
        ticket_id="WOT-2026-999z",
        actor="BUILDER",
        payload={},
    )
    bus.emit(
        event_type="STATE_CHANGED",
        ticket_id="WOT-2026-999z",
        actor="SUPERVISOR",
        payload={"to_state": "COMPLETED"},
    )

    script = Path(__file__).resolve().parents[2] / "scripts" / "archive_event_bus.py"
    import os

    env = dict(os.environ)
    env["AGENT_PROJECT_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(script), "--all-terminal"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert _archived_ticket_ids_from_stdout(result.stdout) == ["WOT-2026-999z"]


def test_step_archive_event_bus_real_git_stages_the_gitignored_archive(
    tmp_path: Path,
) -> None:
    """HERMETIC, real git subprocess (no mocking): proves `git add -f` really
    overrides a `.gitignore` rule that excludes the archive directory --
    exactly the production layout (`.agent/runtime/events/archive/` is
    gitignored in both motor and destino).
    """
    import subprocess

    from scripts.closeout_steps.archival import _git_add_force

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / ".gitignore").write_text(
        ".agent/runtime/events/archive/\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", ".gitignore"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    archive_dir = repo / ".agent" / "runtime" / "events" / "archive"
    archive_dir.mkdir(parents=True)
    rel_path = ".agent/runtime/events/archive/events.WOT-2026-086f.jsonl"
    (repo / rel_path).write_text('{"event_type": "BUILDER_EXIT"}\n', encoding="utf-8")

    # Control (pre-fix behavior): a plain `git add` respects .gitignore and
    # stages nothing -- the exact silent gap this ticket closes.
    plain_add = subprocess.run(
        ["git", "add", rel_path], cwd=repo, capture_output=True, text=True
    )
    assert plain_add.returncode != 0  # git refuses an ignored path without -f
    staged_before = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert rel_path not in staged_before

    assert _git_add_force(repo, rel_path) is True

    staged_after = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert rel_path in staged_after
