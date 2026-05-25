"""Tests for security logging in guard_paths.py."""

import sys
from pathlib import Path


# Add .agent to path for imports
agent_dir = Path(__file__).parent.parent / ".agent"
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

import hooks.guard_paths as guard_mod  # noqa: E402


# Test log file inside repository's .agent folder (writable)
TEST_LOG = Path(".agent/test_logs/security_test.log")


def _ensure_test_log_dir():
    TEST_LOG.parent.mkdir(parents=True, exist_ok=True)


def _cleanup_log():
    if TEST_LOG.exists():
        TEST_LOG.unlink()


class TestSecurityLogging:
    def setup_class(self):
        """Ensure test log directory exists before all tests."""
        _ensure_test_log_dir()

    def teardown_class(self):
        """Remove test log after all tests."""
        _cleanup_log()

    def test_log_security_event_creates_file(self):
        """_log_security_event creates log file if it doesn't exist."""
        guard_mod.SECURITY_LOG_PATH = TEST_LOG
        _cleanup_log()
        try:
            guard_mod._log_security_event("TEST_EVENT", "/test/path", "test reason")
            assert TEST_LOG.exists(), f"Log file {TEST_LOG} was not created"
            content = TEST_LOG.read_text(encoding="utf-8")
            assert "TEST_EVENT" in content
            assert "/test/path" in content
            assert "test reason" in content
        finally:
            _cleanup_log()

    def test_log_security_event_appends_to_existing(self):
        """_log_security_event appends to existing log file."""
        guard_mod.SECURITY_LOG_PATH = TEST_LOG
        _cleanup_log()
        try:
            TEST_LOG.parent.mkdir(parents=True, exist_ok=True)
            TEST_LOG.write_text("Existing entry\n", encoding="utf-8")
            guard_mod._log_security_event("NEW_EVENT", "/new/path", "new reason")
            content = TEST_LOG.read_text(encoding="utf-8")
            assert "Existing entry" in content
            assert "NEW_EVENT" in content
            assert "/new/path" in content
        finally:
            _cleanup_log()

    def test_log_security_event_handles_errors_gracefully(self):
        """_log_security_event handles I/O errors without crashing."""
        # Point to a directory to trigger an error when opening as file
        guard_mod.SECURITY_LOG_PATH = TEST_LOG.parent  # directory, not file
        try:
            guard_mod._log_security_event("TEST", "/path", "reason")
            # If we reach here, no exception was raised â€” success
        except Exception as e:
            raise AssertionError(f"_log_security_event raised {e!r}") from e
        finally:
            _cleanup_log()
