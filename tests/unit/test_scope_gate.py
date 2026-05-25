"""Tests for scope gate functionality in agent_controller.py."""

import sys
from pathlib import Path
from unittest.mock import patch


# Add the agent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from agent_controller import (
    EXCLUDE_FILES_REL,
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
        assert "events.jsonl" in EXCLUDE_FILES_REL
        assert "supervisor_state.json" in EXCLUDE_FILES_REL
        assert "not git-managed" in str(result["warnings"])

    def test_check_scope_gate_in_scope(self):
        """Test files within scope."""
        content = "## Files Likely Touched\n- file.py"
        changed = {str(Path.cwd() / "file.py")}
        result = check_scope_gate(content, changed, set())
        assert result["valid"] is True
        assert result["out_of_scope"] == set()

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
