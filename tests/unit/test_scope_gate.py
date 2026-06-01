"""Tests for scope gate functionality in agent_controller.py."""

import sys
from pathlib import Path
from unittest.mock import patch


# Add the agent directory to path for imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import (  # noqa: E402
    _exclude_files,
    _handle_mark_ready,
    _scope_gate_allows_close,
    check_scope_gate,
    get_changed_files,
    parse_files_likely_touched,
)


class TestParseFilesLikelyTouched:
    """Test parsing of Files Likely Touched section."""

    def test_parse_simple_files(self):
        """Test parsing simple file list."""
        content = """
## Files Likely Touched

- file1.py
- file2.md
- `file3.txt`
- "file4.json"

## Next Section
"""
        files = parse_files_likely_touched(content)
        expected = {
            str((Path.cwd() / "file1.py").resolve()),
            str((Path.cwd() / "file2.md").resolve()),
            str((Path.cwd() / "file3.txt").resolve()),
            str((Path.cwd() / "file4.json").resolve()),
        }
        assert files == expected

    def test_parse_no_section(self):
        """Test parsing when no section exists."""
        content = "Some other content"
        files = parse_files_likely_touched(content)
        assert files == set()

    def test_parse_empty_section(self):
        """Test parsing empty section."""
        content = """
## Files Likely Touched

## Next Section
"""
        files = parse_files_likely_touched(content)
        assert files == set()

    def test_parse_with_bullets_and_quotes(self):
        """Test parsing with various formats."""
        content = """
## Files Likely Touched

* file1.py
- file2.md
`file3.txt`
"file4.json"
file5.py

## Next
"""
        files = parse_files_likely_touched(content)
        expected = {
            str((Path.cwd() / f"file{i}.{ext}").resolve())
            for i, ext in [(1, "py"), (2, "md"), (3, "txt"), (4, "json"), (5, "py")]
        }
        assert files == expected


class TestGetChangedFiles:
    """Test getting changed files from git."""

    @patch("subprocess.run")
    @patch("agent_controller.PROJECT_ROOT", Path("/fake/root"))
    def test_get_changed_files_no_git(self, mock_run):
        """Test when no .git directory."""
        with patch("pathlib.Path.exists", return_value=False):
            result = get_changed_files()
            assert result is None

    @patch("subprocess.run")
    @patch("agent_controller.PROJECT_ROOT", Path("/fake/root"))
    def test_get_changed_files_git_status(self, mock_run):
        """Test parsing git status output with null-byte separator."""
        # Format: "XY path\0" for each entry, renames have two entries "R old\0new\0"
        mock_run.return_value.stdout = (
            "M file1.py\0A file2.md\0D file3.txt\0R old.py\0new.py\0?? untracked.json\0"
        )
        mock_run.return_value.returncode = 0
        with patch("pathlib.Path.exists", return_value=True):
            result = get_changed_files()
            expected = {
                str((Path("/fake/root") / "file1.py").resolve()),
                str((Path("/fake/root") / "file2.md").resolve()),
                str((Path("/fake/root") / "file3.txt").resolve()),
                str((Path("/fake/root") / "new.py").resolve()),
                str((Path("/fake/root") / "untracked.json").resolve()),
            }
            assert result == expected

    @patch("subprocess.run")
    @patch("agent_controller.PROJECT_ROOT", Path("/fake/root"))
    def test_get_changed_files_rename_format(self, mock_run):
        """Test parsing rename with proper porcelain -z format."""
        # Rename: R old.py\0new.py\0
        mock_run.return_value.stdout = "R old.py\0new.py\0"
        mock_run.return_value.returncode = 0
        with patch("pathlib.Path.exists", return_value=True):
            result = get_changed_files()
            # Should only add the new path, not the old one
            expected = {str((Path("/fake/root") / "new.py").resolve())}
            assert result == expected
            assert str((Path("/fake/root") / "old.py").resolve()) not in result

    @patch("subprocess.run")
    @patch("agent_controller.PROJECT_ROOT", Path("/fake/root"))
    def test_get_changed_files_path_with_spaces(self, mock_run):
        """Test parsing paths with spaces using null-byte separator."""
        # Path with spaces: "M file with spaces.py\0"
        mock_run.return_value.stdout = "M file with spaces.py\0?? another file.md\0"
        mock_run.return_value.returncode = 0
        with patch("pathlib.Path.exists", return_value=True):
            result = get_changed_files()
            expected = {
                str((Path("/fake/root") / "file with spaces.py").resolve()),
                str((Path("/fake/root") / "another file.md").resolve()),
            }
            assert result == expected


class TestCheckScopeGate:
    """Test scope gate checking."""

    def test_check_scope_gate_no_whitelist(self):
        """Test when no whitelist section."""
        content = "No section"
        changed = {"/path/file.py"}
        result = check_scope_gate(content, changed, set())
        assert result["valid"] is True
        assert result["out_of_scope"] == set()
        assert "No Files Likely Touched" in str(result["warnings"])

    def test_check_scope_gate_no_git(self):
        """Test when not git repo."""
        content = "## Files Likely Touched\n- file.py"
        result = check_scope_gate(content, None, set())
        # Ensure standard exclusions are present
        exclude_files = _exclude_files()
        assert any("events.jsonl" in path for path in exclude_files)
        assert "not git-managed" in str(result["warnings"])

    def test_check_scope_gate_in_scope(self):
        """Test files within scope."""
        content = "## Files Likely Touched\n- file.py"
        changed = {str(Path.cwd() / "file.py")}
        result = check_scope_gate(content, changed, set())
        assert result["valid"] is True
        assert result["out_of_scope"] == set()

    def test_check_scope_gate_zero_overlap_blocks(self):
        """Test zero overlap blocks closeout."""
        content = "## Files Likely Touched\n- file.py"
        result = check_scope_gate(content, set(), set())
        assert result["valid"] is False
        assert str(Path.cwd() / "file.py") in result["missing_from_diff"]
        assert "None of the declared Files Likely Touched entries" in str(
            result["blocked_reason"]
        )

    def test_check_scope_gate_partial_overlap_warns(self):
        """Test partial overlap warns but does not block."""
        content = """
## Files Likely Touched
- file.py
- other.py
"""
        changed = {str(Path.cwd() / "file.py")}
        result = check_scope_gate(content, changed, set())
        assert result["valid"] is True
        assert str(Path.cwd() / "other.py") in result["missing_from_diff"]
        assert any(
            "Partial scope coverage" in warning for warning in result["warnings"]
        )

    def test_check_scope_gate_out_of_scope(self):
        """Test files out of scope."""
        content = "## Files Likely Touched\n- allowed.py"
        changed = {str(Path.cwd() / "allowed.py"), str(Path.cwd() / "forbidden.py")}
        result = check_scope_gate(content, changed, set())
        assert result["valid"] is False
        assert str(Path.cwd() / "forbidden.py") in result["out_of_scope"]

    def test_check_scope_gate_exclude_files(self):
        """Test excluded files are ignored."""
        content = "## Files Likely Touched\n- allowed.py"
        changed = {str(Path.cwd() / "allowed.py"), str(Path.cwd() / "excluded.py")}
        exclude = {str(Path.cwd() / "excluded.py")}
        result = check_scope_gate(content, changed, exclude)
        assert result["valid"] is True
        assert result["out_of_scope"] == set()


class TestHandleMarkReadyScopeGate:
    """Test that --mark-ready stops on zero-overlap scope failures."""

    @patch("agent_controller._emit_builder_exit")
    @patch("agent_controller._auto_archive_closed_artifacts")
    @patch("agent_controller._sync_mark_ready_targets")
    @patch("agent_controller._reset_circuit_breaker")
    @patch("agent_controller._release_builder_lock")
    @patch("agent_controller._check_circuit_breaker")
    @patch("agent_controller.get_changed_files", return_value=set())
    @patch("agent_controller.read_file")
    def test_mark_ready_blocks_on_zero_overlap(
        self,
        mock_read_file,
        mock_get_changed_files,
        mock_check_breaker,
        mock_release_lock,
        mock_reset_breaker,
        mock_sync_targets,
        mock_archive,
        mock_emit_exit,
    ):
        """Test --mark-ready returns failure before any closeout side effects."""
        plan_content = """# Work Plan

**ID:** WP-2026-142
**Estado:** APPROVED

## Files Likely Touched
- file.py
"""
        log_content = "# Execution Log\n\n**Estado:** IN_PROGRESS"

        def _read_side_effect(path):
            path_str = str(path)
            if "work_plan.md" in path_str:
                return plan_content
            if "execution_log.md" in path_str:
                return log_content
            if "STATE.md" in path_str:
                return "# State\n\n- **Estado actual:** IN_PROGRESS"
            return ""

        mock_read_file.side_effect = _read_side_effect
        mock_check_breaker.return_value = {"open": False, "reason": None}

        result = _handle_mark_ready(
            scope_override=None, json_output=False, force_mode=False
        )

        assert result == 1
        mock_emit_exit.assert_not_called()
        mock_archive.assert_not_called()
        mock_sync_targets.assert_not_called()
        mock_reset_breaker.assert_not_called()
        mock_release_lock.assert_not_called()


class TestScopeGateHints:
    """Test actionable CL-08 hints for workspace memory files."""

    def test_scope_gate_prints_workspace_memory_hint(self, capsys):
        gate_result = {
            "valid": False,
            "out_of_scope": set(),
            "missing_from_diff": {
                str(
                    (
                        Path.cwd()
                        / ".agent"
                        / "runtime"
                        / "memory"
                        / "observations.jsonl"
                    ).resolve()
                )
            },
            "covered_files": set(),
            "warnings": [],
            "blocked_reason": "None of the declared Files Likely Touched entries appeared in the diff",
        }

        allowed = _scope_gate_allows_close(gate_result, scope_override=None)

        assert allowed is False
        output = capsys.readouterr().out
        assert "This is expected (CL-08)" in output
        assert "--scope-override" in output
        assert ".agent/runtime/memory/" in output
