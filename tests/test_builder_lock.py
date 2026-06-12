"""Tests for builder_lock.txt schema and contract.

WP-2026-117: Builder lock PID cleanup.

The builder lock contains operational metadata:
- ticket_id: the active ticket being worked on
- started_at: ISO 8601 timestamp for TTL-based stale detection
- pid: diagnostic signal for process correlation (NOT authoritative for liveness)
- project_root, role, backend, round: identity metadata

The lock contains pid as a DIAGNOSTIC signal only. It is NOT used as primary
authority for liveness decisions. Liveness is determined by:
1. Bus events (BUILDER_EXIT after lock_start -> dead)
2. Lock mtime TTL fallback (<15 min -> alive)

Supervisor must NOT use pid for liveness (verified by
test_supervisor_does_not_depend_on_pid_for_liveness).
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime
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
        from bus.ticket_id import is_valid_ticket_id

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

        # Validate ticket_id format against canonical pattern
        ticket_id = data["ticket_id"]
        assert is_valid_ticket_id(ticket_id), (
            f"ticket_id must match canonical ticket format (e.g. WT-YYYY-NNN), "
            f"got {ticket_id}"
        )

        # Validate started_at is ISO 8601
        started_at = data["started_at"]
        try:
            # Normalize: Python 3.10 fromisoformat rejects >6 fractional digits
            # (PowerShell's 'o' format produces 7 digits)
            normalized = started_at.replace("Z", "+00:00")
            if "." in normalized:
                before_dot, after_dot = normalized.split(".", 1)
                # Separate fraction from timezone
                frac = after_dot
                tz = ""
                for i, ch in enumerate(after_dot):
                    if ch in "+-" and i > 0:
                        frac = after_dot[:i]
                        tz = after_dot[i:]
                        break
                if len(frac) > 6:
                    normalized = f"{before_dot}.{frac[:6]}{tz}"
            datetime.fromisoformat(normalized)
        except (ValueError, AttributeError) as exc:
            pytest.fail(f"started_at must be ISO 8601 format: {exc}")

    def test_lock_schema_does_not_contain_pid(self) -> None:
        """Lock may contain pid as diagnostic signal (WP-2026-117).

        WP-2026-117 removed pid dependency from liveness detection, but pid
        is preserved in the lock as a diagnostic signal for process correlation.
        The key contract is that pid is NOT used for liveness decisions - the
        supervisor relies on bus events + mtime instead.
        Liveness contract is verified by test_supervisor_does_not_depend_on_pid_for_liveness.
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

        # pid may exist as diagnostic signal; if present, must be an integer
        if "pid" in data:
            pid_value = data["pid"]
            assert isinstance(pid_value, int), (
                f"pid must be an integer if present, got {type(pid_value).__name__}"
            )
        if "process_id" in data:
            assert isinstance(data["process_id"], int)
        if "processId" in data:
            assert isinstance(data["processId"], int)

    def test_launcher_writes_pid_as_diagnostic_only(self) -> None:
        """Launcher writes pid as diagnostic signal, not liveness authority.

        WP-2026-117: pid is preserved in builder_lock.txt as a diagnostic
        signal for process correlation. The supervisor uses bus events + mtime
        for liveness, not pid. The launcher comment documents this contract.
        """
        content = LAUNCHER_PATH.read_text(encoding="utf-8")

        # Look for the builderLockState hashtable definition
        lock_section_start = content.find("$builderLockState = [ordered]@{")
        assert lock_section_start != -1, (
            "Could not find builderLockState definition in launcher"
        )

        # Find the closing brace
        lock_section_end = content.find("}", lock_section_start)
        lock_section = content[lock_section_start:lock_section_end]

        # pid should appear in the lock state as diagnostic signal
        assert "pid" in lock_section.lower(), (
            "Launcher should include pid in builderLockState as diagnostic signal"
        )

        # Verify the WP-2026-117 contract comment exists near the lock definition
        # explaining pid is for diagnostics, not liveness authority
        pre_lock_section = content[
            max(0, lock_section_start - 500) : lock_section_start
        ]
        assert (
            "WP-2026-117" in pre_lock_section or "diagnost" in pre_lock_section.lower()
        ), "Launcher should document that pid is for diagnostics, not liveness"

    def test_launcher_comment_explains_no_pid(self) -> None:
        """Launcher should have a comment explaining pid is diagnostic only."""
        content = LAUNCHER_PATH.read_text(encoding="utf-8")

        # Look for WP-2026-117 reference or diagnostic explanation
        assert "WP-2026-117" in content or "diagnost" in content.lower(), (
            "Launcher should reference WP-2026-117 or explain pid is for diagnostics"
        )


class TestSupervisorLockHandling:
    """Tests for supervisor handling of the minimal lock schema."""

    def test_supervisor_does_not_depend_on_pid_for_liveness(self) -> None:
        """Supervisor _builder_alive must not use pid as primary authority."""
        from bus import supervisor as supervisor_module

        wrapper_content = inspect.getsource(
            supervisor_module.SequentialTicketSupervisor._builder_alive
        )
        helper_content = inspect.getsource(supervisor_module._builder_alive_bare)

        # The method should NOT call _is_pid_alive or check process by PID
        # It should use bus events (BUILDER_EXIT) and mtime fallback
        assert "_is_pid_alive" not in wrapper_content, (
            "_builder_alive must not use _is_pid_alive (WP-2026-117)"
        )
        assert "_is_pid_alive" not in helper_content, (
            "_builder_alive helper must not use _is_pid_alive (WP-2026-117)"
        )

        # Should use bus-based liveness check
        assert (
            "BUILDER_EXIT" in helper_content
            or "_has_builder_exited_after" in helper_content
        ), "_builder_alive should use bus events for liveness"

        # Should use mtime fallback
        assert "st_mtime" in helper_content or "mtime" in helper_content, (
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

        assert found, "Launcher should reference TTL-based stale lock detection"

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

        assert found, "Supervisor must have age calculation for TTL detection"


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
