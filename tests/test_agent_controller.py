"""Minimal tests for agent_controller.py canonical functions.

Only tests functions that exist in the canonical controller:
- read_file
- write_file
- validate_state_files
- determine_next_action
- should_overwrite_turn
- update_log_status
- run_quality_gates

Full test suite for removed functions (normalize_*, mark_*, perform_*,
request_*, get_rejection_*, publish_*) can be restored when those
functions are implemented.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import agent_controller  # noqa: E402
from agent_controller import (  # noqa: E402
    determine_next_action,
    read_file,
    run_quality_gates,
    should_overwrite_turn,
    update_log_status,
    validate_state_files,
    write_file,
)


class TestReadFile:
    """Test read_file handles filesystem correctly."""

    def test_read_file_existing_path(self, tmp_path):
        """read_file returns content from existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = read_file(test_file)
        assert result == "test content"

    def test_read_file_missing_path(self, tmp_path):
        """read_file returns empty string for missing file."""
        missing_file = tmp_path / "missing.txt"

        result = read_file(missing_file)
        assert result == ""


class TestWriteFile:
    """Test write_file creates and updates files."""

    def test_write_file_creates_new(self, tmp_path):
        """write_file creates new file with content."""
        test_file = tmp_path / "new.txt"
        write_file(test_file, "new content")

        assert test_file.exists()
        assert test_file.read_text() == "new content"

    def test_write_file_overwrites_existing(self, tmp_path):
        """write_file overwrites existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content")

        write_file(test_file, "new content")

        assert test_file.read_text() == "new content"

    def test_write_file_creates_parent_dirs(self, tmp_path):
        """write_file creates parent directories if needed."""
        test_file = tmp_path / "subdir" / "nested" / "file.txt"
        write_file(test_file, "nested content")

        assert test_file.exists()
        assert test_file.read_text() == "nested content"


class TestValidateStateFiles:
    """Test validate_state_files checks state consistency."""

    def test_validate_returns_dict_with_keys(self):
        """validate_state_files returns proper error dict structure."""
        with patch("agent_controller.read_file", return_value=""):
            errors = validate_state_files()

        # Should have these keys
        assert "work_plan.md" in errors
        assert "execution_log.md" in errors
        assert "TURN.md" in errors
        assert "consistency" in errors

    def test_validate_detects_missing_section(self):
        """validate_state_files detects missing required sections."""
        with (
            patch("agent_controller.read_file", return_value="# Empty file\n"),
            patch(
                "agent_controller.TURN_FILE",
                MagicMock(exists=MagicMock(return_value=True)),
            ),
        ):
            errors = validate_state_files()

        # Should detect missing sections
        assert len(errors["TURN.md"]) > 0 or len(errors["consistency"]) > 0


class TestDetermineNextAction:
    """Test determine_next_action analyzes state and returns action."""

    def test_determine_next_action_returns_dict(self):
        """determine_next_action returns proper action dict."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.HOOKS_AVAILABLE", False),
        ):
            action = determine_next_action(skip_gates=True)

        # Should return dict with role and action_type
        assert isinstance(action, dict)
        assert "role" in action


class TestShouldOverwriteTurn:
    """Test should_overwrite_turn determines if TURN.md needs reset."""

    def test_should_overwrite_turn_returns_bool(self):
        """should_overwrite_turn returns boolean."""
        with patch.object(Path, "exists", return_value=False):
            result = should_overwrite_turn(Path("/fake/TURN.md"))

        assert isinstance(result, bool)


class TestUpdateLogStatus:
    """Test update_log_status modifies execution log."""

    def test_update_log_status_returns_bool(self):
        """update_log_status returns success boolean."""
        with (
            patch("agent_controller.read_file", return_value="# Execution Log\n"),
            patch("agent_controller.write_file"),
        ):
            result = update_log_status("IN_PROGRESS", "test note")

        assert isinstance(result, bool)


class TestRunQualityGates:
    """Test run_quality_gates executes validation checks."""

    def test_run_quality_gates_returns_dict(self):
        """run_quality_gates returns result dict with expected keys."""
        with (
            patch("agent_controller.read_file", return_value=""),
            patch("agent_controller.subprocess"),
        ):
            result = run_quality_gates()

        assert isinstance(result, dict)
        # Should have standard result keys: errors, passed, summary, warnings
        assert "passed" in result
        assert "summary" in result


class TestHumanGateThreshold:
    """WP-2026-106 B-fix: HUMAN_GATE threshold is a single source of truth."""

    def test_threshold_reads_from_agents_config(self, tmp_path, monkeypatch):
        """get_human_gate_threshold reads manager_review.max_attempts."""
        import json

        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps({"manager_review": {"max_attempts": 5}}), encoding="utf-8"
        )
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", cfg)
        assert agent_controller.get_human_gate_threshold() == 5

    def test_threshold_falls_back_when_config_missing(self, tmp_path, monkeypatch):
        """Missing config -> safe fallback, never the legacy hardcoded 3."""
        monkeypatch.setattr(
            agent_controller, "AGENTS_CONFIG_PATH", tmp_path / "absent.json"
        )
        result = agent_controller.get_human_gate_threshold()
        assert result == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        assert result != 3

    def test_threshold_falls_back_on_malformed_config(self, tmp_path, monkeypatch):
        """Malformed JSON -> fallback, no exception."""
        bad = tmp_path / "agents.json"
        bad.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(agent_controller, "AGENTS_CONFIG_PATH", bad)
        assert (
            agent_controller.get_human_gate_threshold()
            == agent_controller.HUMAN_GATE_REJECTION_FALLBACK
        )


class TestTicketProseIntegration:
    """WP-2026-162: Ticket prose validation integration in _handle_validate."""

    def test_validate_includes_ticket_prose_warnings(self, tmp_path, monkeypatch):
        """_handle_validate includes ticket_prose warnings when validator available."""
        # Mock validate_ticket_prose to return warnings
        mock_result = {
            "warnings": [
                {
                    "rule_id": "TP-PROSE-01",
                    "rule_name": "throat-clearing",
                    "evidence": "test",
                    "suggestion": "fix",
                }
            ],
            "warning_count": 1,
        }

        def mock_validate(work_plan_path, collab_dir):
            return mock_result

        # Patch WORK_PLAN and get_collab_dir
        fake_work_plan = tmp_path / "work_plan.md"
        fake_work_plan.write_text("# Plan\n", encoding="utf-8")
        fake_collab = tmp_path / "collab"
        fake_collab.mkdir()

        monkeypatch.setattr(agent_controller, "WORK_PLAN", fake_work_plan)
        monkeypatch.setattr(agent_controller, "get_collab_dir", lambda: fake_collab)

        # Mock the validate_state_files and other dependencies to return empty
        monkeypatch.setattr(agent_controller, "validate_state_files", lambda: {})
        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda x: {}
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda x: "")
        monkeypatch.setattr(agent_controller, "get_status", lambda x, y: "APPROVED")
        monkeypatch.setattr(
            agent_controller, "_check_scope_for_validate", lambda x, y: ([], [])
        )
        monkeypatch.setattr(agent_controller, "_check_bus_drift", lambda x, y: [])
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda x, y, z: {"errors": [], "warnings": []},
        )

        # Patch the import
        import sys

        mock_module = type(
            "MockModule",
            (),
            {"validate_ticket_prose": staticmethod(mock_validate)},
        )()
        monkeypatch.setitem(sys.modules, "scripts.validate_ticket_prose", mock_module)

        # Capture stdout
        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        # Exit code should be 0 (warnings don't block)
        assert exit_code == 0
        output = captured.getvalue()
        assert "ticket_prose" in output or "TP-PROSE" in output

    def test_validate_graceful_degrade_without_validator(self, tmp_path, monkeypatch):
        """_handle_validate works even if validator not available."""
        # Mock the validate_ticket_prose import to raise ImportError
        import sys
        from types import ModuleType

        # Create a mock module that raises ImportError when validate_ticket_prose is accessed
        def mock_validate(*args, **kwargs):
            raise ImportError("Validator not available")

        mock_module = ModuleType("scripts.validate_ticket_prose")
        mock_module.validate_ticket_prose = mock_validate
        monkeypatch.setitem(sys.modules, "scripts.validate_ticket_prose", mock_module)

        # Mock file reads
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: "# Plan\n\n## Metadata\n- **ID:** TEST\n- **Estado:** APPROVED\n",
        )
        monkeypatch.setattr(agent_controller, "validate_state_files", lambda: {})
        monkeypatch.setattr(
            agent_controller, "_collect_deliverable_type_warnings", lambda x: {}
        )
        monkeypatch.setattr(agent_controller, "get_status", lambda x, y: "APPROVED")
        monkeypatch.setattr(
            agent_controller, "_check_scope_for_validate", lambda x, y: ([], [])
        )
        monkeypatch.setattr(agent_controller, "_check_bus_drift", lambda x, y: [])
        monkeypatch.setattr(
            agent_controller,
            "_check_invariants",
            lambda x, y, z: {"errors": [], "warnings": []},
        )

        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            exit_code = agent_controller._handle_validate(json_output=True)
        finally:
            sys.stdout = old_stdout

        # Should still work and return 0
        assert exit_code == 0


class TestSessionClose:
    """WP-2026-169: Test --session-close handler delegation and idempotency."""

    def test_session_close_already_completed(self, monkeypatch):
        """When STATE.md already COMPLETED and no --force, exit 0 silently."""

        def mock_read(path):
            return "Estado actual: COMPLETED\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0

    def test_session_close_dry_run(self, monkeypatch):
        """--dry-run delegates and returns exit code without syncing state."""
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="[DRY-RUN] ok\n", stderr="")
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=True,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        # Verify subprocess received --dry-run flag
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "--dry-run" in args

    def test_session_close_dry_run_passes_ticket(self, monkeypatch):
        """--session-close --dry-run --ticket WP-2026-168 passes the flag."""
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="[DRY-RUN] ok\n", stderr="")
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=True,
            skip_slow=False,
            ticket="WP-2026-168",
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        args = mock_run.call_args[0][0]
        assert "--ticket" in args
        assert "WP-2026-168" in args

    def test_session_close_real_syncs_state(self, monkeypatch):
        """Real close delegates and syncs STATE.md to COMPLETED."""
        written = {}

        def mock_write(path, content):
            written[str(path)] = content

        def mock_read(path):
            return "# State\nEstado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "write_file", mock_write)
        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        mock_run = MagicMock(
            return_value=MagicMock(
                returncode=0, stdout="[OK] Session close completed\n", stderr=""
            )
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 0
        # Verify STATE.md was synced to COMPLETED
        assert any("COMPLETED" in v for v in written.values())

    def test_session_close_force_overrides_idempotency(self, monkeypatch):
        """--force overrides already-completed guard and runs session close."""
        written = {}

        def mock_write(path, content):
            written[str(path)] = content

        def mock_read(path):
            return "Estado actual: COMPLETED\n"

        monkeypatch.setattr(agent_controller, "write_file", mock_write)
        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        mock_run = MagicMock(
            return_value=MagicMock(
                returncode=0, stdout="[OK] Session close completed\n", stderr=""
            )
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", mock_run)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=True,
            json_output=False,
        )
        assert code == 0
        assert mock_run.called

    def test_session_close_script_not_found(self, monkeypatch):
        """When session_closeout.py is missing, exit with error."""
        monkeypatch.setattr(
            agent_controller,
            "PROJECT_ROOT",
            Path("/nonexistent"),
        )

        def mock_read(path):
            return "Estado actual: IN_PROGRESS\n"

        monkeypatch.setattr(agent_controller, "read_file", mock_read)

        code = agent_controller._handle_session_close(
            dry_run=False,
            skip_slow=False,
            ticket=None,
            tickets=None,
            force_mode=False,
            json_output=False,
        )
        assert code == 1


class TestPreHandoff:
    """WP-2026-173: --pre-handoff helper to stage commit and checkpoint.

    Test suite covers at least five cases:
    - happy path: commit + tag + clean tree
    - idempotent: no changes + tag already aligned
    - tag-only: no changes but tag missing → create tag without commit
    - hook failure: pre-commit hook fails → stderr propagated
    - dirty tree: tree still dirty after ops → error
    """

    _PLAN_ID = "WP-2026-173"
    _PLAN_CONTENT = f"""# Work Plan

## Metadata
- **ID:** {_PLAN_ID}
- **Estado:** APPROVED

## Files Likely Touched
- src/file1.py
- src/file2.py
"""

    @staticmethod
    def _make_git_mock(overrides=None):
        """Create a subprocess.run mock for git commands.

        Args:
            overrides: dict of pattern -> (returncode, stdout, stderr)
                       to override specific command responses.
        """
        default_overrides = overrides or {}

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)

            # Check overrides first
            for pattern, result in default_overrides.items():
                if pattern in cmd_str:
                    rc, out, err = result
                    return MagicMock(returncode=rc, stdout=out, stderr=err)

            # Default handlers
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(
                    returncode=0, stdout="[main abc123] commit\n", stderr=""
                )
            if len(cmd) >= 3 and cmd[1] == "tag" and cmd[2] in ("-a", "-d"):
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")

            return MagicMock(returncode=0, stdout="", stderr="")

        return mock_run

    def _setup_basic_mocks(self, monkeypatch, changed_files, whitelist_files):
        """Set up common mocks for pre_handoff tests.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            changed_files: set of absolute paths for get_changed_files.
            whitelist_files: set of absolute paths for parse_files_likely_touched.
        """
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: self._PLAN_CONTENT if "work_plan" in str(x).lower() else "",
        )
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: whitelist_files,
        )
        monkeypatch.setattr(
            agent_controller,
            "get_changed_files",
            lambda: changed_files,
        )

    def _capture_output(self, func):
        """Run func capturing stdout+stderr, return (exit_code, combined_text)."""
        from io import StringIO

        captured_out = StringIO()
        captured_err = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            code = func()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        combined = captured_out.getvalue() + captured_err.getvalue()
        return code, combined

    def test_happy_path_commit_tag_clean(self, monkeypatch):
        """Happy path: commit + tag + clean tree → exit 0."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        file2 = str(project_root / "src" / "file2.py")
        whitelist = {file1, file2}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        git_mock = self._make_git_mock()
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert "Pre-handoff complete" in output

    def test_idempotent_no_changes_tag_aligned(self, monkeypatch):
        """No changes + tag aligned → idempotent exit 0."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        # Override: tag exists and aligns with HEAD
        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert "already aligned" in output

    def test_no_changes_tag_missing_create_only(self, monkeypatch):
        """No changes + tag missing → create tag without commit."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        tag_created = [False]

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[1] == "tag" and cmd[2] == "-a":
                tag_created[0] = True
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="abc123\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert tag_created[0], "Tag was not created"
        assert "Created/refreshed tag" in output

    def test_no_changes_tag_misaligned_delete_then_recreate(self, monkeypatch):
        """No changes + existing misaligned tag → delete then recreate."""
        self._setup_basic_mocks(monkeypatch, set(), set())

        calls = []

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            calls.append(cmd_str)
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=0, stdout="oldsha\n", stderr="")
            if "rev-parse HEAD" in cmd_str:
                return MagicMock(returncode=0, stdout="newsha\n", stderr="")
            if len(cmd) >= 3 and cmd[:3] == ["git", "tag", "-d"]:
                return MagicMock(returncode=0, stdout="Deleted tag\n", stderr="")
            if len(cmd) >= 3 and cmd[:3] == ["git", "tag", "-a"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        assert any("git tag -d checkpoint/review-WP-2026-173" in c for c in calls), (
            output
        )
        assert any("git tag -a checkpoint/review-WP-2026-173" in c for c in calls), (
            output
        )
        assert next(i for i, c in enumerate(calls) if "git tag -d" in c) < next(
            i for i, c in enumerate(calls) if "git tag -a" in c
        ), output
        assert "Created/refreshed tag" in output

    def test_hook_failure_propagates_stderr(self, monkeypatch):
        """Pre-commit hook failure → stderr propagated, exit != 0."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        whitelist = {file1}
        fake_stderr = (
            "pre-commit hook failed\nAborting commit due to pre-commit hook.\n"
        )

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(returncode=1, stdout="", stderr=fake_stderr)
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code != 0, f"Expected non-zero, got {code}. Output: {output}"
        assert "pre-commit hook failed" in output, f"Missing error in output: {output}"

    def test_dirty_tree_after_ops(self, monkeypatch):
        """Dirty tree after commit + tag → error exit 1."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        whitelist = {file1}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        # Override status to report a dirty file
        def git_mock(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "rev-parse" in cmd_str and "checkpoint" in cmd_str and "^{}" in cmd_str:
                return MagicMock(returncode=1, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "add"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "commit"]:
                return MagicMock(
                    returncode=0, stdout="[main abc123] commit\n", stderr=""
                )
            if len(cmd) >= 3 and cmd[1] == "tag" and cmd[2] == "-a":
                return MagicMock(returncode=0, stdout="", stderr="")
            if len(cmd) >= 2 and cmd[:2] == ["git", "status"]:
                # Simulate an untracked non-live file
                return MagicMock(
                    returncode=0,
                    stdout="?? untracked_output.txt\n",
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code != 0, f"Expected non-zero, got {code}. Output: {output}"
        assert "Tree still dirty" in output
