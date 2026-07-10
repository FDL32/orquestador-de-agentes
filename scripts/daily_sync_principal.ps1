<#
.SYNOPSIS
    Sincroniza (una vez al dia) el checkout PRINCIPAL del motor con origin/main,
    de forma segura: nunca pierde trabajo de otra sesion.

.DESCRIPTION
    Envoltura fina sobre scripts/sync_principal.py pensada para el Programador de
    tareas de Windows (Task Scheduler). Corre desde la worktree-dev (donde vive el
    venv del motor), hace `git fetch` y aplica el sync:

      - Si el principal esta al dia -> no toca nada.
      - Si esta detras (ancestro de origin/main) -> fast-forward limpio.
      - Si tiene commits DIVERGENTES sin pushear -> crea una rama de rescate
        `rescue/<sha>-<fecha>` ANTES de avanzar (nada se pierde), y lo reporta.
      - Si el principal esta en una rama con nombre (no detached) -> NO lo toca.

    El resultado (incluida la COLA de ramas rescue/* pendientes de reintegrar en
    main) se escribe en el log para que su dueno las termine y mergee.

    Este script asume la topologia que crea setup_dev_worktree.ps1: principal
    detached (solo-consumo) + worktree-dev en `main`.

.PARAMETER DryRun
    Solo reporta la accion, no la aplica. Sin este flag, aplica el sync.

.PARAMETER LogPath
    Fichero de log (append). Por defecto:
    <_dev>\.agent\runtime\sync_principal\daily.log

.EXAMPLE
    # ejecucion manual (dry-run):
    powershell -File scripts\daily_sync_principal.ps1 -DryRun

.EXAMPLE
    # ejecucion real:
    powershell -File scripts\daily_sync_principal.ps1

.NOTES
    Registro en Task Scheduler (diario 06:00), una sola linea en PowerShell:

      $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NonInteractive -File `"$PWD\scripts\daily_sync_principal.ps1`""
      $trigger = New-ScheduledTaskTrigger -Daily -At 6:00am
      Register-ScheduledTask -TaskName "motor-sync-principal" `
        -Action $action -Trigger $trigger -Description "Sync motor primary to main"

    Verifica luego con:  Get-ScheduledTask -TaskName motor-sync-principal
    y revisa el log en .agent\runtime\sync_principal\daily.log
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$LogPath
)

$ErrorActionPreference = 'Stop'

# The dev worktree = the parent of this script's scripts/ dir (this file lives in
# <_dev>\scripts\). That worktree carries the venv and IS a worktree of the motor.
$DevRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $DevRoot '.venv\Scripts\python.exe'
$SyncScript = Join-Path $DevRoot 'scripts\sync_principal.py'

if (-not (Test-Path $Python)) {
    Write-Error "[daily-sync] venv python not found at $Python. Run setup_dev_worktree.ps1 first."
    exit 2
}
if (-not (Test-Path $SyncScript)) {
    Write-Error "[daily-sync] sync_principal.py not found at $SyncScript."
    exit 2
}

if (-not $LogPath) {
    $LogDir = Join-Path $DevRoot '.agent\runtime\sync_principal'
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    }
    $LogPath = Join-Path $LogDir 'daily.log'
}

# Build the sync_principal.py argument list. --motor-root is the dev worktree
# (any worktree of the repo works; the primary is auto-detected). --fetch keeps
# origin/main current before planning.
$syncArgs = @('--motor-root', $DevRoot, '--fetch')
if (-not $DryRun) {
    $syncArgs += '--apply'
}

$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$output = & $Python $SyncScript @syncArgs 2>&1
$exit = $LASTEXITCODE

$header = "===== $stamp (exit=$exit, dryrun=$($DryRun.IsPresent)) ====="
Add-Content -Path $LogPath -Value $header -Encoding utf8
Add-Content -Path $LogPath -Value $output -Encoding utf8

# Echo to stdout too, so a manual run or Task Scheduler history shows it.
Write-Output $header
Write-Output $output

exit $exit
