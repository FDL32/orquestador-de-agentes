"""Regression tests for the OpenCode branch of launch_agent_terminals.ps1.

WP-2026-067 introduced an OpenCode integration that built an args array and
stringified it directly into Start-AgentWindow's -Command payload. PowerShell
joined the array with spaces and destroyed the quoting of the multi-word
prompt, so OpenCode received fragmented arguments and printed [message..]
help instead of running the ticket. Gates passed because no test exercised
this code path.

These tests validate the launcher source structurally so the same regression
cannot reappear silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_agent_terminals.ps1"


@pytest.fixture(scope="module")
def opencode_branch() -> str:
    """Return the body of the `if ($builderBackend -eq 'opencode')` block."""
    source = LAUNCHER.read_text(encoding="utf-8")
    start_marker = "if ($builderBackend -eq 'opencode')"
    end_marker = "else {"
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_launcher_file_exists() -> None:
    assert LAUNCHER.is_file(), f"launcher not found at {LAUNCHER}"


def test_opencode_branch_single_quotes_prompt(opencode_branch: str) -> None:
    """The composed prompt must be wrapped via ConvertTo-SingleQuotedLiteral
    before being injected into the -Command payload. Without this, the
    multi-word prompt gets split into multiple args by PowerShell."""
    assert "ConvertTo-SingleQuotedLiteral $builderPrompt" in opencode_branch, (
        "OpenCode branch must wrap the prompt in single-quote literal; "
        "regression of WP-2026-067 silent quoting bug"
    )


def test_opencode_branch_does_not_stringify_args_array(
    opencode_branch: str,
) -> None:
    """The bug pattern is interpolating a PowerShell array directly into a
    double-quoted command string: '\"& $exe $builderArgs\"'. That join
    destroys quoting. Asserting the anti-pattern is not present."""
    assert '"& $builderExeLiteral $builderArgs"' not in opencode_branch, (
        "OpenCode branch must not stringify a raw $builderArgs array into "
        "-Command; this is the WP-2026-067 regression"
    )


def test_opencode_branch_reads_model_from_config(opencode_branch: str) -> None:
    """The model must come from .opencode/opencode.json, never hardcoded."""
    assert "$opencodeConfig.model" in opencode_branch, (
        "model must be read from .opencode/opencode.json"
    )
    assert "opencode-go/qwen3.5-plus" not in opencode_branch, (
        "model must not be hardcoded in the launcher"
    )


def test_opencode_branch_attaches_canonical_files(opencode_branch: str) -> None:
    """Canonical state files must be attached via -f so the OpenCode session
    has the ticket context. The list comes from Get-CanonicalFilesForOpenCode."""
    assert "Get-CanonicalFilesForOpenCode" in opencode_branch, (
        "canonical files must be obtained from the helper function"
    )
    assert "-f " in opencode_branch, (
        "branch must construct -f flags for canonical files"
    )
