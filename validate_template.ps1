$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $scriptDir

Write-Host "Validating portable template..." -ForegroundColor Cyan

$steps = @(
    @{ Name = "Controller validation"; Cmd = "python .agent/agent_controller.py --validate --json --force" },
    @{ Name = "Controller state"; Cmd = "python .agent/agent_controller.py --json --force" },
    @{ Name = "Safe tests"; Cmd = "python scripts/run_pytest_safe.py tests/unit/test_windows_safe_temp_runtime.py -q -p no:cacheprovider" },
    @{ Name = "Core lint"; Cmd = "ruff check .agent/hooks/guard_paths.py tests" }
)

foreach ($step in $steps) {
    Write-Host "`n[$($step.Name)]" -ForegroundColor Yellow
    cmd /c $step.Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Validation failed at: $($step.Name)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`nTemplate validation passed." -ForegroundColor Green
