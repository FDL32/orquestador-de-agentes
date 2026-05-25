"""Tests for guard_paths core logic."""

import json
import os
import sys
from pathlib import Path


# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from hooks.guard_paths import (  # noqa: E402
    DEFAULT_ALLOWLIST,
    _is_blocked_command,
    _is_protected_path,
    _normalize,
    _read_json,
    _tool_paths,
)


# Test workspace inside repository (writable without special permissions)
TEST_WORKSPACE = Path(__file__).parent / ".test_workspace"


def _clean_workspace():
    if TEST_WORKSPACE.exists():
        import shutil

        shutil.rmtree(TEST_WORKSPACE)


class TestNormalize:
    def test_normalize_lowercase_and_slashes(self):
        assert _normalize("C:\\Path\\To\\File") == "c:/path/to/file"
        assert _normalize("/Path/To/File") == "/path/to/file"
        assert _normalize("..\\..") == "../.."
        assert _normalize("../..") == "../.."


class TestReadJson:
    def test_read_json_valid(self):
        config_file = TEST_WORKSPACE / "config_valid.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        try:
            result = _read_json(config_file)
            assert result == {"key": "value"}
        finally:
            config_file.unlink(missing_ok=True)

    def test_read_json_invalid(self):
        config_file = TEST_WORKSPACE / "config_bad.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{invalid json}", encoding="utf-8")
        try:
            result = _read_json(config_file)
            assert result == {}
        finally:
            config_file.unlink(missing_ok=True)

    def test_read_json_missing(self):
        config_file = TEST_WORKSPACE / "nonexistent.json"
        result = _read_json(config_file)
        assert result == {}


class TestToolPaths:
    def test_extracts_single_path(self):
        assert _tool_paths({"file_path": "/path/to/file"}) == ["/path/to/file"]

    def test_extracts_multiple_paths(self):
        assert _tool_paths({"path": "/a", "target_path": "/b"}) == ["/a", "/b"]

    def test_ignores_empty_and_none(self):
        assert _tool_paths({"new_path": ""}) == []
        assert _tool_paths({"file_path": None}) == []

    def test_ignores_non_string_values(self):
        assert _tool_paths({"file_path": 123}) == []

    def test_returns_empty_when_no_candidates(self):
        assert _tool_paths({"other": "value"}) == []


class TestIsProtectedPath:
    def setup_method(self):
        _clean_workspace()
        self.repo_root = (TEST_WORKSPACE / "repo").resolve()
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self._orig_cwd = os.getcwd()
        os.chdir(self.repo_root)

    def teardown_method(self):
        os.chdir(self._orig_cwd)
        _clean_workspace()

    def test_outside_repo_blocked(self):
        outside = self.repo_root.parent / "outside.txt"
        blocked, reason = _is_protected_path(str(outside), DEFAULT_ALLOWLIST, {})
        assert blocked is True
        assert "fuera del repo" in reason

    def test_protected_pattern_blocked(self):
        priv = self.repo_root / "privada" / "secret.txt"
        priv.parent.mkdir(parents=True, exist_ok=True)
        priv.write_text("secret")
        blocked, reason = _is_protected_path(str(priv), DEFAULT_ALLOWLIST, {})
        assert blocked is True
        assert "ruta protegida" in reason

    def test_protected_filename_blocked(self):
        env_file = self.repo_root / ".env"
        env_file.write_text("KEY=value")
        blocked, reason = _is_protected_path(str(env_file), DEFAULT_ALLOWLIST, {})
        assert blocked is True
        assert "archivo protegido" in reason

    def test_additional_protected_filenames_blocked(self):
        protected_files = [
            ".env.local",
            ".env.production",
            "secrets.json",
            "credentials.json",
        ]
        for filename in protected_files:
            filepath = self.repo_root / filename
            filepath.write_text("content")
            blocked, reason = _is_protected_path(str(filepath), DEFAULT_ALLOWLIST, {})
            assert blocked is True
            assert "archivo protegido" in reason

    def test_token_patterns_blocked(self):
        token_file = self.repo_root / "token.txt"
        token_file.write_text("token123")
        blocked, reason = _is_protected_path(str(token_file), DEFAULT_ALLOWLIST, {})
        assert blocked is True
        assert "protegida por patron" in reason

    def test_default_allowlist_allows_inside_repo(self):
        src_dir = self.repo_root / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        src_file = src_dir / "main.py"
        src_file.write_text("print('hello')")
        blocked, reason = _is_protected_path(str(src_file), DEFAULT_ALLOWLIST, {})
        assert blocked is False
        assert reason == ""

    def test_custom_allowlist_allows_specific_root(self):
        src_dir = self.repo_root / "src"
        tests_dir = self.repo_root / "tests"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.py").write_text("")
        (tests_dir / "test_app.py").write_text("")
        allowlist = {"write_roots": ["src"]}
        src_file = src_dir / "app.py"
        tests_file = tests_dir / "test_app.py"
        blocked_src, _ = _is_protected_path(str(src_file), allowlist, {})
        blocked_tests, reason_tests = _is_protected_path(str(tests_file), allowlist, {})
        assert blocked_src is False
        assert blocked_tests is True
        assert ("write_roots" in reason_tests) or (
            "fuera de write_roots" in reason_tests
        )

    def test_case_insensitive_protected_filename(self):
        env_upper = self.repo_root / ".ENV"
        env_upper.write_text("")
        blocked, reason = _is_protected_path(str(env_upper), DEFAULT_ALLOWLIST, {})
        assert blocked is True
        assert "archivo protegido" in reason


class TestIsBlockedCommand:
    def test_path_traversal_blocked(self):
        blocked, reason = _is_blocked_command("cat ../../etc/passwd", {})
        assert blocked is True
        assert "path traversal" in reason.lower()

    def test_protected_refs_blocked(self):
        blocked, reason = _is_blocked_command("cat .env", {})
        assert blocked is True
        assert "sensibles" in reason

    def test_blocked_rm_rf(self):
        blocked, reason = _is_blocked_command("rm -rf /", {})
        assert blocked is True
        assert "bloqueado" in reason.lower()

    def test_blocked_git_push_force(self):
        blocked, _ = _is_blocked_command("git push --force origin main", {})
        assert blocked is True

    def test_blocked_git_reset_hard(self):
        blocked, _ = _is_blocked_command("git reset --hard", {})
        assert blocked is True

    def test_blocked_token_references(self):
        blocked_commands = [
            "echo sk-ant-api03-token123",
            "cat api_key.txt",
            "grep password file.txt",
            "sed 's/bearer.*//' config.json",
        ]
        for cmd in blocked_commands:
            blocked, reason = _is_blocked_command(cmd, {})
            assert blocked is True
            assert "sensibles" in reason or "protegido" in reason

    def test_blocked_destructive_commands(self):
        destructive_cmds = [
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sdb",
            "fdisk /dev/sdc",
            "format c:",
            "del /f /s /q *",
        ]
        for cmd in destructive_cmds:
            blocked, reason = _is_blocked_command(cmd, {})
            assert blocked is True
            assert "destructivo" in reason or "bloqueado" in reason

    def test_allowed_simple_command(self):
        blocked, reason = _is_blocked_command("ls -la", {})
        assert blocked is False
        assert reason == ""

    def test_custom_blocked_pattern(self):
        denylist = {"blocked_command_patterns": [r"dangerous_command"]}
        blocked, reason = _is_blocked_command("run dangerous_command --force", denylist)
        assert blocked is True
        assert "bloqueado" in reason.lower()

    def test_backslash_path_traversal(self):
        blocked, reason = _is_blocked_command("del ..\\..\\file.txt", {})
        assert blocked is True
        assert "path traversal" in reason.lower()
