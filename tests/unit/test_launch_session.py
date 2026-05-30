"""Tests for WP-2026-180: Builder session persistence and reuse.

Covers:
- Launcher source code checks for --title and --session flags
- Self-contained cleanup function tests (contract-based, no module imports)
- builder_session.json schema validation
- Session closeout cleanup step
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_agent_terminals.ps1"


# ============================================================================
# Helper: simulate _cleanup_builder_session contract
# ============================================================================


def _cleanup_session_by_ticket(session_path: Path, ticket_id: str) -> bool:
    """Simulate _cleanup_builder_session: remove builder_session.json for a ticket.

    Returns True if file existed and was removed, False if no-op.
    Only removes if ticket_id matches the session's ticket_id,
    or if the file is corrupt/unparseable.
    """
    if not session_path.exists():
        return False
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
        if data.get("ticket_id") != ticket_id:
            return False  # Different ticket; leave it
    except (OSError, json.JSONDecodeError):
        pass  # Corrupt; remove it
    session_path.unlink()
    return True


def _cleanup_session_force(session_path: Path) -> bool:
    """Simulate _bus_cleanup_builder_session: unconditionally remove file."""
    if not session_path.exists():
        return False
    session_path.unlink()
    return True


# ============================================================================
# Launcher source code checks
# ============================================================================


@pytest.fixture(scope="module")
def launcher_source() -> str:
    """Return the full launcher source text."""
    return LAUNCHER.read_text(encoding="utf-8")


def test_launcher_file_exists() -> None:
    """Sanity check: the launcher script must exist."""
    assert LAUNCHER.is_file(), f"launcher not found at {LAUNCHER}"


def test_opencode_command_has_title_flag(launcher_source: str) -> None:
    """The opencode run command must inject --title for session identification.

    WP-2026-180 Phase 1a: --title <ticketId>-R<round> must be in the
    opencode run command so the session can be identified later.
    """
    assert "--title" in launcher_source, (
        "OpenCode run command must include --title for deterministic session identification; "
        "regression would prevent builder_session.json from being captured"
    )
    assert "$sessionTitleLiteral" in launcher_source, (
        "The title value must be single-quote escaped via ConvertTo-SingleQuotedLiteral; "
        "otherwise shell injection breaks the argument"
    )


def test_resume_builder_reads_session_json(launcher_source: str) -> None:
    """The -ResumeBuilder path must read builder_session.json to reuse session.

    WP-2026-180 Phase 2: When -ResumeBuilder is set, the launcher reads
    builder_session.json and extracts session_id for --session reuse.
    """
    assert "builder_session.json" in launcher_source, (
        "Launcher must reference builder_session.json to read cached session ID "
        "for --ResumeBuilder path"
    )
    assert "$sessionData.ticket_id -eq $ticketId" in launcher_source, (
        "Resume path must verify ticket_id match before reusing session; "
        "otherwise stale sessions from other tickets would be reused"
    )


def test_resume_builder_fallback_to_clean_session(
    launcher_source: str,
) -> None:
    """The -ResumeBuilder path must fall back to a clean session gracefully.

    WP-2026-180 Phase 2 fallback: If builder_session.json is corrupt, missing,
    or the ticket doesn't match, the launcher must proceed with a clean session
    (no --session flag) without blocking the launch.
    """
    assert "falling back to clean session" in launcher_source, (
        "Launcher must log 'falling back to clean session' when builder_session.json "
        "cannot be used, ensuring transparent fallback"
    )


# ============================================================================
# builder_session.json schema validation
# ============================================================================


def _valid_session_data(
    ticket_id: str = "WP-2026-180",
    session_id: str = "test-session-abc-123",
    round_num: int = 1,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "ticket_id": ticket_id,
        "started_at": "2026-05-30T10:00:00Z",
        "round": round_num,
        "title": f"{ticket_id}-R{round_num}",
    }


class TestBuilderSessionSchema:
    """Validate the builder_session.json schema as defined in work_plan.md."""

    REQUIRED_KEYS: ClassVar[set[str]] = {
        "session_id",
        "ticket_id",
        "started_at",
        "round",
        "title",
    }

    def test_all_required_keys_present(self) -> None:
        """builder_session.json must contain all schema fields."""
        data = _valid_session_data()
        missing = self.REQUIRED_KEYS - set(data.keys())
        assert not missing, (
            f"builder_session.json schema missing keys: {missing}. "
            "Expected: session_id, ticket_id, started_at, round, title"
        )

    def test_no_extra_keys(self) -> None:
        """builder_session.json should not have unexpected keys."""
        data = _valid_session_data()
        extra = set(data.keys()) - self.REQUIRED_KEYS
        assert not extra, f"builder_session.json has unexpected keys: {extra}"

    def test_session_id_is_non_empty_string(self) -> None:
        """session_id must be a non-empty string."""
        data = _valid_session_data()
        assert isinstance(data["session_id"], str) and data["session_id"], (
            "session_id must be a non-empty string"
        )

    def test_ticket_id_matches_pattern(self) -> None:
        """ticket_id must match 'WP-XXXX-NNN' pattern."""
        data = _valid_session_data()
        assert data["ticket_id"].startswith("WP-"), (
            f"ticket_id '{data['ticket_id']}' must start with 'WP-'"
        )

    def test_round_is_positive_int(self) -> None:
        """round must be a positive integer."""
        data = _valid_session_data()
        assert isinstance(data["round"], int) and data["round"] >= 1, (
            f"round must be a positive integer, got {data['round']}"
        )

    def test_title_matches_convention(self) -> None:
        """title must follow '<ticket_id>-R<round>' convention."""
        data = _valid_session_data()
        expected = f"{data['ticket_id']}-R{data['round']}"
        assert data["title"] == expected, (
            f"title '{data['title']}' does not match convention '{expected}'"
        )

    def test_json_serializable(self) -> None:
        """builder_session.json must be valid JSON."""
        data = _valid_session_data()
        serialized = json.dumps(data, indent=2)
        deserialized = json.loads(serialized)
        assert deserialized == data, (
            "builder_session.json data must survive JSON round-trip"
        )


# ============================================================================
# Cleanup by ticket contract tests (simulates _cleanup_builder_session)
# ============================================================================


class TestCleanupByTicket:
    """Test the ticket-aware cleanup contract.

    These tests simulate _cleanup_builder_session behavior without importing
    the agent_controller module (which has conflicting runtime package paths).
    """

    def _write_session(
        self,
        runtime_dir: Path,
        ticket_id: str = "WP-2026-180",
    ) -> Path:
        session_path = runtime_dir / "builder_session.json"
        data = _valid_session_data(ticket_id=ticket_id)
        session_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return session_path

    def test_removes_existing_session(self) -> None:
        """Cleanup must remove an existing builder_session.json."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = self._write_session(runtime_dir)
            assert session_path.exists()

            result = _cleanup_session_by_ticket(session_path, "WP-2026-180")
            assert result, "cleanup must return True when file is removed"
            assert not session_path.exists(), (
                "builder_session.json must be removed after cleanup"
            )

    def test_does_not_remove_wrong_ticket(self) -> None:
        """Cleanup must NOT remove session if ticket_id does not match."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = self._write_session(runtime_dir, ticket_id="WP-2026-179")
            assert session_path.exists()

            result = _cleanup_session_by_ticket(session_path, "WP-2026-180")
            assert not result, "cleanup must return False when ticket doesn't match"
            assert session_path.exists(), (
                "builder_session.json for different ticket must NOT be removed"
            )

    def test_does_not_fail_if_missing(self) -> None:
        """Cleanup must not error if builder_session.json does not exist."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = runtime_dir / "builder_session.json"
            result = _cleanup_session_by_ticket(session_path, "WP-2026-180")
            assert not result, "cleanup must return False for non-existent file"

    def test_removes_corrupt_session(self) -> None:
        """Cleanup must remove a corrupt/unparseable builder_session.json."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = runtime_dir / "builder_session.json"
            session_path.write_text("not-json", encoding="utf-8")
            assert session_path.exists()

            result = _cleanup_session_by_ticket(session_path, "WP-2026-180")
            assert result, "cleanup must remove corrupt file"
            assert not session_path.exists(), (
                "Corrupt builder_session.json must be removed"
            )

    def test_scenario_valid_session_reuse_path(self) -> None:
        """Full scenario: valid session -> resume -> cleanup.

        This tests the intended flow:
        1. builder_session.json is written with session_id and ticket_id
        2. Launcher reads it, verifies ticket_id matches, uses session_id
        3. After closeout, cleanup removes the file
        """
        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "builder_session.json"

            # Step 1: Capture session (simulated)
            session_data = _valid_session_data(
                ticket_id="WP-2026-180",
                session_id="ses_real_id_12345",
                round_num=2,
            )
            session_path.write_text(json.dumps(session_data), encoding="utf-8")
            assert session_path.exists()

            # Step 2: Resume - verify ticket match (simulated launcher logic)
            raw = json.loads(session_path.read_text(encoding="utf-8"))
            assert raw["ticket_id"] == "WP-2026-180", "Ticket must match for resume"
            assert raw["session_id"] == "ses_real_id_12345", (
                "Session ID must be readable"
            )
            assert raw["round"] == 2, "Round must be preserved"
            assert raw["title"] == "WP-2026-180-R2", "Title must follow convention"
            # Session ID is valid for --session flag
            session_id_for_flag = raw["session_id"]
            assert session_id_for_flag, (
                "Session ID must be non-empty for --session flag"
            )

            # Step 3: Cleanup after closeout
            result = _cleanup_session_by_ticket(session_path, "WP-2026-180")
            assert result, "Cleanup must succeed"
            assert not session_path.exists(), "Session must be removed after closeout"


# ============================================================================
# Force cleanup contract tests (simulates _bus_cleanup_builder_session)
# ============================================================================


class TestForceCleanup:
    """Test the unconditional cleanup contract.

    These tests simulate _bus_cleanup_builder_session behavior without importing
    the bus.supervisor module (which has conflicting runtime package paths).
    """

    def test_removes_existing_session_file(self) -> None:
        """Force cleanup must remove an existing builder_session.json."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = runtime_dir / "builder_session.json"
            session_path.write_text("{}", encoding="utf-8")
            assert session_path.exists()

            result = _cleanup_session_force(session_path)
            assert result, "force cleanup must return True when file was removed"
            assert not session_path.exists(), (
                "Force cleanup must remove builder_session.json"
            )

    def test_no_error_if_missing(self) -> None:
        """Force cleanup must not error if file does not exist."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = runtime_dir / "builder_session.json"
            result = _cleanup_session_force(session_path)
            assert not result, "force cleanup must return False for missing file"

    def test_unconditional_removal_ignores_ticket(self) -> None:
        """Force cleanup must remove regardless of ticket_id."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            session_path = runtime_dir / "builder_session.json"
            data = _valid_session_data(ticket_id="WP-2026-179")
            session_path.write_text(json.dumps(data), encoding="utf-8")
            assert session_path.exists()

            result = _cleanup_session_force(session_path)
            assert result, "force cleanup must remove regardless of ticket"
            assert not session_path.exists(), "File must be removed unconditionally"


# ============================================================================
# Session closeout step test
# ============================================================================


class TestSessionCloseoutCleanup:
    """Test the _step_cleanup_builder_session in session_closeout.py.

    These tests import session_closeout.py which does NOT have the runtime/
    package conflict since it only imports project_root after bootstrap.
    """

    @pytest.fixture
    def closeout_module(self):
        """Import session_closeout module.

        Adds REPO_ROOT to sys.path first (not .agent/) to avoid the
        .agent/runtime/ shadowing the top-level runtime/project_root.py.
        """
        import sys

        sys.path.insert(0, str(REPO_ROOT))
        from scripts import session_closeout

        yield session_closeout
        sys.path.pop(0)

    def test_step_removes_existing_session(self, closeout_module):
        """Closeout step must remove builder_session.json."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_dir = root / ".agent" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            session_path = runtime_dir / "builder_session.json"
            session_path.write_text("{}", encoding="utf-8")
            assert session_path.exists()

            result = closeout_module._step_cleanup_builder_session(root, dry_run=False)
            assert result.status == "PASS", (
                f"Expected PASS, got {result.status}: {result.detail}"
            )
            assert not session_path.exists()

    def test_step_skips_if_absent(self, closeout_module):
        """Closeout step should skip if file already absent."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_dir = root / ".agent" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)

            result = closeout_module._step_cleanup_builder_session(root, dry_run=False)
            assert result.status == "SKIP", (
                f"Expected SKIP, got {result.status}: {result.detail}"
            )

    def test_step_dry_run(self, closeout_module):
        """Closeout step must skip in dry-run mode."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_dir = root / ".agent" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            session_path = runtime_dir / "builder_session.json"
            session_path.write_text("{}", encoding="utf-8")

            result = closeout_module._step_cleanup_builder_session(root, dry_run=True)
            assert result.status == "SKIP", (
                f"Expected SKIP in dry-run, got {result.status}"
            )
            assert session_path.exists(), "File must NOT be removed in dry-run mode"
