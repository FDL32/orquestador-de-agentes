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

import importlib.util
import json
import platform
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_agent_terminals.ps1"
DIAGNOSTIC_SCRIPT = REPO_ROOT / "scripts" / "diagnose_builder_orphans.py"


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


@pytest.mark.skipif(
    _resolve_powershell() is None,
    reason="PowerShell required to query launcher source",
)
def test_stop_builder_no_env_var_patterns() -> None:
    """WT-2026-242c: AGENT_BUILDER_TICKET/ROUND patterns removed from Stop-ProjectBuilderProcesses.

    These patterns were dead code: Win32_Process.CommandLine does not contain
    environment variables. The detection must rely solely on CLI-arg patterns.
    """
    launcher_source = LAUNCHER.read_text(encoding="utf-8")

    func_start = launcher_source.find("function Stop-ProjectBuilderProcesses")
    assert func_start != -1, "Stop-ProjectBuilderProcesses function not found"

    patterns_marker = "$builderProcessPatterns = @("
    patterns_start = launcher_source.find(patterns_marker, func_start)
    assert patterns_start != -1, "$builderProcessPatterns array not found in function"

    patterns_end = launcher_source.find(")", patterns_start)
    patterns_section = launcher_source[patterns_start:patterns_end]

    assert "AGENT_BUILDER_TICKET" not in patterns_section, (
        "AGENT_BUILDER_TICKET still in $builderProcessPatterns — dead code not cleaned"
    )
    assert "AGENT_BUILDER_ROUND" not in patterns_section, (
        "AGENT_BUILDER_ROUND still in $builderProcessPatterns — dead code not cleaned"
    )

    func_section = launcher_source[func_start : func_start + 2000]
    assert "opencode.*run.*--agent" in func_section, (
        "opencode.*run.*--agent pattern missing from Stop-ProjectBuilderProcesses"
    )


def test_diagnostic_script_importable() -> None:
    """WT-2026-242c: diagnose_builder_orphans.py must be importable."""
    assert DIAGNOSTIC_SCRIPT.is_file(), (
        f"diagnostic script not found at {DIAGNOSTIC_SCRIPT}"
    )

    spec = importlib.util.spec_from_file_location(
        "diagnose_builder_orphans", str(DIAGNOSTIC_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert hasattr(mod, "diagnose"), "diagnose() function not found"
    assert hasattr(mod, "_read_builder_lock"), "_read_builder_lock() not found"
    assert hasattr(mod, "_is_bus_state_post_success"), (
        "_is_bus_state_post_success() not found"
    )


def test_diagnostic_bus_state_post_success() -> None:
    """WT-2026-242c: _is_bus_state_post_success must identify orphan-safe states."""
    spec = importlib.util.spec_from_file_location(
        "diagnose_builder_orphans", str(DIAGNOSTIC_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for state in ("READY_FOR_REVIEW", "READY_TO_CLOSE", "HUMAN_GATE", "COMPLETED"):
        assert mod._is_bus_state_post_success(state), f"{state} should be post-success"

    assert not mod._is_bus_state_post_success("IN_PROGRESS")
    assert not mod._is_bus_state_post_success(None)
    assert not mod._is_bus_state_post_success("UNKNOWN_STATE")


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="WMI orphan detection only available on Windows",
)
def test_diagnostic_runs_on_clean_state() -> None:
    """WT-2026-242c: diagnostic must run without error on a clean project."""
    spec = importlib.util.spec_from_file_location(
        "diagnose_builder_orphans", str(DIAGNOSTIC_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    workspace = REPO_ROOT.parent / "orquestador_de_agentes_workspace"
    result = mod.diagnose(str(workspace))
    assert "gap_confirmed" in result
    assert "builder_processes" in result
    assert isinstance(result["builder_processes"], list)


def test_builder_lock_enriched_content(tmp_path):
    """WT-2026-242c: _read_builder_lock must parse enriched identity contract.

    Verifica que el lock escrito con el formato exacto del launcher
    (ticket_id, project_root, started_at, role, backend, round, pid)
    es correctamente parseado por _read_builder_lock, devolviendo
    todos los campos de identidad enriquecida.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "diagnose_builder_orphans", str(DIAGNOSTIC_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    lock_dir = tmp_path / ".agent" / "runtime"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / "builder_lock.txt"

    lock_data = {
        "ticket_id": "WT-2026-242c",
        "project_root": str(tmp_path),
        "started_at": "2026-06-09T08:00:00.0000000Z",
        "role": "BUILDER",
        "backend": "open-code",
        "round": 1,
        "pid": 1234,
    }
    lock_file.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")

    result = mod._read_builder_lock(str(tmp_path))

    assert result is not None, "_read_builder_lock returned None"
    assert result["ticket_id"] == "WT-2026-242c"
    assert result["project_root"] == str(tmp_path)
    assert result["started_at"] == "2026-06-09T08:00:00.0000000Z"
    assert result["role"] == "BUILDER"
    assert result["backend"] == "open-code"
    assert result["round"] == 1
    assert result["pid"] == 1234
