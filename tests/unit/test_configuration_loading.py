"""
Tests for scripts/validate_agent_config.py â€” configuration loading functions.

Covers: allowlist/denylist loading from JSON, fallback to defaults, invalid JSON handling.
"""

import json

from scripts.validate_agent_config import (
    DEFAULT_ALLOWLIST,
    load_allowlist,
    load_denylist,
)


class TestAllowlistLoading:
    """Test loading of .agent_allowlist.json."""

    def test_load_allowlist_success(self, tmp_path, monkeypatch):
        """Test loading a valid allowlist file."""
        allow_data = {
            "write_roots": ["src/", "tests/"],
            "protected_paths": ["privada/"],
        }
        allow_file = tmp_path / ".agent_allowlist.json"
        allow_file.write_text(json.dumps(allow_data), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_allowlist()

        assert result["write_roots"] == ["src/", "tests/"]
        assert result["protected_paths"] == ["privada/"]

    def test_load_allowlist_missing_uses_defaults(self, tmp_path, monkeypatch):
        """Test that missing file falls back to defaults."""
        monkeypatch.chdir(tmp_path)
        result = load_allowlist()
        assert result == DEFAULT_ALLOWLIST

    def test_load_allowlist_invalid_json_uses_defaults(self, tmp_path, monkeypatch):
        """Test that malformed JSON falls back to defaults."""
        allow_file = tmp_path / ".agent_allowlist.json"
        allow_file.write_text("{invalid json}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = load_allowlist()
        assert result == DEFAULT_ALLOWLIST


class TestDenylistLoading:
    """Test loading of .agent_denylist.json."""

    def test_load_denylist_success(self, tmp_path, monkeypatch):
        """Test loading a valid denylist file."""
        deny_data = {"blocked_patterns": ["^secret/.*"], "blocked_commands": ["rm -rf"]}
        deny_file = tmp_path / ".agent_denylist.json"
        deny_file.write_text(json.dumps(deny_data), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_denylist()

        assert result["blocked_patterns"] == ["^secret/.*"]
        assert result["blocked_commands"] == ["rm -rf"]


class TestConfigurationValidation:
    """Test overall configuration validation."""

    def test_configuration_validation_logic(self, tmp_path, monkeypatch):
        """Test configuration loading in isolation."""
        allow = {"write_roots": ["src/"], "protected_paths": ["privada/"]}
        (tmp_path / ".agent_allowlist.json").write_text(
            json.dumps(allow), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)

        assert load_allowlist()["write_roots"] == ["src/"]
