#!/usr/bin/env python3
"""Tests for session_closeout.py - session closeout orchestrator.

Tests cover:
(a) Session window resolution (with/without previous report, first-run fallback)
(b) Ticket resolution priority chain (explicit > detected > work_plan fallback)
(c) --skip-slow behavior (skips observations and memory consolidation)
(d) --dry-run behavior (generates report without executing destructive steps)
(e) Portability checks (absolute path detection, manifest validation)
(f) Report generation (correct structure, PASS/WARN/FAIL per step)
(g) CLI argument parsing
(h) prepush_check blocking behavior (early exit on failure)

Uses monkeypatch and tmp_path to isolate filesystem and subprocess calls.
No test mutates the real filesystem.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.session_closeout import (
    DRY_RUN_REPORT_REL,
    REPORT_REL,
    CloseoutReport,
    StepResult,
    _check_portability,
    _check_versioned_filenames,
    _detect_tickets_in_window,
    _find_last_report_timestamp,
    _generate_report,
    _get_ticket_close_timestamps,
    _resolve_active_ticket,
    _resolve_session_window,
    _resolve_tickets,
    _run_script,
    _step_manifest_check,
    main,
    run_closeout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str,
    ticket_id: str,
    timestamp: str,
    sequence_number: int,
    payload: dict | None = None,
    actor: str = "BUILDER",
) -> dict:
    """Create a minimal event dict for testing."""
    return {
        "event_id": f"ev-{sequence_number:04d}",
        "event_type": event_type,
        "ticket_id": ticket_id,
        "actor": actor,
        "timestamp": timestamp,
        "payload": payload or {},
        "schema_version": "1.0",
        "sequence_number": sequence_number,
    }


def _write_events_file(project_root: Path, events: list[dict]) -> None:
    """Write events to the events.jsonl file."""
    events_dir = project_root / ".agent" / "runtime" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    events_path = events_dir / "events.jsonl"
    with open(events_path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _write_report(project_root: Path, generated: str) -> None:
    """Write a session_close_report.md with a given Generated timestamp."""
    report_dir = project_root / ".agent" / "runtime" / "memory"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "session_close_report.md"
    report_path.write_text(
        f"# Session Close Report\n\n**Generated:** {generated}\n\n## Summary\n\nTest report.\n",
        encoding="utf-8",
    )


def _write_work_plan(project_root: Path, ticket_id: str = "WP-2026-168") -> None:
    """Write a minimal work_plan.md with a given ticket ID."""
    wp_dir = project_root / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True, exist_ok=True)
    wp_path = wp_dir / "work_plan.md"
    wp_path.write_text(
        f"# Work Plan\n\n## Metadata\n- **ID:** {ticket_id}\n- **Estado:** APPROVED\n",
        encoding="utf-8",
    )


def _generated_report_path(project_root: Path, *, dry_run: bool) -> Path:
    """Return the report path for the requested closeout mode."""
    return project_root / (DRY_RUN_REPORT_REL if dry_run else REPORT_REL)


def test_run_script_exports_agent_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Child scripts receive the canonical destination root explicitly."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("scripts.session_closeout.subprocess.run", fake_run)
    monkeypatch.setattr(
        "runtime.motor_link.resolve_motor_script",
        lambda project_root, script_name: tmp_path / script_name,
    )

    _run_script("memory_consolidate.py", ["--apply"], tmp_path)

    assert captured["cwd"] == str(tmp_path)
    assert captured["env"]["AGENT_PROJECT_ROOT"] == str(tmp_path.resolve())


class TestFindLastReportTimestamp:
    """Tests for session window resolution from last report."""

    def test_no_report_returns_none(self, tmp_path: Path) -> None:
        """When no report exists, returns None."""
        assert _find_last_report_timestamp(tmp_path) is None

    def test_report_exists_returns_timestamp(self, tmp_path: Path) -> None:
        """When report exists, parses the Generated timestamp."""
        _write_report(tmp_path, "2026-05-27 00:00:00 UTC")
        result = _find_last_report_timestamp(tmp_path)
        assert result == "2026-05-27 00:00:00 UTC"

    def test_malformed_report_returns_none(self, tmp_path: Path) -> None:
        """When report has no Generated line, returns None."""
        report_dir = tmp_path / ".agent" / "runtime" / "memory"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "session_close_report.md").write_text(
            "# No generated line here\n", encoding="utf-8"
        )
        assert _find_last_report_timestamp(tmp_path) is None


class TestResolveSessionWindow:
    """Tests for session window resolution."""

    def test_first_run_uses_first_event(self, tmp_path: Path) -> None:
        """When no report exists, falls back to first event timestamp."""
        events = [
            _make_event("STATE_CHANGED", "WP-2026-168", "2026-05-29T09:00:00+00:00", 1),
            _make_event("BUILDER_EXIT", "WP-2026-168", "2026-05-29T10:00:00+00:00", 2),
        ]
        _write_events_file(tmp_path, events)
        dt, src = _resolve_session_window(tmp_path)
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 29
        assert "first event" in src

    def test_existing_report_takes_precedence(self, tmp_path: Path) -> None:
        """When both report and events exist, report timestamp wins."""
        _write_report(tmp_path, "2026-05-28 12:00:00 UTC")
        events = [
            _make_event("STATE_CHANGED", "WP-2026-168", "2026-05-29T09:00:00+00:00", 1),
        ]
        _write_events_file(tmp_path, events)
        dt, src = _resolve_session_window(tmp_path)
        assert dt is not None
        assert "last report" in src

    def test_no_events_no_report(self, tmp_path: Path) -> None:
        """When neither report nor events exist, returns None."""
        dt, src = _resolve_session_window(tmp_path)
        assert dt is None
        assert "no events" in src


class TestDetectTicketsInWindow:
    """Tests for ticket detection from events within session window."""

    def test_filters_by_timestamp(self) -> None:
        """Only tickets with events after window_start are returned."""
        events = [
            _make_event("STATE_CHANGED", "WP-2026-160", "2026-05-20T10:00:00+00:00", 1),
            _make_event("STATE_CHANGED", "WP-2026-167", "2026-05-29T08:00:00+00:00", 2),
            _make_event("BUILDER_EXIT", "WP-2026-168", "2026-05-29T09:00:00+00:00", 3),
        ]
        from datetime import datetime, timezone

        window = datetime(2026, 5, 29, tzinfo=timezone.utc)
        result = _detect_tickets_in_window(events, window)
        assert "WP-2026-160" not in result
        assert "WP-2026-167" in result
        assert "WP-2026-168" in result

    def test_no_window_returns_all(self) -> None:
        """When window_start is None, all ticket IDs are returned."""
        events = [
            _make_event("STATE_CHANGED", "WP-2026-160", "2026-05-20T10:00:00+00:00", 1),
            _make_event("BUILDER_EXIT", "WP-2026-168", "2026-05-29T09:00:00+00:00", 2),
        ]
        result = _detect_tickets_in_window(events, None)
        assert result == ["WP-2026-160", "WP-2026-168"]

    def test_deduplicates_tickets(self) -> None:
        """Multiple events for the same ticket yield only one entry."""
        events = [
            _make_event("STATE_CHANGED", "WP-2026-168", "2026-05-29T09:00:00+00:00", 1),
            _make_event("BUILDER_EXIT", "WP-2026-168", "2026-05-29T10:00:00+00:00", 2),
        ]
        result = _detect_tickets_in_window(events, None)
        assert result == ["WP-2026-168"]


class TestResolveTickets:
    """Tests for ticket resolution priority chain."""

    def test_explicit_tickets_win(self, tmp_path: Path) -> None:
        """Explicit CLI tickets take highest priority."""
        _write_work_plan(tmp_path, "WP-2026-100")
        events = [
            _make_event("STATE_CHANGED", "WP-2026-168", "2026-05-29T09:00:00+00:00", 1),
        ]
        _write_events_file(tmp_path, events)
        tickets, src = _resolve_tickets(tmp_path, ["WP-2026-999"])
        assert tickets == ["WP-2026-999"]
        assert "explicit" in src

    def test_detected_fallback(self, tmp_path: Path) -> None:
        """When no explicit tickets, detected from events window."""
        _write_work_plan(tmp_path, "WP-2026-100")
        events = [
            _make_event("STATE_CHANGED", "WP-2026-168", "2026-05-29T09:00:00+00:00", 1),
        ]
        _write_events_file(tmp_path, events)
        tickets, src = _resolve_tickets(tmp_path, None)
        assert "WP-2026-168" in tickets
        assert "detected" in src

    def test_work_plan_fallback(self, tmp_path: Path) -> None:
        """When no events in window, falls back to work_plan active ticket."""
        _write_work_plan(tmp_path, "WP-2026-168")
        # No events file
        tickets, src = _resolve_tickets(tmp_path, None)
        assert tickets == ["WP-2026-168"]
        assert "fallback" in src

    def test_no_tickets_found(self, tmp_path: Path) -> None:
        """When nothing available, returns empty list."""
        tickets, src = _resolve_tickets(tmp_path, None)
        assert tickets == []
        assert "no tickets" in src


class TestResolveActiveTicket:
    """Tests for active ticket resolution from work_plan.md."""

    def test_parses_ticket_id(self, tmp_path: Path) -> None:
        """Correctly extracts ticket ID from work_plan.md."""
        _write_work_plan(tmp_path, "WP-2026-168")
        assert _resolve_active_ticket(tmp_path) == "WP-2026-168"

    def test_parses_suffixed_ticket_id(self, tmp_path: Path) -> None:
        """Correctly extracts suffixed ticket IDs from work_plan.md."""
        _write_work_plan(tmp_path, "WT-2026-234a")
        assert _resolve_active_ticket(tmp_path) == "WT-2026-234a"

    def test_no_work_plan(self, tmp_path: Path) -> None:
        """Returns None when work_plan.md doesn't exist."""
        assert _resolve_active_ticket(tmp_path) is None


class TestGetTicketCloseTimestamps:
    """Tests for extracting close timestamps from events."""

    def test_finds_completed_state(self) -> None:
        """Finds STATE_CHANGED with to_state=COMPLETED."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-168",
                "2026-05-29T10:00:00+00:00",
                1,
                payload={"from_state": "READY_TO_CLOSE", "to_state": "COMPLETED"},
            ),
        ]
        result = _get_ticket_close_timestamps(events, ["WP-2026-168"])
        assert result["WP-2026-168"] == "2026-05-29T10:00:00+00:00"

    def test_ignores_non_terminal(self) -> None:
        """Ignores STATE_CHANGED events that don't reach terminal state."""
        events = [
            _make_event(
                "STATE_CHANGED",
                "WP-2026-168",
                "2026-05-29T10:00:00+00:00",
                1,
                payload={"from_state": "IN_PROGRESS", "to_state": "READY_FOR_REVIEW"},
            ),
        ]
        result = _get_ticket_close_timestamps(events, ["WP-2026-168"])
        assert "WP-2026-168" not in result


class TestCheckPortability:
    """Tests for absolute path detection in portable files."""

    def test_clean_paths_pass(self, tmp_path: Path) -> None:
        """No absolute paths returns PASS."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text(
            "# Hello\nSome relative text.\n", encoding="utf-8"
        )
        result = _check_portability(tmp_path)
        assert result.status == "PASS"

    def test_absolute_path_warns(self, tmp_path: Path) -> None:
        """Absolute home path in markdown triggers WARN."""
        home = Path.home()
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text(
            f"# Config\nPath is {home}/something\n", encoding="utf-8"
        )
        result = _check_portability(tmp_path)
        assert result.status == "WARN"
        assert "readme.md:2" in result.detail

    def test_no_scan_dirs_pass(self, tmp_path: Path) -> None:
        """When scan dirs don't exist, returns PASS."""
        result = _check_portability(tmp_path)
        assert result.status == "PASS"


class TestGenerateReport:
    """Tests for report generation."""

    def test_creates_report_file(self, tmp_path: Path) -> None:
        """Report file is created at the expected path."""
        report = CloseoutReport(
            session_start="from first event",
            tickets=["WP-2026-168"],
            steps=[StepResult(name="test_step", status="PASS", detail="ok")],
        )
        path = _generate_report(report, tmp_path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Session Close Report" in content
        assert "WP-2026-168" in content
        assert "test_step" in content
        assert "PASS" in content

    def test_report_shows_dry_run(self, tmp_path: Path) -> None:
        """Dry run mode is reflected in the report."""
        report = CloseoutReport(dry_run=True)
        path = _generate_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "**Dry Run:** Yes" in content

    def test_overall_status_fail(self, tmp_path: Path) -> None:
        """Overall status is FAIL when any blocking step fails."""
        report = CloseoutReport(
            steps=[
                StepResult(name="step1", status="PASS"),
                StepResult(name="step2", status="FAIL", blocking=True),
            ]
        )
        path = _generate_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "Overall: FAIL" in content

    def test_overall_status_warn(self, tmp_path: Path) -> None:
        """Overall status is WARN when no failures but warnings exist."""
        report = CloseoutReport(
            steps=[
                StepResult(name="step1", status="PASS"),
                StepResult(name="step2", status="WARN"),
            ]
        )
        path = _generate_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "Overall: WARN" in content


class TestCloseoutReportOverallStatus:
    """Tests for the CloseoutReport.overall_status property."""

    def test_all_pass(self) -> None:
        report = CloseoutReport(steps=[StepResult(name="a", status="PASS")])
        assert report.overall_status == "PASS"

    def test_warning_gives_warn(self) -> None:
        report = CloseoutReport(
            steps=[
                StepResult(name="a", status="PASS"),
                StepResult(name="b", status="WARN"),
            ]
        )
        assert report.overall_status == "WARN"

    def test_failure_gives_fail(self) -> None:
        report = CloseoutReport(
            steps=[
                StepResult(name="a", status="PASS"),
                StepResult(name="b", status="FAIL"),
            ]
        )
        assert report.overall_status == "FAIL"

    def test_empty_steps(self) -> None:
        report = CloseoutReport()
        assert report.overall_status == "PASS"


# ---------------------------------------------------------------------------
# Test: run_closeout integration (with mocked subprocess)
# ---------------------------------------------------------------------------


class TestRunCloseout:
    """Integration tests for run_closeout with mocked subprocess calls."""

    def _mock_run_success(self, *args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )

    def test_dry_run_generates_report(self, tmp_path: Path) -> None:
        """Dry-run mode writes an ignored preview, not the durable report."""
        _write_work_plan(tmp_path, "WP-2026-168")
        result = run_closeout(tmp_path, dry_run=True)
        assert result == 0
        report_path = _generated_report_path(tmp_path, dry_run=True)
        assert report_path.exists()
        assert not _generated_report_path(tmp_path, dry_run=False).exists()
        content = report_path.read_text(encoding="utf-8")
        assert "**Dry Run:** Yes" in content

    def test_skip_slow_skips_observations_and_consolidate(self, tmp_path: Path) -> None:
        """--skip-slow marks observations and consolidate as SKIP."""
        _write_work_plan(tmp_path, "WP-2026-168")

        with patch(
            "scripts.session_closeout._run_script", side_effect=self._mock_run_success
        ):
            result = run_closeout(tmp_path, dry_run=True, skip_slow=True)

        assert result == 0
        report_path = _generated_report_path(tmp_path, dry_run=True)
        content = report_path.read_text(encoding="utf-8")
        assert "**Skip Slow:** Yes" in content
        assert "observations_all" in content
        assert "SKIP" in content

    def test_prepush_failure_returns_1(self, tmp_path: Path) -> None:
        """When prepush_check fails, returns exit code 1 early."""
        _write_work_plan(tmp_path, "WP-2026-168")

        def _mock_run(script_name, args, project_root, timeout=120):
            if script_name == "prepush_check.py":
                return subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="RUFF FAILED", stderr=""
                )
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )

        with patch("scripts.session_closeout._run_script", side_effect=_mock_run):
            result = run_closeout(tmp_path, dry_run=False)

        assert result == 1
        report_path = _generated_report_path(tmp_path, dry_run=False)
        content = report_path.read_text(encoding="utf-8")
        assert "prepush_check" in content
        assert "FAIL" in content

    def test_prepush_failure_reports_stderr(self, tmp_path: Path) -> None:
        """A stderr-only gate failure remains actionable in the report."""
        _write_work_plan(tmp_path, "WP-2026-168")

        def _mock_run(script_name, args, project_root, timeout=120):
            return subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="ModuleNotFoundError: No module named 'bus'",
            )

        with patch("scripts.session_closeout._run_script", side_effect=_mock_run):
            result = run_closeout(tmp_path, dry_run=False)

        assert result == 1
        content = _generated_report_path(
            tmp_path,
            dry_run=False,
        ).read_text(encoding="utf-8")
        assert "ModuleNotFoundError" in content

    def test_explicit_ticket_passed_through(self, tmp_path: Path) -> None:
        """Explicit tickets from CLI are used directly."""
        with patch(
            "scripts.session_closeout._run_script", side_effect=self._mock_run_success
        ):
            result = run_closeout(
                tmp_path, dry_run=True, explicit_tickets=["WP-2026-999"]
            )
        assert result == 0
        report_path = _generated_report_path(tmp_path, dry_run=True)
        content = report_path.read_text(encoding="utf-8")
        assert "WP-2026-999" in content

    def test_first_run_fallback_no_report(self, tmp_path: Path) -> None:
        """First-run with no report and no events uses work_plan fallback."""
        _write_work_plan(tmp_path, "WP-2026-168")
        result = run_closeout(tmp_path, dry_run=True)
        assert result == 0
        report_path = _generated_report_path(tmp_path, dry_run=True)
        content = report_path.read_text(encoding="utf-8")
        assert "WP-2026-168" in content
        assert "fallback" in content.lower() or "work_plan" in content.lower()

    def test_manifest_missing_fails(self, tmp_path: Path) -> None:
        """Missing MANIFEST.distribute causes FAIL in report."""
        _write_work_plan(tmp_path, "WP-2026-168")

        with patch(
            "scripts.session_closeout._run_script", side_effect=self._mock_run_success
        ):
            run_closeout(tmp_path, dry_run=True)

        # manifest_check is not blocking in the current impl (WARN/FAIL but non-blocking)
        report_path = _generated_report_path(tmp_path, dry_run=True)
        content = report_path.read_text(encoding="utf-8")
        assert "manifest_check" in content

    def test_portability_absolute_path_warns(self, tmp_path: Path) -> None:
        """Absolute paths in docs/ trigger WARN in portability check."""
        _write_work_plan(tmp_path, "WP-2026-168")
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text(
            f"# Guide\nPath: {Path.home()}/something\n", encoding="utf-8"
        )

        with patch(
            "scripts.session_closeout._run_script", side_effect=self._mock_run_success
        ):
            run_closeout(tmp_path, dry_run=True)

        report_path = _generated_report_path(tmp_path, dry_run=True)
        content = report_path.read_text(encoding="utf-8")
        assert "portability_paths" in content
        assert "WARN" in content

    def test_manifest_resolves_from_motor_link(self, tmp_path: Path) -> None:
        """External-motor topology validates MANIFEST.distribute in repo_motor."""
        motor_root = tmp_path / "motor"
        motor_root.mkdir()
        (motor_root / "MANIFEST.distribute").write_text("", encoding="utf-8")

        project_root = tmp_path / "destination"
        config_dir = project_root / ".agent" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor_root)}),
            encoding="utf-8",
        )

        result = _step_manifest_check(project_root)

        assert result.status == "PASS"
        assert "repo_motor" in result.detail


# ---------------------------------------------------------------------------
# Test: CLI argument parsing via main()
# ---------------------------------------------------------------------------


class TestCLI:
    """Tests for CLI argument parsing."""

    def test_dry_run_flag(self, tmp_path: Path) -> None:
        """--dry-run is parsed correctly."""
        _write_work_plan(tmp_path, "WP-2026-168")
        with (
            patch(
                "sys.argv",
                ["session_closeout.py", "--project-root", str(tmp_path), "--dry-run"],
            ),
            patch("scripts.session_closeout.run_closeout") as mock_run,
        ):
            mock_run.return_value = 0
            main()
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["dry_run"] is True

    def test_skip_slow_flag(self, tmp_path: Path) -> None:
        """--skip-slow is parsed correctly."""
        _write_work_plan(tmp_path, "WP-2026-168")
        with (
            patch(
                "sys.argv",
                ["session_closeout.py", "--project-root", str(tmp_path), "--skip-slow"],
            ),
            patch("scripts.session_closeout.run_closeout") as mock_run,
        ):
            mock_run.return_value = 0
            main()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["skip_slow"] is True

    def test_ticket_flag(self, tmp_path: Path) -> None:
        """--ticket is parsed into explicit_tickets list."""
        _write_work_plan(tmp_path, "WP-2026-168")
        with (
            patch(
                "sys.argv",
                [
                    "session_closeout.py",
                    "--project-root",
                    str(tmp_path),
                    "--ticket",
                    "WP-2026-999",
                ],
            ),
            patch("scripts.session_closeout.run_closeout") as mock_run,
        ):
            mock_run.return_value = 0
            main()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["explicit_tickets"] == ["WP-2026-999"]

    def test_tickets_flag(self, tmp_path: Path) -> None:
        """--tickets is parsed into explicit_tickets list."""
        _write_work_plan(tmp_path, "WP-2026-168")
        with (
            patch(
                "sys.argv",
                [
                    "session_closeout.py",
                    "--project-root",
                    str(tmp_path),
                    "--tickets",
                    "WP-2026-001,WP-2026-002",
                ],
            ),
            patch("scripts.session_closeout.run_closeout") as mock_run,
        ):
            mock_run.return_value = 0
            main()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["explicit_tickets"] == ["WP-2026-001", "WP-2026-002"]

    def test_nonexistent_project_root_exits_1(self, tmp_path: Path) -> None:
        """Non-existent project root returns exit code 1."""
        bad_path = tmp_path / "nonexistent"
        with patch(
            "sys.argv",
            ["session_closeout.py", "--project-root", str(bad_path)],
        ):
            result = main()
            assert result == 1


class TestCheckVersionedFilenames:
    """Tests for _check_versioned_filenames — ticket-ID-in-filename barrier."""

    @staticmethod
    def _mock_git_ls_files(
        files: list[str], returncode: int = 0, stderr: str = ""
    ) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["git", "ls-files"],
            returncode=returncode,
            stdout="\n".join(files),
            stderr=stderr,
        )

    def test_clean_repo_returns_pass(self, tmp_path: Path) -> None:
        """No ticket IDs in any versioned filename → PASS."""
        mock = self._mock_git_ls_files(
            ["README.md", "scripts/session_closeout.py", "tests/test_utils.py"]
        )
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "PASS"

    def test_detects_wt_ticket_in_filename(self, tmp_path: Path) -> None:
        """WT-YYYY-NNN in basename → FAIL."""
        mock = self._mock_git_ls_files(
            ["README.md", "docs/BUS_ARCHITECTURE_WT-2026-210.md"]
        )
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "FAIL"
        assert "BUS_ARCHITECTURE_WT-2026-210.md" in result.detail

    def test_detects_underscore_test_pattern(self, tmp_path: Path) -> None:
        """test_wt_YYYY_NNNa.py underscore pattern → FAIL."""
        mock = self._mock_git_ls_files(["tests/test_wt_2026_252a.py"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "FAIL"
        assert "test_wt_2026_252a.py" in result.detail

    def test_detects_plan_prefix(self, tmp_path: Path) -> None:
        """PLAN-YYYY-NNN in basename → FAIL."""
        mock = self._mock_git_ls_files(["PLAN-2026-252.md"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "FAIL"
        assert "PLAN-2026-252" in result.detail

    def test_detects_wp_prefix(self, tmp_path: Path) -> None:
        """WP-YYYY-NNN in basename → FAIL."""
        mock = self._mock_git_ls_files(["docs/WP-2026-100-plan.md"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "FAIL"
        assert "WP-2026-100" in result.detail

    def test_ignores_content_with_ticket_ids(self, tmp_path: Path) -> None:
        """Ticket IDs in file content, not filename → PASS."""
        mock = self._mock_git_ls_files(["utils.py"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "PASS"

    def test_paths_are_motor_relative(self, tmp_path: Path) -> None:
        """Diagnostic uses motor-relative paths, never absolute paths."""
        mock = self._mock_git_ls_files(["docs/BUS_ARCHITECTURE_WT-2026-210.md"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert "docs/BUS_ARCHITECTURE_WT-2026-210.md" in result.detail
        assert str(tmp_path) not in result.detail

    def test_git_failure_returns_warn(self, tmp_path: Path) -> None:
        """Git command timeout → WARN, not crash."""
        with patch(
            "scripts.session_closeout.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "ls-files"], timeout=30),
        ):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "WARN"

    def test_git_nonzero_exit_returns_warn(self, tmp_path: Path) -> None:
        """Git ls-files non-zero exit → WARN."""
        mock = self._mock_git_ls_files(
            [], returncode=128, stderr="fatal: not a git repo"
        )
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "WARN"

    def test_detects_suffixed_wt_ticket(self, tmp_path: Path) -> None:
        """WT-YYYY-NNNa with suffixed letter → FAIL."""
        mock = self._mock_git_ls_files(["docs/PLAN_WT-2026-233c.md"])
        with patch("scripts.session_closeout.subprocess.run", return_value=mock):
            result = _check_versioned_filenames(tmp_path)
        assert result.status == "FAIL"
        assert "PLAN_WT-2026-233c.md" in result.detail
