"""Tests for the Claude settings portability/security gate (WOT-2026-003c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


# Import the gate module from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import check_claude_settings_portability as gate


# A hook that fails CLOSED (non-zero) when run with no resolvable guard.
_FAIL_CLOSED_CMD = 'python -c "import sys; sys.stdin.buffer.read(); sys.exit(2)"'
# A hook that fails OPEN (exit 0) regardless -- the anti-pattern.
_FAIL_OPEN_CMD = 'python -c "import sys; sys.stdin.buffer.read(); sys.exit(0)"'


def _hooks(command: str, matcher: str = "Write|Edit|MultiEdit") -> dict:
    return {
        "hooks": {
            "PreToolUse": [
                {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
            ]
        }
    }


class TestPersonalGrants:
    def test_permissions_allow_flagged(self):
        settings = {"permissions": {"allow": ["Bash(rm:*)", "WebFetch(domain:x.io)"]}}
        violations = gate.check_no_personal_grants(settings)
        assert any("permissions.allow" in v for v in violations)

    def test_no_permissions_is_clean(self):
        assert gate.check_no_personal_grants(_hooks(_FAIL_CLOSED_CMD)) == []

    def test_empty_allow_is_clean(self):
        assert gate.check_no_personal_grants({"permissions": {"allow": []}}) == []


class TestFailClosed:
    def test_fail_open_hook_is_flagged(self):
        violations = gate.check_hooks_fail_closed(_hooks(_FAIL_OPEN_CMD))
        assert violations, "a hook that exits 0 with no guard must be flagged"
        assert any("FAIL-OPEN" in v for v in violations)

    def test_fail_closed_hook_passes(self):
        assert gate.check_hooks_fail_closed(_hooks(_FAIL_CLOSED_CMD)) == []

    def test_non_gating_matcher_is_ignored(self):
        # A Read-only matcher must not be subjected to the fail-closed rule.
        settings = _hooks(_FAIL_OPEN_CMD, matcher="Read")
        assert gate.check_hooks_fail_closed(settings) == []


class TestFileAndMain:
    def test_clean_file_returns_zero(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps(_hooks(_FAIL_CLOSED_CMD)), encoding="utf-8")
        assert gate.check_settings_file(p) == []
        assert gate.main([str(p)]) == 0

    def test_dirty_file_returns_one(self, tmp_path: Path):
        p = tmp_path / "settings.json"
        bad = _hooks(_FAIL_OPEN_CMD)
        bad["permissions"] = {"allow": ["Bash(python3:*)"]}
        p.write_text(json.dumps(bad), encoding="utf-8")
        violations = gate.check_settings_file(p)
        assert any("permissions.allow" in v for v in violations)
        assert any("FAIL-OPEN" in v for v in violations)
        assert gate.main([str(p)]) == 1

    def test_missing_file_is_clean(self, tmp_path: Path):
        assert gate.check_settings_file(tmp_path / "nope.json") == []

    def test_dir_argument_resolves_claude_settings(self, tmp_path: Path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(
            json.dumps(_hooks(_FAIL_CLOSED_CMD)), encoding="utf-8"
        )
        assert gate.main([str(tmp_path)]) == 0
