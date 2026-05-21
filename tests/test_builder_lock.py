"""Tests for builder_lock.txt schema and contract.

WP-2026-117: Builder lock PID cleanup.

The builder lock must contain only minimal operational metadata:
- ticket_id: the active ticket being worked on
- started_at: ISO 8601 timestamp for TTL-based stale detection

The lock must NOT contain:
- pid: process ID is not authoritative (wrapper PID causes false positives)

Liveness is determined by:
1. Bus events (BUILDER_EXIT after lock_start -> dead)
2. Lock mtime TTL fallback (<15 min -> alive)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = PROJECT_ROOT / "scripts" / "launch_agent_terminals.ps1"
SUPERVISOR_PATH = PROJECT_ROOT / "bus" / "supervisor.py"
LOCK_PATH = PROJECT_ROOT / ".agent" / "runtime" / "builder_lock.txt"


class TestBuilderLockSchema:
    """Tests for the minimal builder lock schema."""

    def test_lock_schema_contains_required_fields(self) -> None:
        """Lock must contain ticket_id and started_at as minimum schema."""
        if not LOCK_PATH.exists():
            pytest.skip("builder_lock.txt does not exist yet")

        content = LOCK_PATH.read_text(encoding="utf-8").strip()
        if not content:
            pytest.skip("builder_lock.txt is empty")

        # Handle BOM if present
        if content.startswith("\ufeff"):
            content = content[1:]

        data = json.loads(content)

        # Required fields
        assert "ticket_id" in data, "Lock must contain ticket_id"
        assert "started_at" in data, "Lock must contain started_at"

        # Validate ticket_id format
        ticket_id = data["ticket_id"]
        assert re.match(r"WP-\d{4}-\d+", ticket_id), (
            f"ticket_id must match WP-YYYY-NNN format, got {ticket_id}"
        )

        # Validate started_at is ISO 8601
        started_at = data["started_at"]
        try:
            datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            pytest.fail(f"started_at must be ISO 8601 format: {exc}")

    def test_lock_schema_does_not_contain_pid(self) -> None:
        """Lock must NOT contain pid field (WP-2026-117).

        This test will fail if pid is reintroduced in the lock.
        """
        if not LOCK_PATH.exists():
            pytest.skip("builder_lock.txt does not exist yet")

        content = LOCK_PATH.read_text(encoding="utf-8").strip()
        if not content:
            pytest.skip("builder_lock.txt is empty")

        # Handle BOM if present
        if content.startswith("\ufeff"):
            content = content[1:]

        data = json.loads(content)

        # PID fields that must NOT be present
        pid_fields = ["pid", "process_id", "processId", "Pid", "PID"]

        for field in pid_fields:
            assert field not in data, (
                f"Lock must not contain '{field}' field (WP-2026-117). "
                f"PID causes false positives in liveness detection."
            )

    def test_launcher_does_not_write_pid(self) -> None:
        """Launcher script must not write pid to builder_lock.txt."""
        content = LAUNCHER_PATH.read_text(encoding="utf-8")

        # The lock state creation should not include pid
        # Look for the builderLockState hashtable definition
        lock_section_start = content.find("$builderLockState = [ordered]@{")
        assert lock_section_start != -1, (
            "Could not find builderLockState definition in launcher"
        )

        # Find the closing brace
        lock_section_end = content.find("}", lock_section_start)
        lock_section = content[lock_section_start:lock_section_end]

        # PID must not appear in the lock state definition
        assert "pid" not in lock_section.lower(), (
            "Launcher must not include pid in builderLockState (WP-2026-117)"
        )

    def test_launcher_comment_explains_no_pid(self) -> None:
        """Launcher should have a comment explaining why pid is excluded."""
        content = LAUNCHER_PATH.read_text(encoding="utf-8")

        # Look for WP-2026-117 reference or explanation
        assert "WP-2026-117" in content or "PID" in content, (
            "Launcher should reference WP-2026-117 or explain PID exclusion"
        )


class TestSupervisorLockHandling:
    """Tests for supervisor handling of the minimal lock schema."""

    def test_supervisor_does_not_depend_on_pid_for_liveness(self) -> None:
        """Supervisor _builder_alive must not use pid as primary authority."""
        content = SUPERVISOR_PATH.read_text(encoding="utf-8")

        # Find the _builder_alive method
        method_start = content.find("def _builder_alive(self)")
        assert method_start != -1, "Could not find _builder_alive method"

        # Find the next method definition or end of class
        next_method = content.find("def ", method_start + 1)
        if next_method == -1:
            next_method = len(content)
        method_content = content[method_start:next_method]

        # The method should NOT call _is_pid_alive or check process by PID
        # It should use bus events (BUILDER_EXIT) and mtime fallback
        assert "_is_pid_alive" not in method_content, (
            "_builder_alive must not use _is_pid_alive (WP-2026-117)"
        )

        # Should use bus-based liveness check
        assert "BUILDER_EXIT" in method_content or "_has_builder_exited_after" in method_content, (
            "_builder_alive should use bus events for liveness"
        )

        # Should use mtime fallback
        assert "st_mtime" in method_content or "mtime" in method_content, (
            "_builder_alive should use mtime as fallback"
        )

    def test_supervisor_has_builder_exit_check(self) -> None:
        """Supervisor must have _has_builder_exited_after method."""
        content = SUPERVISOR_PATH.read_text(encoding="utf-8")

        assert "def _has_builder_exited_after" in content, (
            "Supervisor must have _has_builder_exited_after method for bus-first liveness"
        )


class TestLockStaleDetection:
    """Tests for stale lock detection based on TTL."""

    def test_launcher_has_ttl_comment(self) -> None:
        """Launcher should mention TTL-based stale detection."""
        content = LAUNCHER_PATH.read_text(encoding="utf-8")

        # Should have some reference to TTL or stale detection
        ttl_patterns = ["TTL", "stale", "Stale", "MaxAge", "stale-lock"]
        found = any(pattern in content for pattern in ttl_patterns)

        assert found, (
            "Launcher should reference TTL-based stale lock detection"
        )

    def test_supervisor_uses_started_at_for_ttl(self) -> None:
        """Supervisor must use started_at for TTL-based stale detection."""
        content = SUPERVISOR_PATH.read_text(encoding="utf-8")

        # Should parse started_at for age calculation
        assert "started_at" in content, (
            "Supervisor must use started_at for TTL detection"
        )

        # Should have age calculation logic
        age_patterns = ["age", "TotalMinutes", "TotalSeconds", "UtcNow -"]
        found = any(pattern in content for pattern in age_patterns)

        assert found, (
            "Supervisor must have age calculation for TTL detection"
        )


class TestLockIntegrity:
    """Integration tests for lock integrity."""

    def test_lock_file_encoding(self) -> None:
        """Lock file must be valid UTF-8 JSON."""
        if not LOCK_PATH.exists():
            pytest.skip("builder_lock.txt does not exist yet")

        content = LOCK_PATH.read_text(encoding="utf-8").strip()
        if not content:
            pytest.skip("builder_lock.txt is empty")

        # Handle BOM
        if content.startswith("\ufeff"):
            content = content[1:]

        # Must be valid JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            pytest.fail(f"builder_lock.txt must be valid JSON: {exc}")

        # Must be a dict
        assert isinstance(data, dict), "Lock must be a JSON object"
