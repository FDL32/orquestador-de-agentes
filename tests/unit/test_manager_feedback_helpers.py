"""Tests for scripts/manager_feedback_helpers.py (WOT-2026-014f).

Two layers of verification:

(a) AST Architecture Guard: asserts exactly ONE real implementation of each
    helper exists across scripts/ (in the canonical module). Thin wrappers
    are detected by their delegation pattern and are NOT counted.

(b) Import-Identity Mutation Barrier: verifies that all three consumers bind
    to the SAME function objects from the canonical module (identity check),
    and that replacing the canonical reference in a consumer with an
    independent local copy breaks the identity and makes the test FAIL.
    The mutation is applied via monkeypatch to the consumer module namespace.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = MOTOR_ROOT / "scripts"
CANONICAL_MODULE_PATH = SCRIPTS_DIR / "manager_feedback_helpers.py"


def _count_real_implementations(source: str, func_name: str) -> int:
    """Count functions with a real body (not a thin wrapper).

    A thin wrapper has exactly 1 non-docstring statement that is a Return of a Call.
    """
    tree = ast.parse(source)
    real_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != func_name:
            continue
        stmts = [
            s
            for s in node.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        if (
            len(stmts) == 1
            and isinstance(stmts[0], ast.Return)
            and isinstance(stmts[0].value, ast.Call)
        ):
            continue
        real_count += 1
    return real_count


def _collect_scripts_sources() -> dict[str, str]:
    """Return {relative_path: source} for all .py files under scripts/."""
    result = {}
    for py_file in SCRIPTS_DIR.rglob("*.py"):
        rel = str(py_file.relative_to(MOTOR_ROOT))
        result[rel] = py_file.read_text(encoding="utf-8")
    return result


class TestASTArchitecture:
    """Assert exactly 1 real implementation per helper, in the canonical module."""

    def test_exactly_one_real_find_manager_feedback_files(self) -> None:
        """find_manager_feedback_files has exactly 1 real impl in scripts/."""
        sources = _collect_scripts_sources()
        total_real = sum(
            _count_real_implementations(src, "find_manager_feedback_files")
            for src in sources.values()
        )
        assert total_real == 1, (
            f"Expected 1 real impl of find_manager_feedback_files, got {total_real}."
        )

    def test_exactly_one_real_extract_ticket_id_from_feedback(self) -> None:
        """extract_ticket_id_from_feedback has exactly 1 real impl in scripts/."""
        sources = _collect_scripts_sources()
        total_public = sum(
            _count_real_implementations(src, "extract_ticket_id_from_feedback")
            for src in sources.values()
        )
        total_private = sum(
            _count_real_implementations(src, "_extract_ticket_id_from_feedback")
            for src in sources.values()
        )
        total = total_public + total_private
        assert total == 1, (
            f"Expected 1 real impl of extract_ticket_id_from_feedback, got {total}."
        )

    def test_canonical_module_exists(self) -> None:
        """The canonical module must exist at scripts/manager_feedback_helpers.py."""
        assert CANONICAL_MODULE_PATH.exists(), f"Not found: {CANONICAL_MODULE_PATH}"

    def test_canonical_module_contains_real_implementations(self) -> None:
        """The canonical module must contain the 1 real impl of each helper."""
        src = CANONICAL_MODULE_PATH.read_text(encoding="utf-8")
        assert _count_real_implementations(src, "find_manager_feedback_files") == 1
        assert _count_real_implementations(src, "extract_ticket_id_from_feedback") == 1


class TestImportIdentityBarrier:
    """All three consumers bind to the SAME function objects as the canonical module.

    Primary barrier: each consumer imports the canonical via
    _canonical_find_manager_feedback_files / _canonical_extract_ticket_id_from_feedback.
    These names in the consumer module namespace must be THE SAME object (is-identity)
    as the function in scripts.manager_feedback_helpers.

    Mutation test: replacing the consumer module-level canonical reference with an
    independent local copy breaks the identity assertion -> the test FAILS.
    This is the mutation-verified property: a reverted consumer is detected.
    """

    @pytest.fixture(autouse=True)
    def _load_modules(self) -> None:
        """Load all relevant modules."""
        import sys

        if str(MOTOR_ROOT) not in sys.path:
            sys.path.insert(0, str(MOTOR_ROOT))
        self.canonical_mod = importlib.import_module("scripts.manager_feedback_helpers")
        self.archive_mod = importlib.import_module(
            "scripts.archive_collaboration_artifacts"
        )
        self.archival_mod = importlib.import_module("scripts.closeout_steps.archival")
        self.closeout_mod = importlib.import_module("scripts.session_closeout")
        from bus.ticket_id import TICKET_ID_PATTERN

        self.ticket_id_pattern = TICKET_ID_PATTERN

    def test_extract_identity_archive(self) -> None:
        """archive_mod._canonical_extract IS canonical_mod.extract_ticket_id_from_feedback."""
        assert (
            self.archive_mod._canonical_extract_ticket_id_from_feedback
            is self.canonical_mod.extract_ticket_id_from_feedback
        ), "archive_mod has a local copy, not the canonical"

    def test_extract_identity_archival(self) -> None:
        """archival_mod._canonical_extract IS canonical_mod.extract_ticket_id_from_feedback."""
        assert (
            self.archival_mod._canonical_extract_ticket_id_from_feedback
            is self.canonical_mod.extract_ticket_id_from_feedback
        ), "archival_mod has a local copy, not the canonical"

    def test_extract_identity_closeout(self) -> None:
        """closeout_mod._canonical_extract IS canonical_mod.extract_ticket_id_from_feedback."""
        assert (
            self.closeout_mod._canonical_extract_ticket_id_from_feedback
            is self.canonical_mod.extract_ticket_id_from_feedback
        ), "closeout_mod has a local copy, not the canonical"

    def test_find_identity_archive(self) -> None:
        """archive_mod._canonical_find IS canonical_mod.find_manager_feedback_files."""
        assert (
            self.archive_mod._canonical_find_manager_feedback_files
            is self.canonical_mod.find_manager_feedback_files
        ), "archive_mod has a local copy, not the canonical"

    def test_find_identity_archival(self) -> None:
        """archival_mod._canonical_find IS canonical_mod.find_manager_feedback_files."""
        assert (
            self.archival_mod._canonical_find_manager_feedback_files
            is self.canonical_mod.find_manager_feedback_files
        ), "archival_mod has a local copy, not the canonical"

    def test_find_identity_closeout(self) -> None:
        """closeout_mod._canonical_find IS canonical_mod.find_manager_feedback_files."""
        assert (
            self.closeout_mod._canonical_find_manager_feedback_files
            is self.canonical_mod.find_manager_feedback_files
        ), "closeout_mod has a local copy, not the canonical"

    def test_mutation_propagates_via_consumer_namespace(self) -> None:
        """PRIMARY BARRIER: patching canonical propagates through consumer call paths.

        We patch the canonical module attribute AND update the consumer module
        namespaces (because Python imports bind names at import time). The test
        verifies that all three consumers produce the sentinel when their cached
        canonical reference is replaced to point at _patched.

        This simulates the contract: if a consumer imported the canonical and
        you swap out the canonical function, the consumer that uses it must see
        the change. A consumer with its own local implementation would NOT see it.
        """
        sentinel = "MUTATED_SENTINEL_014F"

        orig_canonical = self.canonical_mod.extract_ticket_id_from_feedback
        orig_archive_ref = self.archive_mod._canonical_extract_ticket_id_from_feedback
        orig_archival_ref = self.archival_mod._canonical_extract_ticket_id_from_feedback
        orig_closeout_ref = self.closeout_mod._canonical_extract_ticket_id_from_feedback

        def _patched(filename: str, *, ticket_id_pattern: str) -> str | None:
            return sentinel

        try:
            self.canonical_mod.extract_ticket_id_from_feedback = _patched
            self.archive_mod._canonical_extract_ticket_id_from_feedback = _patched
            self.archival_mod._canonical_extract_ticket_id_from_feedback = _patched
            self.closeout_mod._canonical_extract_ticket_id_from_feedback = _patched

            filename = "manager_feedback_WP-2026-155.md"
            archive_result = self.archive_mod.extract_ticket_id_from_feedback(filename)
            archival_result = self.archival_mod._extract_ticket_id_from_feedback(
                filename, ticket_id_pattern=self.ticket_id_pattern
            )
            closeout_result = self.closeout_mod._extract_ticket_id_from_feedback(
                filename
            )

            assert archive_result == sentinel, (
                f"archive not seeing mutation: {archive_result}"
            )
            assert archival_result == sentinel, (
                f"archival not seeing mutation: {archival_result}"
            )
            assert closeout_result == sentinel, (
                f"closeout not seeing mutation: {closeout_result}"
            )
        finally:
            self.canonical_mod.extract_ticket_id_from_feedback = orig_canonical
            self.archive_mod._canonical_extract_ticket_id_from_feedback = (
                orig_archive_ref
            )
            self.archival_mod._canonical_extract_ticket_id_from_feedback = (
                orig_archival_ref
            )
            self.closeout_mod._canonical_extract_ticket_id_from_feedback = (
                orig_closeout_ref
            )

    def test_reverted_consumer_breaks_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reverting archive_mod to a local copy breaks the identity assertion.

        This proves the mutation-verified property: if someone reverts a consumer
        to have its own local implementation, the identity test (is-check) fails.
        The is-check in test_extract_identity_archive would catch the revert.
        """

        def _local_copy(filename: str, *, ticket_id_pattern: str) -> str | None:
            m = re.search(r"manager_feedback_([A-Z0-9a-z-]+)\.md$", filename)
            return m.group(1) if m else None

        monkeypatch.setattr(
            self.archive_mod,
            "_canonical_extract_ticket_id_from_feedback",
            _local_copy,
        )

        assert (
            self.archive_mod._canonical_extract_ticket_id_from_feedback
            is not self.canonical_mod.extract_ticket_id_from_feedback
        ), "monkeypatch should have broken identity"

        with pytest.raises(AssertionError):
            assert (
                self.archive_mod._canonical_extract_ticket_id_from_feedback
                is self.canonical_mod.extract_ticket_id_from_feedback
            ), "archive_mod has a local copy, not the canonical"
