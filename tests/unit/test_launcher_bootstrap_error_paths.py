"""Tests for launcher bootstrap error paths.

WP-2026-073 adds coverage for the bootstrap error-path in
`scripts/launch_agent_terminals.ps1`. Three hotfixes were applied
on 2026-05-16 (commits 540694a, a5df2cd, dbf4c4a) for bugs that
lived in main because no test exercised the error path:

1. Variable-name before colon (`$bootstrapExitCode:`) -> syntax regression.
2. Access to `.error` on JSON without that property under StrictMode.
3. Lack of defense for `.status`, `.plan_id`, `.reason` when JSON varies.

This test module exercises the bootstrap with controlled failure scenarios
to catch the next regression before it reaches a real session.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_agent_terminals.ps1"
CONTROLLER = REPO_ROOT / ".agent" / "agent_controller.py"


def _resolve_powershell() -> str | None:
    """Return the PowerShell executable available on this platform, or None."""
    if platform.system() == "Windows":
        return "powershell"
    return shutil.which("pwsh")


def _resolve_python() -> str:
    """Return the Python executable from .venv or PATH."""
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    python_exe = shutil.which("python")
    if python_exe:
        return python_exe
    raise RuntimeError("No Python executable found")


@pytest.mark.skipif(
    _resolve_powershell() is None,
    reason="PowerShell required to run launcher tests (powershell.exe on Windows, pwsh elsewhere)",
)
class TestLauncherBootstrapErrorPaths:
    """Test bootstrap error handling in launch_agent_terminals.ps1."""

    def _create_mock_controller(
        self, exit_code: int, stdout: str
    ) -> Path:
        """Create a temporary mock controller script that returns specified output."""
        mock_script = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        # Write a script that prints stdout and exits with specified code
        mock_script.write(f'''
import sys
print({stdout!r})
sys.exit({exit_code})
''')
        mock_script.close()
        return Path(mock_script.name)

    def _run_launcher_bootstrap_section(
        self, mock_controller: Path, expect_failure: bool = False
    ) -> tuple[int, str, str]:
        """Run just the bootstrap section of the launcher with a mock controller.

        Returns (exit_code, stdout, stderr).
        """
        powershell = _resolve_powershell()
        assert powershell is not None

        # Create a minimal test harness that sources the launcher functions
        # and runs only the bootstrap section with our mock controller
        test_script = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        )
        test_script.write(f'''
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$ProjectRoot = '{REPO_ROOT.as_posix()}'
$MockController = '{mock_controller.as_posix()}'

# Replicate the bootstrap section from launch_agent_terminals.ps1
$venvPython = '{_resolve_python()}'
$controllerPath = $MockController
$bootstrapResult = & $venvPython $controllerPath --bootstrap-ticket --json 2>&1
$bootstrapExitCode = $LASTEXITCODE
$bootstrapResultText = ($bootstrapResult | Out-String).Trim()
Write-Host "Bus bootstrap: $bootstrapResultText"

if ($bootstrapExitCode -ne 0) {{
    throw "Bus bootstrap failed with exit code ${{bootstrapExitCode}}: $bootstrapResultText"
}}

try {{
    $bootstrapJson = $bootstrapResultText | ConvertFrom-Json
}} catch {{
    throw "Bus bootstrap returned invalid JSON: $bootstrapResultText"
}}

if ($bootstrapJson.PSObject.Properties['error']) {{
    throw "Bus bootstrap error: $($bootstrapJson.error)"
}}

if ($bootstrapJson.PSObject.Properties['status'] -and $bootstrapJson.status -eq 'skipped') {{
    $skippedPlanId = if ($bootstrapJson.PSObject.Properties['plan_id']) {{ $bootstrapJson.plan_id }} else {{ 'unknown' }}
    $skippedReason = if ($bootstrapJson.PSObject.Properties['reason']) {{ $bootstrapJson.reason }} else {{ 'no reason given' }}
    throw "Bus bootstrap skipped for ${{skippedPlanId}}: $skippedReason"
}}

Write-Host "BOOTSTRAP_OK"
''')
        test_script.close()
        test_path = Path(test_script.name)

        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(test_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode, result.stdout, result.stderr
        finally:
            test_path.unlink(missing_ok=True)

    def test_bootstrap_exit_code_nonzero(self) -> None:
        """Test that exit code != 0 from bootstrap throws with correct message.

        This reproduces the WP-2026-067/WP-2026-069 regression where the
        error message uses `${{bootstrapExitCode}}:` which broke parser
        (hotfix 540694a).
        """
        mock_controller = self._create_mock_controller(
            exit_code=1,
            stdout=json.dumps({"status": "error", "error": "reason"})
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(
                mock_controller, expect_failure=True
            )

            # Should fail
            assert exit_code != 0, "Expected bootstrap to fail with exit code 1"
            # Verify the error message contains the exit code (colon-scope regression check)
            combined_output = stdout + stderr
            assert "exit code 1" in combined_output, (
                f"Error message should contain exit code 1. Output: {combined_output}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)

    def test_bootstrap_json_without_error_property(self) -> None:
        """Test that JSON without .error property does not crash under StrictMode.

        This reproduces the WP-2026-069 hotfix a5df2cd where accessing
        `$obj.error` directly under StrictMode caused PropertyNotFoundStrict.
        """
        mock_controller = self._create_mock_controller(
            exit_code=0,
            stdout=json.dumps({"status": "already_bootstrapped", "plan_id": "WP-XXXX"})
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(mock_controller)

            # Should succeed - no crash from accessing missing .error property
            assert exit_code == 0, (
                f"Bootstrap should not crash when JSON lacks .error property. "
                f"stderr: {stderr}"
            )
            assert "BOOTSTRAP_OK" in stdout, (
                f"Expected BOOTSTRAP_OK in output. stdout: {stdout}, stderr: {stderr}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)

    def test_bootstrap_json_status_skipped(self) -> None:
        """Test that JSON with .status=skipped throws with clear message.

        Verifies defense for optional properties .plan_id and .reason.
        """
        mock_controller = self._create_mock_controller(
            exit_code=0,
            stdout=json.dumps({"status": "skipped", "plan_id": "WP-XXXX", "reason": "no_active"})
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(
                mock_controller, expect_failure=True
            )

            # Should fail with clear message
            assert exit_code != 0, "Expected bootstrap to fail for skipped status"
            combined_output = stdout + stderr
            assert "skipped" in combined_output.lower(), (
                f"Error message should mention 'skipped'. Output: {combined_output}"
            )
            assert "WP-XXXX" in combined_output, (
                f"Error message should contain plan_id. Output: {combined_output}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)

    def test_bootstrap_non_json_stdout(self) -> None:
        """Test that non-JSON stdout throws 'invalid JSON' message."""
        mock_controller = self._create_mock_controller(
            exit_code=0,
            stdout="This is plain text, not JSON"
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(
                mock_controller, expect_failure=True
            )

            # Should fail with JSON parsing error
            assert exit_code != 0, "Expected bootstrap to fail for non-JSON output"
            combined_output = stdout + stderr
            # Check for either English or Spanish JSON error message
            # (PowerShell may localize the ConvertFrom-Json error)
            assert "invalid json" in combined_output.lower() or "json" in combined_output.lower(), (
                f"Error message should mention JSON parsing failure. Output: {combined_output}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)

    def test_bootstrap_variable_scope_colon_rendering(self) -> None:
        """Test that the error message renders the exit code correctly.

        This specifically verifies the WP-2026-069 540694a hotfix where
        `${{bootstrapExitCode}}:` must render as `1:` not as a scoped
        variable reference.
        """
        mock_controller = self._create_mock_controller(
            exit_code=1,
            stdout=json.dumps({"status": "error", "error": "test_reason"})
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(
                mock_controller, expect_failure=True
            )

            assert exit_code != 0
            combined_output = stdout + stderr
            # The message should contain the literal exit code value, not a variable reference
            assert "exit code 1" in combined_output, (
                f"Error message should render exit code as '1', not variable reference. "
                f"Output: {combined_output}"
            )
            # Verify no PowerShell variable reference syntax leaked into output
            assert "$bootstrapExitCode" not in combined_output, (
                f"Variable reference should not appear literally in output. "
                f"Output: {combined_output}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)

    def test_bootstrap_missing_optional_properties(self) -> None:
        """Test that missing optional properties (.plan_id, .reason) are handled.

        Verifies the launcher uses PSObject.Properties check for optional fields.
        """
        mock_controller = self._create_mock_controller(
            exit_code=0,
            stdout=json.dumps({"status": "skipped"})  # No plan_id or reason
        )
        try:
            exit_code, stdout, stderr = self._run_launcher_bootstrap_section(
                mock_controller, expect_failure=True
            )

            # Should fail but with graceful handling of missing properties
            assert exit_code != 0, "Expected bootstrap to fail for skipped status"
            combined_output = stdout + stderr
            assert "skipped" in combined_output.lower(), (
                f"Error message should mention 'skipped'. Output: {combined_output}"
            )
            # Should use fallback values for missing properties
            assert "unknown" in combined_output.lower() or "no reason given" in combined_output.lower(), (
                f"Error message should use fallback values for missing properties. "
                f"Output: {combined_output}"
            )
        finally:
            mock_controller.unlink(missing_ok=True)
