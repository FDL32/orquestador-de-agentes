"""Tests for bus drift detection in --validate."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_controller import _handle_validate  # noqa: E402


def _mock_read_file(path):
    if "execution_log.md" in str(path):
        return "**Estado:** READY_FOR_REVIEW"
    if "work_plan.md" in str(path):
        return "**ID:** WP-2026-063\n**Estado:** APPROVED\ndeliverable_type: code"
    return "**ID:** WP-2026-063"


def _mock_read_file_no_ticket(path):
    if "execution_log.md" in str(path):
        return "**Estado:** READY_FOR_REVIEW"
    if "work_plan.md" in str(path):
        return "**ID:** N/A"
    return "**ID:** N/A"


class TestBusDriftDetection:
    """Test detection of drift between Markdown state and bus events."""

    @patch(
        "scripts.validate_ticket_prose.validate_ticket_prose",
        return_value={"warnings": []},
    )
    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_drift_detected_when_states_differ(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
        mock_prose,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS"}
        mock_bus.latest_event.return_value = mock_event

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch(
        "scripts.validate_ticket_prose.validate_ticket_prose",
        return_value={"warnings": []},
    )
    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_no_drift_when_states_match(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
        mock_prose,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_event = MagicMock()
        mock_event.payload = {"to_state": "READY_FOR_REVIEW"}
        mock_bus.latest_event.return_value = mock_event

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[OK] Todos los archivos de estado son validos.")

    @patch(
        "scripts.validate_ticket_prose.validate_ticket_prose",
        return_value={"warnings": []},
    )
    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_no_bus_event(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
        mock_prose,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        mock_bus.latest_event.return_value = None

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch(
        "scripts.validate_ticket_prose.validate_ticket_prose",
        return_value={"warnings": []},
    )
    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus")
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_no_active_ticket(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_bus,
        mock_deliverable,
        mock_scope,
        mock_invariants,
        mock_prose,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file_no_ticket

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")

    @patch(
        "scripts.validate_ticket_prose.validate_ticket_prose",
        return_value={"warnings": []},
    )
    @patch("agent_controller._check_invariants")
    @patch("agent_controller._check_scope_for_validate")
    @patch("agent_controller._collect_deliverable_type_warnings")
    @patch("agent_controller.event_bus", None)
    @patch("agent_controller.read_file")
    @patch("agent_controller.validate_state_files")
    @patch("builtins.print")
    def test_warning_when_bus_unavailable(
        self,
        mock_print,
        mock_validate,
        mock_read,
        mock_deliverable,
        mock_scope,
        mock_invariants,
        mock_prose,
    ):
        mock_validate.return_value = {}
        mock_scope.return_value = ([], [])
        mock_deliverable.return_value = {}
        mock_invariants.return_value = {"errors": [], "warnings": []}
        mock_read.side_effect = _mock_read_file

        _handle_validate(json_output=False)

        mock_print.assert_any_call("[WARN] 1 advertencia(s) encontradas.")


class TestBusDriftArchiveAware:
    """Test that _check_bus_drift respects the archive early-return barrier."""

    @patch("agent_controller._ticket_events_archived", return_value=True)
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_warning_when_events_archived(self, mock_bus, mock_archived):
        """_check_bus_drift returns [] when the ticket archive file exists."""
        from agent_controller import _check_bus_drift

        plan_content = "**ID:** WP-2026-063\n**Estado:** APPROVED"
        result = _check_bus_drift(plan_content, "READY_FOR_REVIEW")

        assert result == [], f"Expected empty list when archived, got: {result}"
        # closure_invariants.check_bus_drift must NOT be called
        mock_bus.latest_event.assert_not_called()

    @patch("agent_controller._ticket_events_archived", return_value=False)
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_warning_preserved_when_bus_empty_not_archived(
        self, mock_bus, mock_archived
    ):
        """_check_bus_drift returns a non-empty list when bus has no STATE_CHANGED
        and the ticket archive does not exist (regression guard)."""
        from agent_controller import _check_bus_drift

        mock_bus.latest_event.return_value = None

        plan_content = "**ID:** WP-2026-063\n**Estado:** APPROVED"
        result = _check_bus_drift(plan_content, "READY_FOR_REVIEW")

        assert len(result) > 0, (
            "Expected at least one warning when bus is empty and not archived"
        )


class TestTicketLandedByArchivedCommit:
    """WOT-2026-024q: recognize commit-landed evidence for a code-only close.

    When the runtime bus is ABSENT for a ticket but the archived backlog row
    records a commit whose landing is verified by the existing landed-commit
    guard semantics (OK / OK_BY_SUBJECT only), validate must treat the
    bus-dependent closure evidence as satisfied -- WITHOUT fabricating any bus
    event. This mirrors _ticket_events_archived but keys off git landing, not
    the archived bus file.
    """

    _ARCHIVE = (
        "| Media | WOT-2026-038l | titulo | mixed | motor/x | completed | - | "
        "nota | commit:f013a06 |\n"
    )

    def _patch_archive(self, content):
        """Patch get_collab_dir so _archive/backlog_done.md returns `content`."""
        return patch(
            "agent_controller.get_collab_dir",
            return_value=_FakeCollab(content),
        )

    def test_helper_true_when_commit_landed_ok(self):
        """A terminal archived row with a commit that lands as OK -> True."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "f013a06", "verdict": "OK"}
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is True

    def test_helper_true_when_landed_by_subject(self):
        """OK_BY_SUBJECT also counts as landed (CAPA 3)."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {
                        "ticket_id": "WOT-2026-038l",
                        "sha": "f013a06",
                        "verdict": "OK_BY_SUBJECT",
                    }
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is True

    def test_mut_i_pending_is_not_landed(self):
        """MUTATION (i): PENDING_GROUPED_PUSH must NOT count as landed.

        A commit still local (pending grouped push) is not a verified close.
        If the helper treated PENDING as landed, validate would bless an
        unpushed close -- the exact false-green 024q exists to prevent.
        """
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {
                        "ticket_id": "WOT-2026-038l",
                        "sha": "f013a06",
                        "verdict": "PENDING_GROUPED_PUSH",
                    }
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is False

    def test_mut_i_warn_is_not_landed(self):
        """MUTATION (i): WARN (no git object) must NOT count as landed."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "f013a06", "verdict": "WARN"}
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is False

    def test_mut_iii_commit_not_landed_not_verified(self):
        """MUTATION (iii): a cited SHA that ERRORs (lost close) is not verified."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "dead", "verdict": "ERROR"}
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is False

    def test_mut_mixed_ok_plus_pending_not_landed(self):
        """MUTATION (Codex-FS): a multi-SHA row (commit:sha1+sha2) where ONE SHA
        lands OK but a SIBLING is PENDING must NOT count as landed. `any` would
        bless it; `all` (over non-empty results) must reject it -- else a ticket
        with a landed commit next to an unpushed sibling gets a false-green.
        """
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "sha1", "verdict": "OK"},
                    {
                        "ticket_id": "WOT-2026-038l",
                        "sha": "sha2",
                        "verdict": "PENDING_GROUPED_PUSH",
                    },
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is False

    def test_mut_mixed_ok_plus_error_not_landed(self):
        """MUTATION (Codex-FS): OK beside a lost-close ERROR sibling -> not landed."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "sha1", "verdict": "OK"},
                    {"ticket_id": "WOT-2026-038l", "sha": "sha2", "verdict": "ERROR"},
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is False

    def test_helper_true_when_all_shas_landed(self):
        """A multi-SHA row where ALL SHAs land OK -> True (positive control)."""
        from agent_controller import _ticket_landed_by_archived_commit

        with (
            self._patch_archive(self._ARCHIVE),
            patch(
                "scripts.check_backlog_commits_landed.audit",
                return_value=[
                    {"ticket_id": "WOT-2026-038l", "sha": "sha1", "verdict": "OK"},
                    {
                        "ticket_id": "WOT-2026-038l",
                        "sha": "sha2",
                        "verdict": "OK_BY_SUBJECT",
                    },
                ],
            ),
        ):
            assert _ticket_landed_by_archived_commit("WOT-2026-038l") is True

    def test_helper_false_when_ticket_absent_from_archive(self):
        """A ticket with no archived row (no commit cell) -> False, no crash."""
        from agent_controller import _ticket_landed_by_archived_commit

        with self._patch_archive("| header | only |\n"):
            assert _ticket_landed_by_archived_commit("WOT-2026-999z") is False


class TestBusDriftCommitLandedAware:
    """WOT-2026-024q: _check_bus_drift honors the commit-landed fallback,
    but ONLY when the bus is absent for the ticket (mutation ii guard)."""

    @patch("agent_controller._ticket_landed_by_archived_commit", return_value=True)
    @patch("agent_controller._ticket_events_archived", return_value=False)
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_no_warning_when_bus_absent_and_commit_landed(
        self, mock_bus, mock_archived, mock_landed
    ):
        """Bus has NO events for the ticket + commit landed -> no drift warning."""
        from agent_controller import _check_bus_drift

        # bus absent for this ticket
        mock_bus.read_events.return_value = []
        mock_bus.latest_event.return_value = None

        plan_content = "**ID:** WOT-2026-038l\n**Estado:** COMPLETED"
        result = _check_bus_drift(plan_content, "COMPLETED")

        assert result == [], (
            f"Expected no drift when bus absent and commit landed, got: {result}"
        )

    @patch("agent_controller._ticket_landed_by_archived_commit", return_value=True)
    @patch("agent_controller._ticket_events_archived", return_value=False)
    @patch("agent_controller.BUS_AVAILABLE", True)
    @patch("agent_controller.event_bus")
    def test_mut_ii_bus_present_missing_event_stays_error(
        self, mock_bus, mock_archived, mock_landed
    ):
        """MUTATION (ii): bus HAS events for the ticket but the required
        STATE_CHANGED is missing -> the commit-landed fallback must NOT apply;
        drift is still reported (fail-closed preserved)."""
        from agent_controller import _check_bus_drift

        # bus PRESENT for this ticket (has some event) ...
        mock_bus.read_events.return_value = [MagicMock()]
        # ... but STATE_CHANGED is missing / mismatched
        mock_event = MagicMock()
        mock_event.payload = {"to_state": "IN_PROGRESS"}
        mock_bus.latest_event.return_value = mock_event

        plan_content = "**ID:** WOT-2026-038l\n**Estado:** COMPLETED"
        result = _check_bus_drift(plan_content, "COMPLETED")

        assert len(result) > 0, (
            "bus-present + missing/mismatched STATE_CHANGED must still drift "
            "(commit-landed fallback must not suppress it)"
        )


class _FakeCollab:
    """Minimal stand-in for get_collab_dir(): `/ '_archive' / 'backlog_done.md'`
    resolves to a temp-less object whose read_text returns the injected content."""

    def __init__(self, content):
        self._content = content

    def __truediv__(self, _other):
        return self

    def read_text(self, *args, **kwargs):
        return self._content

    def exists(self):
        return True
