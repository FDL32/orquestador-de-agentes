"""Tests for the Claude settings portability/security gate (WOT-2026-003c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent
# Import the gate module from scripts/ and the canonical entrypoint.
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / ".agent" / "hooks"))

import check_claude_settings_portability as gate  # noqa: E402
import claude_guard_entry  # noqa: E402


_CANONICAL = claude_guard_entry.canonical_hook_command()
_NON_CANONICAL = 'python -c "import sys; sys.exit(2)"'


def _settings(command: str = _CANONICAL, matcher: str = "Write|Edit|MultiEdit") -> dict:
    return {
        "hooks": {
            "PreToolUse": [
                {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
            ]
        }
    }


class TestPersonalGrants:
    def test_permissions_allow_flagged(self):
        violations = gate.check_no_personal_grants(
            {"permissions": {"allow": ["Bash(rm:*)"]}}
        )
        assert any("permissions.allow" in v for v in violations)

    def test_no_permissions_is_clean(self):
        assert gate.check_no_personal_grants(_settings()) == []


class TestWriteGuardPresent:
    def test_missing_pretooluse_is_flagged(self):
        violations = gate.check_write_guard_present({"hooks": {}})
        assert violations and "no PreToolUse hook gates writes" in violations[0]

    def test_read_only_matcher_is_flagged(self):
        # A guard that only matches Read does not cover writes.
        violations = gate.check_write_guard_present(_settings(matcher="Read"))
        assert violations and "no PreToolUse hook gates writes" in violations[0]

    def test_partial_matcher_is_flagged(self):
        # Covers Write but not Edit/MultiEdit.
        violations = gate.check_write_guard_present(_settings(matcher="Write"))
        assert violations and "does not cover" in violations[0]
        assert "Edit" in violations[0] and "MultiEdit" in violations[0]

    def test_full_matcher_passes(self):
        assert gate.check_write_guard_present(_settings()) == []


class TestCommandCanonical:
    def test_non_canonical_command_flagged(self):
        violations = gate.check_command_is_canonical(_settings(command=_NON_CANONICAL))
        assert violations and "canonical" in violations[0]

    def test_canonical_command_passes(self):
        assert gate.check_command_is_canonical(_settings()) == []


class TestEntrypointFailsClosed:
    def test_real_entrypoint_fails_closed(self):
        # The shipped claude_guard_entry.py must fail closed with no guard.
        assert gate.check_entrypoint_fails_closed() == []


class TestFileAndMain:
    def test_clean_canonical_file_returns_zero(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps(_settings()), encoding="utf-8")
        assert gate.check_settings_file(p) == []
        assert gate.main([str(p)]) == 0

    def test_dirty_file_returns_one(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        bad = _settings(command=_NON_CANONICAL, matcher="Write")
        bad["permissions"] = {"allow": ["Bash(python3:*)"]}
        p.write_text(json.dumps(bad), encoding="utf-8")
        violations = gate.check_settings_file(p)
        assert any("permissions.allow" in v for v in violations)
        assert any("does not cover" in v for v in violations)
        assert any("canonical" in v for v in violations)
        assert gate.main([str(p)]) == 1

    def test_missing_file_is_clean(self, tmp_path: Path):
        assert gate.check_settings_file(tmp_path / "nope.json") == []

    def test_dir_argument_resolves_claude_settings(self, tmp_path: Path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(json.dumps(_settings()), encoding="utf-8")
        assert gate.main([str(tmp_path)]) == 0

    def test_real_motor_settings_pass(self):
        # The motor's own tracked settings must satisfy its own gate.
        assert gate.check_settings_file(_ROOT / ".claude" / "settings.json") == []


class TestFleetMode:
    def test_discover_destinations_finds_destinations(self, tmp_path: Path):
        """Simulate a parent dir with destination repos."""
        motor = tmp_path / "motor"
        motor.mkdir()
        dest1 = tmp_path / "dest_one"
        dest1.mkdir()
        (dest1 / ".agent").mkdir(parents=True)
        (dest1 / ".agent" / "config").mkdir()
        link1 = dest1 / ".agent" / "config" / "motor_destination_link.json"
        link1.write_text(json.dumps({"destination_root": str(dest1)}), encoding="utf-8")

        dest2 = tmp_path / "dest_two"
        dest2.mkdir()
        (dest2 / ".agent").mkdir(parents=True)
        (dest2 / ".agent" / "config").mkdir()
        link2 = dest2 / ".agent" / "config" / "motor_destination_link.json"
        link2.write_text(json.dumps({"destination_root": str(dest2)}), encoding="utf-8")

        result = gate._discover_destinations(motor)
        assert sorted([p.name for p in result]) == ["dest_one", "dest_two"]

    def test_discover_destinations_skips_missing_link(self, tmp_path: Path):
        """A dir without motor_destination_link.json is not a destination."""
        motor = tmp_path / "motor"
        motor.mkdir()
        (tmp_path / "not_a_dest").mkdir()
        assert gate._discover_destinations(motor) == []

    def test_fleet_check_no_settings_flagged(self, tmp_path: Path):
        """A destination without .claude/settings.json is reported as sin_settings."""
        motor = tmp_path / "motor"
        motor.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / ".agent").mkdir(parents=True)
        (dest / ".agent" / "config").mkdir()
        link = dest / ".agent" / "config" / "motor_destination_link.json"
        link.write_text(json.dumps({"destination_root": str(dest)}), encoding="utf-8")

        _violations, sin_settings, _missing_hook = gate.fleet_check(motor)
        assert dest.name in sin_settings

    def test_fleet_check_canonical_ok(self, tmp_path: Path):
        """A destination with valid canonical settings passes."""
        motor = tmp_path / "motor"
        motor.mkdir()
        # Create the entrypoint file so check_entrypoint_fails_closed works
        (motor / ".agent").mkdir(parents=True)
        (motor / ".agent" / "hooks").mkdir()
        entrypoint = motor / ".agent" / "hooks" / "claude_guard_entry.py"
        entrypoint.write_text(
            "import sys\n"
            "def canonical_hook_command():\n"
            "    return 'python -c \"import sys; sys.exit(2)\"'\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(2)\n",
            encoding="utf-8",
        )

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / ".agent").mkdir(parents=True)
        (dest / ".agent" / "config").mkdir()
        link = dest / ".agent" / "config" / "motor_destination_link.json"
        link.write_text(
            json.dumps({"destination_root": str(dest), "motor_root": str(motor)}),
            encoding="utf-8",
        )
        # Create a canonical settings file
        (dest / ".claude").mkdir()
        (dest / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write|Edit|MultiEdit",
                                "hooks": [
                                    {"type": "command", "command": "fake-canonical"}
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        # Patch entrypoint path for the check_entrypoint_fails_closed
        _violations, sin_settings, _missing_hook = gate.fleet_check(motor)
        # No sin_settings since settings.json exists
        assert dest.name not in sin_settings

    def test_fleet_empty_when_no_destinations(self, tmp_path: Path):
        """No destinations = empty fleet report."""
        motor = tmp_path / "motor"
        motor.mkdir()
        violations, sin_settings, missing_hook = gate.fleet_check(motor)
        assert violations == []
        assert sin_settings == []
        assert missing_hook == []

    def test_check_hook_file_local_exists(self, tmp_path: Path):
        """Local hook file exists = clean."""
        (tmp_path / ".agent" / "hooks").mkdir(parents=True)
        (tmp_path / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
            "", encoding="utf-8"
        )
        assert gate.check_hook_file_exists(tmp_path) == []

    def test_check_hook_file_missing_local(self, tmp_path: Path):
        """No local hook file and no motor link = violation."""
        assert gate.check_hook_file_exists(tmp_path) != []

    def test_check_hook_file_resolved_via_motor_link(self, tmp_path: Path):
        """Hook file found via motor_destination_link.json = clean."""
        motor = tmp_path / "motor"
        (motor / ".agent" / "hooks").mkdir(parents=True)
        (motor / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
            "", encoding="utf-8"
        )
        (tmp_path / ".agent" / "config").mkdir(parents=True)
        (tmp_path / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor)}), encoding="utf-8"
        )
        assert gate.check_hook_file_exists(tmp_path) == []
