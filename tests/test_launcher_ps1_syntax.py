"""Syntax/structure barrier for scripts/launch_agent_terminals.ps1.

The launcher (1,800+ lines, 40+ functions) has no functional test harness:
it executes its main flow on dot-source (no invocation guard), so functions
cannot be imported in isolation yet. This barrier provides the minimum
safety net that future decomposition work requires:

1. The file parses under the real PowerShell AST parser (no syntax errors).
2. The function inventory does not silently shrink (a botched extraction
   that deletes or truncates a function fails here).

This is explicitly a SYNTACTIC barrier, not a functional one - see
prompts/audit_agent_output.md (infra scripts need functional checks under
real constraints). Functional coverage requires first adding an invocation
guard to the launcher; that is the follow-up this barrier unblocks.

[NON-REVERSE-CLASSICAL: structural barrier for an untested legacy script]
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER = _MOTOR_ROOT / "scripts" / "launch_agent_terminals.ps1"

# Regression floor: the launcher had 44 functions when this barrier was
# created. A lower count means an extraction deleted something silently.
_MIN_FUNCTION_COUNT = 40

_POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


_PARSE_SNIPPET = r"""
$errors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{path}', [ref]$tokens, [ref]$errors)
$functions = $ast.FindAll(
    {{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }},
    $true)
@{{ errors = @($errors | ForEach-Object {{ $_.Message }});
    function_count = $functions.Count }} | ConvertTo-Json -Compress
"""


@pytest.fixture(scope="module")
def parse_result() -> dict:
    if _POWERSHELL is None:
        pytest.skip("PowerShell not available on this host")
    snippet = _PARSE_SNIPPET.format(path=str(_LAUNCHER))
    result = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", snippet],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"parser invocation failed: {result.stderr}"
    return json.loads(result.stdout.strip())


def test_launcher_exists() -> None:
    assert _LAUNCHER.is_file(), f"launcher missing at {_LAUNCHER}"


def test_launcher_parses_without_syntax_errors(parse_result: dict) -> None:
    assert parse_result["errors"] in ([], None), (
        f"PowerShell parser reported syntax errors: {parse_result['errors']}"
    )


def test_launcher_function_inventory_floor(parse_result: dict) -> None:
    count = parse_result["function_count"]
    assert count >= _MIN_FUNCTION_COUNT, (
        f"Launcher defines {count} functions, below the {_MIN_FUNCTION_COUNT} "
        "floor - did an extraction silently delete or truncate one?"
    )
