"""Tests for WT-2026-196: Stable blocker signature and adaptive review detection."""

from __future__ import annotations

from bus.blocker_signature import (
    blocker_lines_from_signature,
    compute_blocker_overlap,
    compute_signature,
    extract_signatures_from_feedback,
    parse_blockers,
)


# =============================================================================
# Fixtures: realistic Manager feedback samples
# =============================================================================

REALISTIC_FEEDBACK_WITH_BLOCKERS = """## SUMMARY
Implementation has several issues that need addressing.

## BLOCKERS
- bus/review_bridge.py:123: Missing error handling for None returns
- bus/state_machine.py:45: Invalid state transition in _derive_state
- scripts/manager_review_bridge.py::_save_state Race condition on file write

## SUGGESTIONS
- Add unit tests for edge cases
- Improve logging

DECISION: CHANGES"""

FEEDBACK_WITH_MARKDOWN_NOISE = """## SUMMARY
Issues found.

## BLOCKERS
- **bus/review_bridge.py:123** *Missing error handling* for `None` returns
- `bus/state_machine.py:45`:: Invalid state transition
- BLOCKER: scripts/manager.py :: Write race condition
- P0: core/logic.py:99 Must handle empty input

## SUGGESTIONS
- Fix formatting

DECISION: CHANGES"""

FEEDBACK_WITH_SUGGESTIONS_ONLY = """## SUMMARY
Minor improvements needed.

## BLOCKERS
(none critical)

## SUGGESTIONS
- SUGGESTION: Consider adding type hints
- NIT: Minor formatting issue in review_bridge.py:200

DECISION: CHANGES"""


# =============================================================================
# Test 1: Signature survives line number drift (TP-02)
# =============================================================================


def test_repeated_blocker_signature_survives_line_number_drift():
    """TP-02: Signatures from equivalent blockers must match despite different line numbers."""
    feedback_v1 = """## BLOCKERS
- bus/review_bridge.py:123: Missing error handling for None returns
DECISION: CHANGES"""
    feedback_v2 = """## BLOCKERS
- bus/review_bridge.py:456: Missing error handling for None returns
DECISION: CHANGES"""

    sigs1 = extract_signatures_from_feedback(feedback_v1)
    sigs2 = extract_signatures_from_feedback(feedback_v2)

    # Line number changed from 123 to 456, but file+summary same -> signature must match
    assert len(sigs1) == 1
    assert len(sigs2) == 1
    assert sigs1 == sigs2, (
        f"Signature must NOT depend on line number. v1={sigs1}, v2={sigs2}"
    )

    # Verify the signature contains file and summary, but NOT line number
    sig = next(iter(sigs1))
    assert "review_bridge.py" in sig
    assert "ERROR HANDLING" in sig.upper() or "None" in sig
    assert ":123" not in sig and ":456" not in sig


# =============================================================================
# Test 2: Signature ignores markdown noise (TP-02)
# =============================================================================


def test_repeated_blocker_signature_ignores_markdown_noise():
    """TP-02: Signatures must be stable despite markdown formatting differences."""
    feedback_plain = """## BLOCKERS
- bus/review_bridge.py: Missing error handling for None returns
DECISION: CHANGES"""
    feedback_fancy = """## BLOCKERS
- **`bus/review_bridge.py`** :: *Missing* error handling for `None` returns
DECISION: CHANGES"""

    sigs_plain = extract_signatures_from_feedback(feedback_plain)
    sigs_fancy = extract_signatures_from_feedback(feedback_fancy)

    assert len(sigs_plain) == 1
    assert len(sigs_fancy) == 1
    assert sigs_plain == sigs_fancy, (
        "Signature must ignore markdown formatting. "
        f"plain={sigs_plain}, fancy={sigs_fancy}"
    )


# =============================================================================
# Test 3: Distinct blockers in same file don't collapse (TP-03)
# =============================================================================


def test_repeated_blocker_signature_does_not_merge_distinct_blockers_same_file():
    """TP-03: Two different blockers in the same file must produce different signatures."""
    feedback = """## BLOCKERS
- bus/review_bridge.py:123: Error handling missing for None
- bus/review_bridge.py:200: Race condition on concurrent writes
DECISION: CHANGES"""

    sigs = extract_signatures_from_feedback(feedback)
    assert len(sigs) == 2, (
        "Two distinct blockers in same file must produce 2 signatures"
    )

    # Verify they are different
    sig_list = sorted(sigs)
    assert sig_list[0] != sig_list[1]


# =============================================================================
# Test 4: Diagnostic mode activates on second consecutive repeated blocker (TP-04)
# =============================================================================


def test_diagnostic_mode_activates_on_second_consecutive_repeated_blocker():
    """TP-04: compute_repeated_blockers returns repeated when same sig appears again."""
    from bus.blocker_signature import compute_signature, parse_blockers

    feedback = """## BLOCKERS
- bus/review_bridge.py: Missing error handling
DECISION: CHANGES"""
    blockers_cycle1 = parse_blockers(feedback)
    sigs_cycle1 = {compute_signature(b) for b in blockers_cycle1}

    # Same blocker in cycle 2
    blockers_cycle2 = parse_blockers(feedback)
    sigs_cycle2 = {compute_signature(b) for b in blockers_cycle2}

    overlap = compute_blocker_overlap(sigs_cycle1, sigs_cycle2)
    assert overlap == 1.0, "Same blocker must produce 100% overlap"

    repeated = list(sigs_cycle1 & sigs_cycle2)
    assert len(repeated) == 1, "One blocker must be repeated"
    assert overlap > 0.5, "Overlap exceeds 50% threshold"


# =============================================================================
# Test 5: Overlap >50% activates diagnostic mode (TP-05)
# =============================================================================


def test_diagnostic_mode_activates_when_overlap_exceeds_50_percent():
    """TP-05: When 2 of 3 blockers overlap (>50%), diagnostic mode should activate."""
    feedback_cycle1 = """## BLOCKERS
- bus/a.py: Blocker A
- bus/b.py: Blocker B
- bus/c.py: Blocker C
DECISION: CHANGES"""

    feedback_cycle2 = """## BLOCKERS
- bus/a.py: Blocker A
- bus/b.py: Blocker B
- bus/d.py: Blocker D
DECISION: CHANGES"""

    sigs1 = extract_signatures_from_feedback(feedback_cycle1)
    sigs2 = extract_signatures_from_feedback(feedback_cycle2)

    # 2 of 3 overlap -> 66% -> diagnostic mode on
    overlap = compute_blocker_overlap(sigs1, sigs2)
    assert len(sigs1) == 3
    assert len(sigs2) == 3
    assert overlap > 0.5, f"Overlap {overlap} must exceed 50%"


# =============================================================================
# Test 6: Distinct blockers don't activate diagnostic mode (TP-05/TP-03)
# =============================================================================


def test_diagnostic_mode_does_not_activate_for_distinct_blockers_same_file():
    """TP-05/TP-03: Completely different blockers must not activate diagnostic mode."""
    feedback_cycle1 = """## BLOCKERS
- bus/a.py: Blocker one
DECISION: CHANGES"""
    feedback_cycle2 = """## BLOCKERS
- bus/b.py: Blocker two entirely different
DECISION: CHANGES"""

    sigs1 = extract_signatures_from_feedback(feedback_cycle1)
    sigs2 = extract_signatures_from_feedback(feedback_cycle2)

    overlap = compute_blocker_overlap(sigs1, sigs2)
    assert overlap == 0.0, "Distinct blockers must have zero overlap"

    repeated = list(sigs1 & sigs2)
    assert len(repeated) == 0, "No repeated blockers must be detected"


# =============================================================================
# Additional unit tests for edge cases
# =============================================================================


def test_parse_blockers_extracts_from_realistic_feedback():
    """Test parse_blockers extracts correct number of blockers."""
    blockers = parse_blockers(REALISTIC_FEEDBACK_WITH_BLOCKERS)
    assert len(blockers) >= 3, "Should extract 3 blockers from realistic feedback"
    assert blockers[0]["file"] is not None
    assert blockers[1]["file"] is not None
    # Check each blocker has summary
    for b in blockers:
        assert b["summary"], "Each blocker must have non-empty summary"


def test_parse_blockers_handles_empty_blockers_section():
    """Test parse_blockers returns empty list when no BLOCKERS section."""
    result = parse_blockers("## SUMMARY\nNothing to see here.\nDECISION: APPROVE")
    assert result == []


def test_parse_blockers_handles_no_blockers():
    """Test parse_blockers returns empty when BLOCKERS section has no entries."""
    feedback = """## SUMMARY
OK.

## BLOCKERS
No blockers.

DECISION: CHANGES"""
    result = parse_blockers(feedback)
    assert result == []


def test_compute_signature_without_file():
    """Test signature computation when no file is present."""
    sig = compute_signature(
        {"summary": "Some general issue", "file": None, "function": None}
    )
    assert sig.startswith("|"), "No-file signatue must start with |"
    assert "GENERAL ISSUE" in sig


def test_compute_signature_with_file_only():
    """Test signature with file but no function."""
    sig = compute_signature(
        {"summary": "Error here", "file": "test.py", "function": None}
    )
    assert sig.startswith("test.py"), "File must be first in signature"
    assert ":::" in sig, "File-only signature must use triple-colon separator"


def test_compute_signature_with_file_and_function():
    """Test signature with file and function."""
    sig = compute_signature(
        {"summary": "Error here", "file": "test.py", "function": "my_func"}
    )
    assert sig.startswith("test.py::my_func"), "File+function must be first"
    assert "ERROR HERE" in sig


def test_blocker_lines_from_signature_file_only():
    """Test blocker_lines_from_signature reconstructs display lines."""
    lines = blocker_lines_from_signature("test.py:::ERROR HERE")
    assert len(lines) == 1
    assert "test.py" in lines[0]
    assert "ERROR HERE" in lines[0]


def test_blocker_lines_from_signature_no_file():
    """Test blocker_lines_from_signature with no-file signature."""
    lines = blocker_lines_from_signature("|GENERAL ISSUE")
    assert len(lines) == 1
    assert "GENERAL ISSUE" in lines[0]


def test_overlap_zero_when_either_set_empty():
    """Test compute_blocker_overlap returns 0 when either set is empty."""
    assert compute_blocker_overlap(set(), {"a"}) == 0.0
    assert compute_blocker_overlap({"a"}, set()) == 0.0
    assert compute_blocker_overlap(set(), set()) == 0.0
