"""Tests for closeout_lessons.md CL-03 content integrity.

Tests cover:
- CL-03 allows automatic offline rotation (managed by the motor).
- CL-03 prohibits manual pruning of review_queue.md.
"""

from __future__ import annotations

from pathlib import Path


# Path constants
CLOSEOUT_LESSONS_REL = Path(".agent") / "runtime" / "memory" / "closeout_lessons.md"
CL03_MARKER = "### CL-03"
SECTION_SEP = "---"


def _find_cl03_section(lines: list[str]) -> list[str]:
    """Extract the CL-03 section lines from closeout_lessons content.

    Before: lines is a list of strings from closeout_lessons.md.
    During: Searches for the '### CL-03' header, then collects lines
            until the next section header (###) or section separator (---).
    After: Returns the CL-03 section lines (excluding the header).
    """
    cl03_lines: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### CL-03"):
            found = True
            continue
        if found:
            if stripped.startswith("### ") or stripped == SECTION_SEP:
                break
            cl03_lines.append(line)
    return cl03_lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_closeout_lessons() -> list[str]:
    """Read closeout_lessons.md relative to this test location.

    The file lives at <project_root>/.agent/runtime/memory/closeout_lessons.md.
    We resolve from the tests/ directory up to the project root.
    """
    # Resolve from this file's location: tests/unit/ -> project root
    here = Path(__file__).resolve().parent.parent.parent
    lessons_path = here / CLOSEOUT_LESSONS_REL
    if not lessons_path.exists():
        # Fallback to motor repo path relative to project root
        lessons_path = Path.cwd() / CLOSEOUT_LESSONS_REL
    if not lessons_path.exists():
        # Last resort: check if it is at the motor repo's .agent/
        motor_root = Path(__file__).resolve().parent.parent.parent
        lessons_path = (
            motor_root / ".agent" / "runtime" / "memory" / "closeout_lessons.md"
        )

    assert lessons_path.exists(), f"closeout_lessons.md not found at {lessons_path}"
    return lessons_path.read_text(encoding="utf-8").splitlines()


class TestCL03Content:
    """CL-03 must allow offline rotation and prohibit manual pruning."""

    def test_cl03_allows_offline_rotation(self) -> None:
        """CL-03 must permit automatic offline rotation by the motor."""
        lines = _read_closeout_lessons()
        cl03 = _find_cl03_section(lines)
        assert cl03, "CL-03 section not found in closeout_lessons.md"

        full_text = " ".join(cl03).lower()

        # Must mention automatic/offline rotation
        assert "rotacion" in full_text, "CL-03 must mention rotation (rotacion)"
        assert "automatica" in full_text or "automatic" in full_text, (
            "CL-03 must mention automatic rotation"
        )
        assert "offline" in full_text, "CL-03 must mention offline rotation"

        # Must reference the motor-managed mechanism: session_closeout.py or --session-close
        assert "session_closeout.py" in full_text or "--session-close" in full_text, (
            "CL-03 must reference the motor-managed rotation mechanism"
        )

    def test_cl03_prohibits_manual_pruning(self) -> None:
        """CL-03 must prohibit manual editing/pruning of review_queue.md."""
        lines = _read_closeout_lessons()
        cl03 = _find_cl03_section(lines)
        assert cl03, "CL-03 section not found in closeout_lessons.md"

        full_text = " ".join(cl03).lower()

        # Must prohibit manual editing
        assert "no editar" in full_text or "no edit" in full_text, (
            "CL-03 must prohibit manual editing (no editar)"
        )

        # Must terminate manual pruning
        assert "terminantemente prohibido" in full_text or "prohibido" in full_text, (
            "CL-03 must explicitly prohibit manual pruning"
        )

        # Must reference manual pruning as forbidden
        assert "podado manual" in full_text or "manual" in full_text, (
            "CL-03 must reference manual action as forbidden"
        )

    def test_cl03_preserves_header_active_and_recent(self) -> None:
        """CL-03 must specify that rotation preserves header, active ticket and 10 recent entries."""
        lines = _read_closeout_lessons()
        cl03 = _find_cl03_section(lines)
        assert cl03, "CL-03 section not found in closeout_lessons.md"

        full_text = " ".join(cl03).lower()

        # Must mention preservation of header
        assert "cabecera" in full_text or "header" in full_text, (
            "CL-03 must mention header preservation"
        )

        # Must mention active ticket preservation
        assert "ticket activo" in full_text or "active ticket" in full_text, (
            "CL-03 must mention active ticket preservation"
        )

        # Must mention 10 recent entries
        assert "10" in full_text, "CL-03 must mention the 10 recent entries limit"
        assert "entradas" in full_text or "entries" in full_text, (
            "CL-03 must mention entries"
        )

    def test_cl03_does_not_promise_unimplemented_behavior(self) -> None:
        """CL-03 must not promise behavior that the code does not implement.

        Specifically, it should not suggest that review_queue.md is managed
        automatically outside the session-close flow.
        """
        lines = _read_closeout_lessons()
        cl03 = _find_cl03_section(lines)
        assert cl03, "CL-03 section not found in closeout_lessons.md"

        full_text = " ".join(cl03).lower()

        # Should reference session_closeout.py as the manager
        assert "session_closeout.py" in full_text, (
            "CL-03 must reference session_closeout.py as the rotation manager"
        )

        # Should reference --session-close as the trigger
        assert "--session-close" in full_text, (
            "CL-03 must reference --session-close as the rotation trigger"
        )

        # Should NOT claim that review_queue is auto-managed by the bridge
        assert "auto-gestion" not in full_text, (
            "CL-03 must not promise auto-management that the code does not implement"
        )


class TestCL03Reference:
    """CL-03 must reference WT-2026-190 as the implementing ticket."""

    def test_cl03_references_wt_2026_190(self) -> None:
        """CL-03 must reference WT-2026-190 as the source."""
        lines = _read_closeout_lessons()
        cl03 = _find_cl03_section(lines)
        assert cl03, "CL-03 section not found in closeout_lessons.md"

        full_text = " ".join(cl03)
        assert "WT-2026-190" in full_text, (
            "CL-03 must reference WT-2026-190 as the implementing ticket"
        )


class TestCL03Formatting:
    """CL-03 must use the standard closeout_lessons formatting."""

    def test_cl03_is_under_delivery_hygiene_section(self) -> None:
        """CL-03 must be under the delivery-hygiene section header."""
        lines = _read_closeout_lessons()

        # Find delivery-hygiene header index
        hygiene_idx = -1
        cl03_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "## delivery-hygiene":
                hygiene_idx = i
            if stripped.startswith("### CL-03"):
                cl03_idx = i

        assert hygiene_idx >= 0, "## delivery-hygiene section header not found"
        assert cl03_idx >= 0, "CL-03 section header not found"
        assert cl03_idx > hygiene_idx, (
            "CL-03 must be under the delivery-hygiene section"
        )
