"""Regression test: launcher script must parse cleanly in PowerShell.

WP-2026-069 introduced a bootstrap throw using `"$bootstrapExitCode:"`
which PowerShell parsed as a scoped variable reference (like
`$env:VAR`) instead of a literal colon. The launcher failed at parse
time before reaching any logic. Hotfix 540694a wrapped the variable
with curly braces so the colon is treated as literal.

This test runs PowerShell's parser over the entire launcher and fails
if any syntax error is introduced. It catches the class of
"variable-name-followed-by-colon" bugs as well as any other parser
issues from future edits, regardless of whether the broken path is
exercised by other tests.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_agent_terminals.ps1"


def _resolve_powershell() -> str | None:
    """Return the PowerShell executable available on this platform, or None."""
    if platform.system() == "Windows":
        return "powershell"
    return shutil.which("pwsh")


@pytest.mark.skipif(
    _resolve_powershell() is None,
    reason="PowerShell required to parse the launcher (powershell.exe on Windows, pwsh elsewhere)",
)
def test_launcher_file_exists() -> None:
    assert LAUNCHER.is_file(), f"launcher not found at {LAUNCHER}"


@pytest.mark.skipif(
    _resolve_powershell() is None,
    reason="PowerShell required to parse the launcher (powershell.exe on Windows, pwsh elsewhere)",
)
def test_launcher_powershell_parses_cleanly() -> None:
    """Run PowerShell's parser over the launcher; fail on any syntax error.

    Uses `Get-Command -Syntax` which forces a parse of the script
    without invoking it. A clean parse prints the parameter signature;
    a syntax error returns non-zero and prints a ParserError to stderr.
    """
    powershell = _resolve_powershell()
    assert powershell is not None  # already guarded by skipif

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            f"Get-Command -Syntax -Name '{LAUNCHER.as_posix()}'; if ($?) {{ 'PARSED-OK' }}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"launcher PowerShell parser failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "PARSED-OK" in result.stdout, (
        f"PowerShell did not confirm clean parse:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
