import re

from scripts.flight.thread_id import THREAD_ID_PATTERN, THREAD_ID_TOKEN_PATTERN


def test_thread_id_patterns_accept_launch_and_legacy_forms() -> None:
    """Before: receive the strict and extraction thread-id patterns.

    During: match the new launch form and the historical lowercase form.

    After: strict validation and text extraction accept their documented forms.
    """
    launch = "mcp:launch:" + "a" * 64
    legacy = "mcp:" + "a1b2-c3"

    assert re.fullmatch(THREAD_ID_PATTERN, launch)
    assert re.fullmatch(THREAD_ID_PATTERN, legacy)
    assert re.fullmatch(THREAD_ID_TOKEN_PATTERN, launch)
    assert re.fullmatch(THREAD_ID_TOKEN_PATTERN, legacy)


def test_thread_id_strict_pattern_rejects_invalid_forms() -> None:
    """Before: receive malformed launch and prefixed identifiers.

    During: apply the strict validation pattern with full-match semantics.

    After: every malformed value is rejected, including uppercase legacy ids.
    """
    invalid = (
        "mcp:launch:" + "a" * 63,
        "mcp:launch:" + "A" * 64,
        "mcp:launch:" + "a" * 63 + "g",
        "launch:" + "a" * 64,
        "mcp:" + "ABCDEF12",
    )

    assert all(re.fullmatch(THREAD_ID_PATTERN, value) is None for value in invalid)
