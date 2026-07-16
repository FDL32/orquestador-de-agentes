"""Contract test: canonical prompts carry a homogeneous, greppable summary header.

WOT-2026-022o. FORMAT SPEC (canonical, defined HERE -- this docstring is the
single localizable home of the format, per the contract):

    Each allowlisted prompt MUST contain, within its first HEADER_SCAN_LINES
    lines, a homogeneous greppable summary block of the exact form::

        <!-- PROMPT-SUMMARY
        what: <one line: what this prompt is>
        when: <one line: when to use it>
        not: <one line: when NOT to use it / what it is not>
        -->

    The block is PREPENDED right after the ``# Title``; it does NOT rewrite the
    body (an HTML comment, invisible when rendered, greppable via
    ``grep PROMPT-SUMMARY``). An agent navigating by grep finds the right prompt
    without reading 200-1300 line files whole.

    ALLOWLIST is intentionally BOUNDED (WOT-2026-022o anti-scope): EXACTLY the
    pilot (``orchestrator_session_bootstrap.md``) plus ``orchestrator_pipeline.md``
    -- the two prompts the ticket cited as opening without an indexable summary.
    Adopting more prompts is INCREMENTAL in successor tickets, NOT this one: do
    not widen this allowlist here (the floor and the ceiling are both fixed).
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
HEADER_SCAN_LINES = 12
MARKER = "<!-- PROMPT-SUMMARY"
CLOSE = "-->"
REQUIRED_KEYS = ("what:", "when:", "not:")

# BOUNDED allowlist -- see the module docstring. Do NOT widen here.
ALLOWLIST = (
    "orchestrator_session_bootstrap.md",  # pilot
    "orchestrator_pipeline.md",
)


def _summary_block(text: str) -> list[str]:
    """Return the PROMPT-SUMMARY block lines within the scan window, or [].

    Before: ``text`` is a prompt's full content. During: scan only the first
    HEADER_SCAN_LINES lines for the MARKER, then take up to its CLOSE line.
    After: the block's lines (marker..close inclusive), or [] if absent/unclosed
    within the window.
    """
    lines = text.splitlines()[:HEADER_SCAN_LINES]
    start = next((i for i, ln in enumerate(lines) if MARKER in ln), None)
    if start is None:
        return []
    end = next((i for i in range(start, len(lines)) if lines[i].strip() == CLOSE), None)
    if end is None:
        return []
    return lines[start : end + 1]


@pytest.mark.parametrize("prompt_name", ALLOWLIST)
def test_allowlisted_prompt_has_summary_header(prompt_name: str) -> None:
    """Each allowlisted prompt carries the greppable PROMPT-SUMMARY block within
    the first HEADER_SCAN_LINES lines, with all three keys (what/when/not).

    Mutation (teeth): remove the block -- or any one of the three keys -- from an
    allowlisted prompt and this test FAILS (empty block, or a missing key).
    """
    path = PROMPTS_DIR / prompt_name
    assert path.is_file(), f"allowlisted prompt missing on disk: {path}"
    block = _summary_block(path.read_text(encoding="utf-8"))
    assert block, (
        f"{prompt_name}: no '{MARKER} ... {CLOSE}' block within the first "
        f"{HEADER_SCAN_LINES} lines"
    )
    block_text = "\n".join(block).lower()
    missing = [key for key in REQUIRED_KEYS if key not in block_text]
    assert not missing, f"{prompt_name}: PROMPT-SUMMARY block missing keys {missing}"


def test_allowlist_is_bounded() -> None:
    """Anti-scope guard (WOT-2026-022o): the allowlist stays SMALL and fixed to
    the pilot + the two cited prompts. If a future change widens it here (instead
    of in a successor ticket), this test flags it so the scope decision is
    explicit, not silent."""
    assert set(ALLOWLIST) == {
        "orchestrator_session_bootstrap.md",
        "orchestrator_pipeline.md",
    }, "widening the 022o allowlist belongs in a successor ticket, not here"
