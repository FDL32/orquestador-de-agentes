"""Focal tests for the ticket-nomenclature gate — WOT-2026-010b.

The gate (scripts/check_ticket_nomenclature.py, created in WOT-2026-010a) was
shipped without focal tests. These tests pin its behaviour as a verified
barrier after the WOT-2026-010b refactor that centralized the legacy literal
into a single exempted constant.

Barrier contract: a live generator using a legacy prefix MUST classify as
"generator"; commit-history comments MUST classify as "history"; explicitly
tagged legacy examples MUST classify as "legacy-tagged".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_GATE_PATH = _MOTOR_ROOT / "scripts" / "check_ticket_nomenclature.py"

_spec = importlib.util.spec_from_file_location("check_ticket_nomenclature", _GATE_PATH)
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


class TestGeneratorDetection:
    """Live generators with a legacy prefix must classify as 'generator'."""

    def test_ticket_flag_generator(self):
        # The canonical regression case: a command example teaching legacy.
        assert (
            _gate.classify_line("python x.py --ticket WP-2026-123a", False)
            == "generator"
        )

    def test_ticket_id_flag_generator(self):
        assert _gate.classify_line("  --ticket-id WT-2026-001", False) == "generator"

    def test_plan_id_generator(self):
        assert _gate.classify_line("- **Plan ID:** WP-XXX", False) == "generator"

    def test_placeholder_generator(self):
        assert _gate.classify_line("ID format: WP-YYYY-NNN", False) == "generator"

    def test_source_ticket_generator(self):
        assert (
            _gate.classify_line('  "source_ticket": "WP-2026-132",', False)
            == "generator"
        )


class TestHistoryDetection:
    """Commit-history comments are legacy-compat implicit, not generators."""

    def test_comment_history(self):
        assert (
            _gate.classify_line("# WP-2026-122: centralized path resolution", False)
            == "history"
        )

    def test_compound_history(self):
        assert (
            _gate.classify_line("# WP-2026-122 / WP-2026-155: path resolution", False)
            == "history"
        )

    def test_prose_reference_is_history(self):
        # A bare historical mention in prose with no generator signal.
        assert (
            _gate.classify_line(
                "la causa se corrigio en WP-2026-120 hace tiempo", False
            )
            == "history"
        )


class TestLegacyTagged:
    """Explicitly tagged legacy examples are permitted."""

    def test_inline_tag(self):
        line = "source_ticket: WP-2026-132  # legacy-compat: retro example"
        assert _gate.classify_line(line, False) == "legacy-tagged"

    def test_region_tag(self):
        # region_legacy=True simulates being inside a tagged example block.
        assert (
            _gate.classify_line('"source_ticket": "WP-2026-132"', True)
            == "legacy-tagged"
        )


class TestNoFalsePositive:
    """Lines without any legacy hit return None."""

    def test_canonical_wot_is_clean(self):
        assert _gate.classify_line("python x.py --ticket WOT-2026-010b", False) is None

    def test_plain_line(self):
        assert _gate.classify_line("just some prose with no ticket id", False) is None


class TestSingleExemptedLiteral:
    """WOT-2026-010b: the forbidden literal lives exactly once, exempted."""

    def test_literal_centralized(self):
        text = _GATE_PATH.read_text(encoding="utf-8")
        # Build the forbidden literal by composition so this test file does not
        # itself contain it (would trip test_no_inline_ticket_regex).
        literal = "(?:" + "WP|WT" + ")-"
        offending = [
            ln
            for ln in text.splitlines()
            if literal in ln and "ticket-id-exemption" not in ln
        ]
        assert offending == [], (
            f"legacy literal must be centralized in one exempted constant; "
            f"found uncentralized: {offending}"
        )

    def test_gate_runs_green_on_repo(self):
        # End-to-end: the gate over the real repo classifies cleanly (no
        # unclassified generator). This is the same invariant 010a closed.
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, str(_GATE_PATH)],
            cwd=_MOTOR_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
