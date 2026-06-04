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

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add .agent to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
agent_dir = PROJECT_ROOT / ".agent"
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


def test_agent_controller_help_lists_critical_flags() -> None:
    controller = PROJECT_ROOT / ".agent" / "agent_controller.py"
    result = subprocess.run(
        [sys.executable, str(controller), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    for flag in (
        "--mark-ready",
        "--validate",
        "--manager-approve <ticket>",
        "--request-changes <ticket>",
        "--resume-human-gate",
        "--bootstrap-ticket",
        "--escalate-human-gate",
        "--pre-handoff",
    ):
        assert flag in result.stdout
    assert "Traceback" not in result.stderr
    assert "error:" not in result.stderr.lower()


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

    def test_session_close_dry_run(self, monkeypatch, tmp_path):
        """--dry-run delegates and returns exit code without syncing state."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

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

    def test_session_close_dry_run_passes_ticket(self, monkeypatch, tmp_path):
        """--session-close --dry-run --ticket WP-2026-168 passes the flag."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

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

    def test_session_close_real_syncs_state(self, monkeypatch, tmp_path):
        """Real close delegates and syncs STATE.md to COMPLETED."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

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

    def test_session_close_force_overrides_idempotency(self, monkeypatch, tmp_path):
        """--force overrides already-completed guard and runs session close."""
        # Create mock scripts/session_closeout.py in temp dir
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        (script_dir / "session_closeout.py").write_text("")
        monkeypatch.setattr(agent_controller, "PROJECT_ROOT", tmp_path)

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
        # Ensure .git exists for pre_handoff git directory check
        project_root = agent_controller.PROJECT_ROOT.resolve()
        git_path = project_root / ".git"
        original_exists = Path.exists

        def _patched_exists(self_path):
            if str(self_path) == str(git_path):
                return True
            return original_exists(self_path)

        monkeypatch.setattr(Path, "exists", _patched_exists)

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

    def test_happy_path_resets_circuit_breaker(self, monkeypatch, tmp_path):
        """Successful pre-handoff should clear an OPEN circuit breaker."""
        project_root = agent_controller.PROJECT_ROOT.resolve()
        file1 = str(project_root / "src" / "file1.py")
        file2 = str(project_root / "src" / "file2.py")
        whitelist = {file1, file2}

        self._setup_basic_mocks(monkeypatch, whitelist, whitelist)

        git_mock = self._make_git_mock()
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        breaker_path = tmp_path / "runtime" / "circuit_breaker.json"
        breaker_path.parent.mkdir(parents=True, exist_ok=True)
        breaker_path.write_text(
            json.dumps(
                {
                    "state": "OPEN",
                    "failures": 4,
                    "no_progress_count": 2,
                    "reason": "previous handoff block",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(agent_controller, "CIRCUIT_BREAKER_PATH", breaker_path)

        code, output = self._capture_output(
            lambda: agent_controller._handle_pre_handoff(json_output=False)
        )

        assert code == 0, f"Expected 0, got {code}. Output: {output}"
        breaker = agent_controller._read_circuit_breaker()
        assert breaker["state"] == "CLOSED"
        assert breaker["failures"] == 0
        assert breaker["no_progress_count"] == 0

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


# =============================================================================
# Tests WP-2026-176: Motor code-only guard
# =============================================================================


class TestMotorCodeOnlyGuard:
    """Tests for motor code-only guard blocking write operations."""

    def test_is_motor_code_only_true(self, monkeypatch):
        """is_motor_code_only returns True when no AGENT_PROJECT_ROOT and marker exists."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

        from runtime.project_root import is_motor_code_only

        # The actual motor repo has agent_controller.py, so this should be True
        # when run from the motor repo and AGENT_PROJECT_ROOT is not set
        result = is_motor_code_only()
        # Note: In test context, this may be False if tests run with AGENT_PROJECT_ROOT
        # or if the test filesystem differs. The marker check is reliable.
        from runtime.project_root import resolve_project_root

        marker = resolve_project_root() / ".agent" / "agent_controller.py"
        expected = marker.exists()
        assert result == expected

    def test_is_motor_code_only_false_with_env(self, monkeypatch):
        """is_motor_code_only returns False when AGENT_PROJECT_ROOT is set."""
        monkeypatch.setenv(
            "AGENT_PROJECT_ROOT", str(Path("/tmp/fake_workspace").resolve())
        )

        from runtime.project_root import is_motor_code_only

        result = is_motor_code_only()
        assert result is False

    def test_main_blocks_mutating_flags(self, monkeypatch):
        """Motor code-only guard blocks --mark-ready when no AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        # Simulate argv with --mark-ready
        test_argv = ["agent_controller.py", "--mark-ready", "--json"]
        monkeypatch.setattr(sys, "argv", test_argv)

        ensure_mock = MagicMock(
            side_effect=AssertionError("_ensure_runtime_dirs called")
        )
        bus_mock = MagicMock(side_effect=AssertionError("_get_event_bus called"))
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", ensure_mock)
        monkeypatch.setattr(agent_controller, "_get_event_bus", bus_mock)

        exit_code = agent_controller.main()
        assert exit_code == 1
        ensure_mock.assert_not_called()
        bus_mock.assert_not_called()

    def test_main_allows_non_mutating_flags(self, monkeypatch):
        """Motor code-only guard allows --validate even without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        # Simulate argv with --validate (should not be blocked)
        test_argv = ["agent_controller.py", "--validate", "--json"]
        monkeypatch.setattr(sys, "argv", test_argv)

        # Patch _ensure_runtime_dirs and _get_event_bus to be safe
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        # We need to also patch the validate handler to return 0, since it reads
        # files from the real filesystem and will fail.
        monkeypatch.setattr(agent_controller, "_handle_validate", lambda json_output: 0)

        exit_code = agent_controller.main()
        assert exit_code == 0

    def test_main_blocks_pre_handoff(self, monkeypatch):
        """Motor code-only guard blocks --pre-handoff without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        test_argv = ["agent_controller.py", "--pre-handoff"]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        exit_code = agent_controller.main()
        assert exit_code == 1

    def test_main_blocks_session_close(self, monkeypatch):
        """Motor code-only guard blocks --session-close without AGENT_PROJECT_ROOT."""
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(agent_controller, "is_motor_code_only", lambda: True)

        test_argv = ["agent_controller.py", "--session-close"]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(agent_controller, "_ensure_runtime_dirs", lambda: None)
        monkeypatch.setattr(agent_controller, "_get_event_bus", lambda: None)

        exit_code = agent_controller.main()
        assert exit_code == 1


# ======================================================================
# WT-2026-181: Dual WP-/WT- prefix regression tests
# ======================================================================


class TestDualPrefixParsing:
    """Verify parsers accept both WP- and WT- prefixes identically."""

    def test_get_plan_id_extracts_wp(self):
        """get_plan_id() extracts WP-2026-XXX correctly."""
        content = "# Work Plan\n- **ID:** WP-2026-100\n- **Estado:** APPROVED\n"
        assert agent_controller.get_plan_id(content) == "WP-2026-100"

    def test_get_plan_id_extracts_wt(self):
        """get_plan_id() extracts WT-2026-XXX correctly."""
        content = "# Work Plan\n- **ID:** WT-2026-100\n- **Estado:** APPROVED\n"
        assert agent_controller.get_plan_id(content) == "WT-2026-100"

    def test_get_plan_id_extracts_wp_from_plan_id_label(self):
        """get_plan_id() handles **Plan ID:** label with WP- prefix."""
        content = "# Work Plan\n- **Plan ID:** WP-2026-100\n"
        assert agent_controller.get_plan_id(content) == "WP-2026-100"

    def test_get_plan_id_extracts_wt_from_plan_id_label(self):
        """get_plan_id() handles **Plan ID:** label with WT- prefix."""
        content = "# Work Plan\n- **Plan ID:** WT-2026-100\n"
        assert agent_controller.get_plan_id(content) == "WT-2026-100"

    def test_get_plan_id_returns_na_for_missing(self):
        """get_plan_id() returns N/A when no ID is present."""
        content = "# Work Plan\n- **Estado:** PENDING\n"
        assert agent_controller.get_plan_id(content) == "N/A"

    def test_validation_accepts_wp_ticket_in_work_plan(self, monkeypatch):
        """get_plan_id() extracts WP- from work_plan content and returns dict result."""
        wp_content = "# Work Plan\n- **ID:** WP-2026-100\n- **Estado:** APPROVED\n- **deliverable_type:** code\n"
        plan_id = agent_controller.get_plan_id(wp_content)
        assert plan_id == "WP-2026-100"

    def test_validation_accepts_wt_ticket_in_work_plan(self, monkeypatch):
        """get_plan_id() extracts WT- from work_plan content."""
        wp_content = "# Work Plan\n- **ID:** WT-2026-100\n- **Estado:** APPROVED\n- **deliverable_type:** code\n"
        plan_id = agent_controller.get_plan_id(wp_content)
        assert plan_id == "WT-2026-100"


# ======================================================================
# WT-2026-188: Closeout commit validation and state cleanup tests
# ======================================================================


class TestCloseoutCommitValidation:
    """WT-2026-188: Validate closeout commit message.

    Tests the pure _validate_closeout_commit_message() helper.
    """

    _ACTIVE_ID = "WT-2026-188"

    def test_manager_approve_rejects_generic_checkpoint_commit_message(self):
        """Checkpoint with correct ID is rejected (generic pre-handoff)."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "chore(WT-2026-188): pre-handoff checkpoint", self._ACTIVE_ID
        )
        assert not valid
        # The commit contains both "pre-handoff" and "checkpoint"; either may
        # be reported first depending on iteration order
        assert any(kw in reason.lower() for kw in ("checkpoint", "pre-handoff"))

    def test_manager_approve_rejects_commit_message_with_wrong_ticket_id(self):
        """Message referencing a valid but different ticket ID is rejected."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "feat(WT-2026-187): improve closeout validation", self._ACTIVE_ID
        )
        assert not valid, f"Expected invalid, got reason: {reason}"
        # Must detect that WT-2026-187 != WT-2026-188
        assert "WT-2026-187" in reason

    def test_manager_approve_rejects_commit_message_without_ticket_id(self):
        """Message without any ticket ID is rejected."""
        valid, _reason = agent_controller._validate_closeout_commit_message(
            "fix: minor cleanup", self._ACTIVE_ID
        )
        assert not valid

    def test_manager_approve_accepts_commit_message_with_active_ticket_id(self):
        """Message with correct ID and descriptive content is accepted."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "feat(WT-2026-188): validate canonical closeout commit hygiene",
            self._ACTIVE_ID,
        )
        assert valid, f"Expected valid, got: {reason}"

    def test_manager_approve_accepts_canonical_closeout_message_with_active_ticket_id(
        self,
    ):
        """Canonical format 'TICKET-ID: msg' (no Conventional Commits) is accepted."""
        valid, reason = agent_controller._validate_closeout_commit_message(
            "WT-2026-188: canonical closeout", self._ACTIVE_ID
        )
        assert valid, f"Expected valid, got: {reason}"


class TestManagerApproveStateCleanup:
    """WT-2026-188: --manager-approve clears auxiliary state files."""

    def test_manager_approve_clears_manager_bridge_state(self, tmp_path, monkeypatch):
        """manager_bridge_state.json is removed after closeout."""
        state_file = tmp_path / "manager_bridge_state.json"
        state_file.write_text('{"last_processed_sequence": 42}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", state_file)
        monkeypatch.setattr(
            agent_controller,
            "_SUPERVISOR_STATE_PATH",
            tmp_path / "supervisor_state.json",
        )
        assert state_file.exists()
        agent_controller._clear_auxiliary_states("WT-2026-188")
        assert not state_file.exists()

    def test_manager_approve_clears_supervisor_state(self, tmp_path, monkeypatch):
        """supervisor_state.json is removed after closeout."""
        state_file = tmp_path / "supervisor_state.json"
        state_file.write_text('{"active_ticket": "WT-2026-188"}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", state_file)
        monkeypatch.setattr(
            agent_controller,
            "_MANAGER_BRIDGE_STATE_PATH",
            tmp_path / "manager_bridge_state.json",
        )
        assert state_file.exists()
        agent_controller._clear_auxiliary_states("WT-2026-188")
        assert not state_file.exists()

    def test_clear_does_not_fail_on_missing(self, tmp_path, monkeypatch):
        """Clearing non-existent state files is a no-op (no exception)."""
        monkeypatch.setattr(
            agent_controller,
            "_MANAGER_BRIDGE_STATE_PATH",
            tmp_path / "nonexistent_mgr.json",
        )
        monkeypatch.setattr(
            agent_controller,
            "_SUPERVISOR_STATE_PATH",
            tmp_path / "nonexistent_sup.json",
        )
        # Should not raise even if files don't exist
        agent_controller._clear_auxiliary_states("WT-2026-188")

    def test_clear_removes_both_files(self, tmp_path, monkeypatch):
        """Both auxiliary state files are removed by a single call."""
        mgr = tmp_path / "manager_bridge_state.json"
        sup = tmp_path / "supervisor_state.json"
        mgr.write_text("{}", encoding="utf-8")
        sup.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", mgr)
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", sup)

        agent_controller._clear_auxiliary_states("WT-2026-188")

        assert not mgr.exists()
        assert not sup.exists()


# ======================================================================
# WT-2026-188: _handle_manager_approve integration tests
# These tests call _handle_manager_approve directly to prove the full flow,
# not just the isolated helpers.
# ======================================================================


class TestHandleManagerApproveIntegration:
    """WT-2026-188: _handle_manager_approve exercises full closeout flow.

    Proves that the handler:
    - Blocks on generic checkpoint commits
    - Blocks on wrong ticket ID in commit
    - Blocks on missing ticket ID in commit
    - Calls _clear_auxiliary_states on successful approve
    """

    _TICKET = "WT-2026-188"

    _WORK_PLAN = (
        "# Work Ticket - WT-2026-188\n"
        "## Metadata\n"
        "- **ID:** WT-2026-188\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n"
    )

    _EXEC_LOG_READY = "# Execution Log WT-2026-188\n\n**Estado:** READY_FOR_REVIEW\n"

    def _setup(self, monkeypatch, tmp_path, commit_msg: str):
        """Patch minimal scaffolding so _handle_manager_approve can run."""
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda p: (
                self._WORK_PLAN if "work_plan" in str(p) else self._EXEC_LOG_READY
            ),
        )
        monkeypatch.setattr(agent_controller, "BUS_AVAILABLE", False)
        monkeypatch.setattr(agent_controller, "event_bus", None)
        monkeypatch.setattr(
            agent_controller, "_sync_markdowns_to_completed", lambda tid: None
        )
        monkeypatch.setattr(
            agent_controller, "_reset_circuit_breaker", lambda tid: None
        )
        monkeypatch.setattr(agent_controller, "_release_builder_lock", lambda tid: None)
        monkeypatch.setattr(
            agent_controller, "_emit_manager_approve_cascade", lambda bus, tid: None
        )
        # Patch commit check to return the supplied message
        monkeypatch.setattr(
            agent_controller,
            "_check_last_commit",
            lambda root, tid: agent_controller._validate_closeout_commit_message(
                commit_msg, tid
            ),
        )
        # Wire real state files into tmp_path
        mgr = tmp_path / "manager_bridge_state.json"
        sup = tmp_path / "supervisor_state.json"
        mgr.write_text('{"seq": 1}', encoding="utf-8")
        sup.write_text('{"active_ticket": "WT-2026-188"}', encoding="utf-8")
        monkeypatch.setattr(agent_controller, "_MANAGER_BRIDGE_STATE_PATH", mgr)
        monkeypatch.setattr(agent_controller, "_SUPERVISOR_STATE_PATH", sup)
        return mgr, sup

    def test_blocks_on_generic_checkpoint_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 for a checkpoint commit with correct ID."""
        self._setup(monkeypatch, tmp_path, "chore(WT-2026-188): pre-handoff checkpoint")
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on generic checkpoint commit"

    def test_blocks_on_wrong_ticket_id_in_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 when commit references a different ticket."""
        self._setup(
            monkeypatch, tmp_path, "feat(WT-2026-187): improve closeout validation"
        )
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on wrong ticket ID in commit"

    def test_blocks_on_missing_ticket_id_in_commit(self, monkeypatch, tmp_path):
        """_handle_manager_approve returns 1 when commit has no ticket ID."""
        self._setup(monkeypatch, tmp_path, "fix: minor cleanup")
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 1, "Expected block on commit without ticket ID"

    def test_clears_auxiliary_states_on_approve(self, monkeypatch, tmp_path):
        """_handle_manager_approve deletes both state files on successful close."""
        mgr, sup = self._setup(
            monkeypatch,
            tmp_path,
            "feat(WT-2026-188): validate canonical closeout commit hygiene",
        )
        assert mgr.exists() and sup.exists()
        rc = agent_controller._handle_manager_approve(self._TICKET, False, False)
        assert rc == 0, f"Expected success, got rc={rc}"
        assert not mgr.exists(), "manager_bridge_state.json must be deleted on approve"
        assert not sup.exists(), "supervisor_state.json must be deleted on approve"


# ======================================================================
# WT-2026-188 Phase 4: Builder ready evidence gate tests
# ======================================================================


class TestImplementationEvidenceGate:
    """WP-2026-188 Phase 4: _check_implementation_evidence pure function tests.

    Tests the four required scenarios:
    - Rejects when only .agent/collaboration/ files changed
    - Rejects when execution_log.md has only boilerplate
    - Rejects when Files Likely Touched not in diff (best-effort)
    - Accepts when real file changed and log has evidence
    """

    _PLAN_ID = "WT-2026-188"
    # Minimal plan content with Files Likely Touched
    _PLAN_WITH_FILES = """# Work Plan

## Metadata
- **ID:** WT-2026-188
- **Estado:** APPROVED
- **deliverable_type:** code

## Files Likely Touched
- `src/module.py`
- `tests/test_module.py`
"""

    _PLAN_WITHOUT_FILES = """# Work Plan

## Metadata
- **ID:** WT-2026-188
- **Estado:** APPROVED
"""

    # Non-boilerplate execution log content (includes quality gate evidence for WT-2026-203)
    _LOG_WITH_EVIDENCE = """# Execution Log

**Estado:** IN_PROGRESS

- Implemented closeout commit validation
- Added `_check_implementation_evidence` function
- Ran quality gates: ruff, pytest
- All checks passed
"""

    # Boilerplate-only log
    _LOG_BOILERPLATE = """# Execution Log

**Estado:** IN_PROGRESS

Marked ready by Builder

Marked ready by Builder
"""

    @staticmethod
    def _make_git_mock(changed_files: list[str], plan_in_log: bool = True) -> MagicMock:
        """Create a subprocess.run mock that returns specific git diff output.

        Args:
            changed_files: list of file paths to return from git diff --name-only
            plan_in_log: if True, git log --oneline includes the plan_id
        """
        mock_stdout = "\n".join(changed_files)

        def mock_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "diff --name-only" in cmd_str and "--cached" not in cmd_str:
                return MagicMock(returncode=0, stdout=mock_stdout, stderr="")
            if "diff --cached --name-only" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "log -1 --name-only" in cmd_str:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "log --oneline" in cmd_str:
                if plan_in_log:
                    return MagicMock(
                        returncode=0,
                        stdout="7a3c596 WT-2026-188: some change\n",
                        stderr="",
                    )
                return MagicMock(
                    returncode=0, stdout="abc1234 other ticket\n", stderr=""
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        return MagicMock(side_effect=mock_run)

    def test_rejects_when_only_collaboration_files_changed(self, monkeypatch):
        """Evidence gate rejects when only .agent/collaboration/ files changed."""
        # Simulate git diff showing only collaboration files
        git_mock = self._make_git_mock(
            [
                ".agent/collaboration/execution_log.md",
                ".agent/collaboration/notifications.md",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock work_plan and execution_log reads
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_WITH_EVIDENCE
                if "execution_log.md" in str(x)
                else self._PLAN_WITHOUT_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should reject: no implementation files outside collaboration
        assert any("No implementation evidence" in err for err in errors), (
            f"Expected no-implementation-evidence error, got: {errors}"
        )

    def test_rejects_when_execution_log_has_only_boilerplate(self, monkeypatch):
        """Evidence gate rejects when execution_log.md has only boilerplate."""
        # Simulate git diff showing a real file change
        git_mock = self._make_git_mock(
            [
                "src/module.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock work_plan and execution_log reads - boilerplate log
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_BOILERPLATE
                if "execution_log.md" in str(x)
                else self._PLAN_WITHOUT_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should reject: log has only boilerplate
        assert any("boilerplate" in err.lower() for err in errors), (
            f"Expected boilerplate error, got: {errors}"
        )

    def test_rejects_when_files_likely_touched_not_in_diff(self, monkeypatch):
        """Evidence gate rejects (best-effort) when Files Likely Touched not in diff."""
        # Simulate git diff showing files NOT in Files Likely Touched
        git_mock = self._make_git_mock(
            [
                "unrelated/other.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: work_plan has Files Likely Touched section, log has evidence

        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {
                "src/module.py",
                "tests/test_module.py",
            },
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # Should produce Files Likely Touched mismatch error (best-effort)
        assert any("Files Likely Touched" in err for err in errors), (
            f"Expected Files Likely Touched error, got: {errors}"
        )

    def test_accepts_when_real_file_changed_and_log_has_evidence(self, monkeypatch):
        """Evidence gate accepts when real file changed and log has evidence."""
        # Simulate git diff showing a real implementation file
        git_mock = self._make_git_mock(
            [
                "src/module.py",
            ]
        )
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: work_plan with files, log with evidence
        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {
                "src/module.py",
                "tests/test_module.py",
            },
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        # All checks should pass
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_gate_is_unconditional(self, monkeypatch):
        """Evidence gate is never bypassed: rejects even when no diff exists."""
        monkeypatch.setattr(agent_controller, "_collect_git_diff_files", lambda: [])
        monkeypatch.setattr(
            agent_controller, "_check_git_log_has_plan_id", lambda pid: False
        )
        monkeypatch.setattr(
            agent_controller, "_check_log_has_quality_gate_evidence", lambda: False
        )
        monkeypatch.setattr(agent_controller, "read_file", lambda name: "")
        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert errors, "Evidence gate must reject when there is no real implementation"

    # ===== WT-2026-203: New evidence gate tests =====

    def test_rejects_when_git_log_misses_plan_id(self, monkeypatch):
        """TP-01: --mark-ready blocks if git log --oneline -20 lacks plan_id."""
        # Simulate git diff showing real file change
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=False)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Mock reads: log has quality gate evidence, plan exists
        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                self._LOG_WITH_EVIDENCE
                if "execution_log.md" in str(x)
                else self._PLAN_WITH_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert any("commit evidence" in err.lower() for err in errors), (
            f"Expected commit evidence error, got: {errors}"
        )

    def test_rejects_when_log_lacks_quality_gate_evidence(self, monkeypatch):
        """TP-02: --mark-ready blocks if execution_log.md lacks pytest/ruff/passed."""
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=True)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        # Log without quality gate keywords but with non-boilerplate content
        # (passes the non-boilerplate check but fails the stricter quality gate check)
        log_no_qg = """# Execution Log

**Estado:** IN_PROGRESS

- Implemented the feature
- All tests were run manually
- Ready for review
"""

        monkeypatch.setattr(
            agent_controller,
            "read_file",
            lambda x: (
                log_no_qg if "execution_log.md" in str(x) else self._PLAN_WITH_FILES
            ),
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert any("quality gate" in err.lower() for err in errors), (
            f"Expected quality gate evidence error, got: {errors}"
        )

    def test_accepts_when_all_new_checks_pass(self, monkeypatch):
        """All WT-2026-203 checks pass when git log has plan_id and log has QG evidence."""
        git_mock = self._make_git_mock(["src/module.py"], plan_in_log=True)
        monkeypatch.setattr(agent_controller.subprocess, "run", git_mock)

        def mock_read(path):
            name = str(path).replace("\\", "/")
            if "execution_log.md" in name:
                return self._LOG_WITH_EVIDENCE
            if "work_plan.md" in name:
                return self._PLAN_WITH_FILES
            return ""

        monkeypatch.setattr(agent_controller, "read_file", mock_read)
        monkeypatch.setattr(
            agent_controller,
            "parse_files_likely_touched",
            lambda x: {"src/module.py"},
        )

        errors = agent_controller._check_implementation_evidence(self._PLAN_ID)
        assert errors == [], f"Expected no errors, got: {errors}"


# =============================================================================
# Tests WT-2026-204: helpers de validacion de blockers y AUTO-REJECT
# =============================================================================


class TestValidateTurnBlockersContent:
    """WT-2026-204: _validate_turn_blockers_content helper."""

    def test_valid_non_empty_blockers(self):
        """Valid non-empty blockers return True."""
        assert (
            agent_controller._validate_turn_blockers_content(
                "- bus/parser.py: fix edge case"
            )
            is True
        )

    def test_empty_blockers_return_false(self):
        """Empty or whitespace-only blockers return False."""
        assert agent_controller._validate_turn_blockers_content("") is False
        assert agent_controller._validate_turn_blockers_content("   ") is False

    def test_oversized_blockers_return_false(self):
        """Blockers exceeding 15 KB return False."""
        big_blockers = "- file.py: " + "x" * (16 * 1024)
        assert agent_controller._validate_turn_blockers_content(big_blockers) is False

    def test_jsonl_crudo_blockers_return_false(self):
        """Blockers containing raw JSONL markers return False."""
        assert (
            agent_controller._validate_turn_blockers_content(
                '{"type":"text","part":{...}}'
            )
            is False
        )
        assert (
            agent_controller._validate_turn_blockers_content(
                "some text sessionID=abc123"
            )
            is False
        )


class TestAutoRejectQualityGates:
    """WT-2026-204: _check_quality_gates AUTO-REJECT path."""

    def test_auto_reject_has_distinct_instruction(self):
        """AUTO-REJECT produces distinct instruction without builder_rules refs."""
        with (
            patch(
                "agent_controller.run_quality_gates",
                return_value={
                    "passed": False,
                    "errors": [],
                    "summary": [],
                    "warnings": [],
                },
            ),
            patch("agent_controller.update_log_status"),
        ):
            result = agent_controller._check_quality_gates(
                plan_id="WT-2026-204",
                plan_type="IMPLEMENTATION",
                plan_status="APPROVED",
                skip_gates=False,
            )

        assert result is not None
        assert result["role"] == "BUILDER"
        # Must not reference old files
        assert result["context_file"] != ".builder_rules"
        assert result["workflow_file"] != ".agent/workflows/builder_workflow.md"
        # Must have distinct instruction
        assert "AUTO-REJECTED" in result["instruction"]
        assert result["instruction"] != (
            "RECHAZADO. Quality Gates fallaron. Corrige errores."
        )
        assert result["action_type"] == "FIX_QUALITY_ISSUES"

    def test_auto_reject_logs_auto_rejected_status(self):
        """AUTO-REJECT updates log status to AUTO-REJECTED."""
        logged_status = {}

        def fake_update_log_status(status, note):
            logged_status["status"] = status
            logged_status["note"] = note

        with (
            patch(
                "agent_controller.run_quality_gates",
                return_value={
                    "passed": False,
                    "errors": [],
                    "summary": [],
                    "warnings": [],
                },
            ),
            patch("agent_controller.update_log_status", fake_update_log_status),
        ):
            agent_controller._check_quality_gates(
                plan_id="WT-2026-204",
                plan_type="IMPLEMENTATION",
                plan_status="APPROVED",
                skip_gates=False,
            )

        assert logged_status.get("status") == "IN_PROGRESS"
        assert "AUTO-REJECTED" in logged_status.get("note", "")
