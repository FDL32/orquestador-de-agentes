[CmdletBinding()]
param(
    # Default deferred to after param-binding because $PSScriptRoot,
    # $PSCommandPath, and $MyInvocation.MyCommand.Path can all be empty/null
    # during param-block default evaluation when PowerShell 5.1 is invoked via
    # subprocess argv. Supervisor relaunch path SHOULD pass -ProjectRoot
    # explicitly to avoid any path-detection dance.
    [string]$ProjectRoot,
    [string]$ManagerBackendPath,
    [string]$BuilderPrompt,
    [switch]$LaunchBuilder = $true,
    [switch]$LaunchSupervisor = $true,
    [switch]$LaunchBridge = $true,
    [switch]$LaunchMonitor = $true,
    [switch]$LaunchWatcher = $false,
    [switch]$StrictLaunch = $true,
    [switch]$ResumeBuilder = $false,
    [switch]$OnlyBuilder = $false,
    [switch]$SkipSupervisorWait = $false
)

$ErrorActionPreference = 'Stop'

function Resolve-DestinationRoot {
    param([Parameter(Mandatory)] [string]$MotorRoot)

    # Intenta leer motor_destination_link.json desde el motor actual
    # y devuelve destination_root si existe.
    $linkPath = Join-Path $MotorRoot '.agent\config\motor_destination_link.json'
    if (Test-Path -LiteralPath $linkPath) {
        try {
            $link = Get-Content -LiteralPath $linkPath -Raw | ConvertFrom-Json
            if ($null -ne $link.destination_root -and (Test-Path -LiteralPath $link.destination_root)) {
                return (Resolve-Path -LiteralPath $link.destination_root).Path
            }
        }
        catch {
            Write-Warning "motor_destination_link.json existe pero no es legible; se usara el fallback local."
        }
    }
    return $null
}


# Resolve ProjectRoot AFTER param binding (here $PSScriptRoot, $PSCommandPath
# and $MyInvocation.MyCommand.Path are reliably populated).
# Precedencia canonica: --project-root > AGENT_PROJECT_ROOT > motor_destination_link.json > fallback local
if (-not $ProjectRoot) {
    # 1) CLI ya fue chequeado (es $null)
    # 2) Env var AGENT_PROJECT_ROOT
    $envProjectRoot = [System.Environment]::GetEnvironmentVariable('AGENT_PROJECT_ROOT')
    if (-not [string]::IsNullOrWhiteSpace($envProjectRoot) -and (Test-Path -LiteralPath $envProjectRoot)) {
        $ProjectRoot = (Resolve-Path -LiteralPath $envProjectRoot).Path
        Write-Host "ProjectRoot resuelto desde AGENT_PROJECT_ROOT: $ProjectRoot"
    }
    else {
        # 3) motor_destination_link.json (desde el motor actual)
        $scriptDir = $null
        if ($PSScriptRoot) {
            $scriptDir = $PSScriptRoot
        } elseif ($PSCommandPath) {
            $scriptDir = Split-Path -Parent $PSCommandPath
        } elseif ($MyInvocation -and $MyInvocation.MyCommand -and $MyInvocation.MyCommand.Path) {
            $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
        }
        if (-not $scriptDir) {
            throw "Cannot resolve script directory automatically. Pass -ProjectRoot <path> explicitly."
        }
        $motorRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path
        $destinationRoot = Resolve-DestinationRoot -MotorRoot $motorRoot
        if ($null -ne $destinationRoot) {
            $ProjectRoot = $destinationRoot
            Write-Host "ProjectRoot resuelto desde motor_destination_link.json: $ProjectRoot"
        }
        else {
            # 4) Fallback local
            $ProjectRoot = $motorRoot
            Write-Host "ProjectRoot resuelto desde fallback local (motor): $ProjectRoot"
        }
    }
}

Set-StrictMode -Version Latest

# WP-2026-176: Motor code root â€” always derived from this script's location.
# Code files (agents_config.py, bus/, .agent/) live in the motor, not in the workspace.
# Defined here so all functions can reference it via $script:_MotorCodeRoot.
$_scriptDirForMotor = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
$script:_MotorCodeRoot = if ($_scriptDirForMotor) { (Resolve-Path (Join-Path $_scriptDirForMotor '..')).Path } else { $ProjectRoot }

# OnlyBuilder: when invoked from supervisor requeue (subprocess), force-disable
# the other launchers. Avoids the PowerShell 5.1 SwitchParameter cast issue
# where `-LaunchSupervisor:$false` or `:0` arrive as strings via argv and fail
# to bind. This switch is additive â€” interactive launching unaffected.
if ($OnlyBuilder) {
    $LaunchSupervisor = $false
    $LaunchBridge = $false
    $LaunchMonitor = $false
    $LaunchWatcher = $false
}

function ConvertTo-SingleQuotedLiteral {
    param([Parameter(Mandatory)] [string]$Text)
    return "'" + ($Text -replace "'", "''") + "'"
}

function Resolve-VenvPython {
    param([Parameter(Mandatory)] [string]$Root)

    $candidate = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }

    $fallback = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $fallback) {
        return $fallback.Source
    }

    throw 'No se encontro python en .venv ni en PATH.'
}

function Resolve-HostShellExecutable {
    $currentProcess = Get-Process -Id $PID -ErrorAction SilentlyContinue
    if ($null -ne $currentProcess -and -not [string]::IsNullOrWhiteSpace($currentProcess.Path) -and (Test-Path -LiteralPath $currentProcess.Path)) {
        return $currentProcess.Path
    }

    foreach ($candidate in @('pwsh.exe', 'powershell.exe')) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw 'No se pudo resolver el ejecutable del shell anfitrion.'
}

function Assert-CanonicalProjectRoot {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    # La raiz es canonica por su estructura .agent/, no por el nombre de la
    # carpeta: el repo puede renombrarse (desacople motor/destino, WP-2026-072+).

    $requiredPaths = @(
        '.agent\collaboration\work_plan.md',
        '.agent\collaboration\TURN.md',
        '.agent\collaboration\execution_log.md',
        '.agent\collaboration\STATE.md',
        '.agent\runtime\events\events.jsonl'
    )

    foreach ($relative in $requiredPaths) {
        $absolute = Join-Path $resolvedRoot $relative
        if (-not (Test-Path -LiteralPath $absolute)) {
            throw "Falta el artefacto canÃ³nico requerido: $relative"
        }
    }

    return $resolvedRoot
}

function Get-PlanIdFromContent {
    param(
        [Parameter(Mandatory)] [string]$Content,
        [Parameter(Mandatory)] [string]$Pattern,
        [Parameter(Mandatory)] [string]$SourceName
    )

    if ($Content -match $Pattern) {
        return $Matches[1]
    }

    throw "No se pudo extraer el plan activo desde $SourceName."
}

function Get-PlanIdFromWorkPlanContent {
    param([Parameter(Mandatory)] [string]$Content)

    $patterns = @(
        '\*\*Plan activo:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '\*\*ID:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '^\s*##\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)\s*:',
        '((?:WP|WT)-\d{4}-[A-Za-z0-9]+)'
    )

    foreach ($pattern in $patterns) {
        try {
            return Get-PlanIdFromContent -Content $Content -Pattern $pattern -SourceName 'work_plan.md'
        }
        catch {
            continue
        }
    }

    throw 'No se pudo extraer el plan activo desde work_plan.md.'
}

function Get-PlanIdFromStateContent {
    param([Parameter(Mandatory)] [string]$Content)

    $patterns = @(
        '-\s*\*\*Plan Activo:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '-\s*\*\*ID:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '\*\*Plan Activo:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '\*\*ID:\*\*\s*((?:WP|WT)-\d{4}-[A-Za-z0-9]+)',
        '((?:WP|WT)-\d{4}-[A-Za-z0-9]+)'
    )

    foreach ($pattern in $patterns) {
        try {
            return Get-PlanIdFromContent -Content $Content -Pattern $pattern -SourceName 'STATE.md'
        }
        catch {
            continue
        }
    }

    throw 'No se pudo extraer el plan activo desde STATE.md.'
}

function Get-OptionalPlanIdFromTurnContent {
    param([Parameter(Mandatory)] [string]$Content)

    $planIdPattern = '(?:WP|WT)-\d{4}-[A-Za-z0-9]+'
    $pattern = "\|\s*\*\*Plan ID\*\*\s*\|\s*\*{0,2}($planIdPattern)\*{0,2}\s*\|"
    if ($Content -match $pattern) {
        return $Matches[1]
    }

    if ($Content -match '\|\s*\*\*Plan ID\*\*\s*\|\s*NINGUNO\s*\|') {
        return $null
    }

    return $null
}

function Get-OptionalPropertyValue {
    param(
        [object]$Object,
        [Parameter(Mandatory)] [string[]]$Names
    )

    foreach ($name in $Names) {
        if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $name) {
            return $Object.$name
        }
    }

    return $null
}

function Get-CurrentBuilderRound {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $supervisorStatePath = Join-Path $ProjectRoot '.agent\runtime\supervisor_state.json'
    if (-not (Test-Path -LiteralPath $supervisorStatePath)) {
        return 1
    }

    try {
        $state = Get-Content -LiteralPath $supervisorStatePath -Raw | ConvertFrom-Json
        $round = [int](Get-OptionalPropertyValue -Object $state -Names @('loop_current_round'))
        # Para Builder inicial, si round=0 (no requeue aÃºn), es BR1
        # Si round=1, significa que ya hubo un requeue, asÃ­ que prÃ³ximo Builder es BR2, etc.
        return [Math]::Max(1, $round + 1)
    }
    catch {
        return 1
    }
}

function Read-BuilderLockState {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $lockPath = Join-Path $ProjectRoot '.agent\runtime\builder_lock.txt'
    if (-not (Test-Path -LiteralPath $lockPath)) {
        return $null
    }

    try {
        $raw = (Get-Content -LiteralPath $lockPath -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $null
        }

        if ($raw.StartsWith('{')) {
            $state = $raw | ConvertFrom-Json
            return [pscustomobject]@{
                LockPath     = $lockPath
                TicketId     = Get-OptionalPropertyValue -Object $state -Names @('ticket_id', 'ticketId')
                ProjectRoot  = Get-OptionalPropertyValue -Object $state -Names @('project_root', 'projectRoot')
                StartedAt    = Get-OptionalPropertyValue -Object $state -Names @('started_at', 'startedAt')
                # WP-2026-117: PID eliminado del contrato del lock - no usar como seÃ±al de vida
                Role         = Get-OptionalPropertyValue -Object $state -Names @('role')
                Backend      = Get-OptionalPropertyValue -Object $state -Names @('backend')
                Round        = Get-OptionalPropertyValue -Object $state -Names @('round')
                Raw          = $state
                LegacyFormat = $false
            }
        }

        return [pscustomobject]@{
            LockPath     = $lockPath
            TicketId     = $null
            ProjectRoot  = $ProjectRoot
            StartedAt    = $raw
            Pid          = $null
            Role         = 'BUILDER'
            Backend      = $null
            Raw          = $raw
            LegacyFormat = $true
        }
    }
    catch {
        Write-Warning "builder_lock.txt corrupto o no parseable; se eliminara. Detalle: $($_.Exception.Message)"
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Remove-StaleLegacyLock {
    param(
        [Parameter(Mandatory)] [string]$LockPath,
        [int]$MaxAgeSeconds = 300
    )

    if (-not (Test-Path -LiteralPath $LockPath)) {
        return $false
    }

    try {
        $item = Get-Item -LiteralPath $LockPath -ErrorAction Stop
        $fileAge = [DateTime]::UtcNow - $item.LastWriteTimeUtc
        if ($fileAge.TotalSeconds -gt $MaxAgeSeconds) {
            Write-Warning "builder_lock legacy supera el TTL ($([math]::Round($fileAge.TotalSeconds, 0)) s). Se eliminara."
            Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
            return $true
        }
    }
    catch {
        Write-Warning "No se pudo inspeccionar el builder_lock legacy. Se eliminara por seguridad."
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
        return $true
    }

    return $false
}

function Repair-BuilderLockState {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [int]$MaxAgeMinutes = 30
    )

    $state = Read-BuilderLockState -ProjectRoot $ProjectRoot
    if ($null -eq $state) {
        return $null
    }

    $lockPath = $state.LockPath
    $currentRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

    if (-not [string]::IsNullOrWhiteSpace($state.ProjectRoot)) {
        try {
            $lockRoot = (Resolve-Path -LiteralPath $state.ProjectRoot).Path
            if ($lockRoot -ne $currentRoot) {
                Write-Warning "builder_lock.txt pertenece a $lockRoot y el proyecto activo es $currentRoot. Se eliminara."
                Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
                return $null
            }
        }
        catch {
            Write-Warning "builder_lock.txt contiene una ruta de proyecto invalida. Se eliminara."
            Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
            return $null
        }
    }

    $workPlanPath = Join-Path $ProjectRoot '.agent\collaboration\work_plan.md'
    $workPlanContent = Get-Content -LiteralPath $workPlanPath -Raw
    $activeTicket = Get-PlanIdFromWorkPlanContent -Content $workPlanContent

    if ($state.TicketId -and $state.TicketId -ne $activeTicket) {
        Write-Warning "builder_lock.txt apunta a $($state.TicketId) y el ticket activo es $activeTicket. Se eliminara."
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        return $null
    }

    $startedAtText = $state.StartedAt
    $startedAt = $null
    if (-not [string]::IsNullOrWhiteSpace($startedAtText)) {
        try {
            $startedAt = [DateTimeOffset]::Parse(
                $startedAtText,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::RoundtripKind
            )
        }
        catch {
            $startedAt = $null
        }
    }

    if ($state.LegacyFormat) {
        $legacyLockRemoved = Remove-StaleLegacyLock -LockPath $lockPath -MaxAgeSeconds 300
        if ($legacyLockRemoved) {
            return $null
        }
    }

    if ($null -ne $startedAt) {
        $age = [DateTimeOffset]::UtcNow - $startedAt.ToUniversalTime()
        if ($age.TotalMinutes -gt $MaxAgeMinutes) {
            Write-Warning "builder_lock.txt excede el TTL ($([math]::Round($age.TotalMinutes, 1)) min). Se eliminara."
            Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
            return $null
        }
    }
    elseif (-not $state.LegacyFormat) {
        Write-Warning "builder_lock.txt no contiene un timestamp valido. Se eliminara."
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        return $null
    }

    if (-not $state.LegacyFormat) {
        Write-Warning "builder_lock.txt no contiene un timestamp valido. Se eliminara."
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        return $null
    }
    # WP-2026-117: PID eliminado del contrato - no verificar proceso por PID

    return $state
}

function Remove-StaleRuntimeArtifacts {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [int]$BuilderLockTtlMinutes = 30,
        [int]$PromptTtlMinutes = 15
    )

    $results = [ordered]@{
        BuilderLockRemoved = $false
        SupervisorLockRemoved = $false
        ManagerPromptRemoved = 0
        BridgeStateRepaired = $false
        SupervisorStateRepaired = $false
    }

    $bridgeStatePath = Join-Path $ProjectRoot '.agent\runtime\manager_bridge_state.json'
    if (Test-Path -LiteralPath $bridgeStatePath) {
        $alignment = Repair-StartupBridgeState -ProjectRoot $ProjectRoot
        $results.BridgeStateRepaired = $alignment.BridgeStateCorrupt -or (
            $null -ne $alignment.BridgeState -and
            $alignment.BridgeLastTicketId -and
            $alignment.BridgeLastTicketId -ne $alignment.WorkPlanId
        )
    }

    $supervisorStatePath = Join-Path $ProjectRoot '.agent\runtime\supervisor_state.json'
    if (Test-Path -LiteralPath $supervisorStatePath) {
        $alignment = Repair-StartupSupervisorState -ProjectRoot $ProjectRoot
        $results.SupervisorStateRepaired = $alignment.SupervisorStateCorrupt -or (
            $null -ne $alignment.SupervisorState -and
            $alignment.SupervisorLastTicketId -and
            $alignment.SupervisorLastTicketId -ne $alignment.WorkPlanId
        )
    }

    $builderLock = Repair-BuilderLockState -ProjectRoot $ProjectRoot -MaxAgeMinutes $BuilderLockTtlMinutes
    if ($null -eq $builderLock -and (Test-Path -LiteralPath (Join-Path $ProjectRoot '.agent\runtime\builder_lock.txt'))) {
        $results.BuilderLockRemoved = $true
    }

    # supervisor_lock.txt is a PID-based lock that becomes orphaned when the terminal
    # is closed without clean shutdown. Remove unconditionally on fresh launch so that
    # the supervisor's own acquire logic runs from a clean state.
    $supervisorLockPath = Join-Path $ProjectRoot '.agent\runtime\supervisor_lock.txt'
    if (Test-Path -LiteralPath $supervisorLockPath) {
        Remove-Item -LiteralPath $supervisorLockPath -Force -ErrorAction SilentlyContinue
        $results.SupervisorLockRemoved = $true
    }

    $tempDir = [System.IO.Path]::GetTempPath()
    $cutoff = [DateTime]::UtcNow.AddMinutes(-$PromptTtlMinutes)
    Get-ChildItem -Path $tempDir -Filter 'manager_prompt_*.md' -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.LastWriteTimeUtc -lt $cutoff) {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
            $results.ManagerPromptRemoved += 1
        }
    }

    return [pscustomobject]$results
}

function Get-ActiveRole {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $helperPath = Join-Path $script:_MotorCodeRoot 'scripts\get_launcher_state.py'
    if (Test-Path -LiteralPath $helperPath) {
        $helperOutput = & $venvPython $helperPath --project-root $ProjectRoot 2>&1
        $helperExitCode = $LASTEXITCODE
        if ($helperExitCode -eq 0) {
            try {
                $launcherState = ($helperOutput | Out-String).Trim() | ConvertFrom-Json
                if ($null -ne $launcherState -and $launcherState.role) {
                    return [string]$launcherState.role
                }
            }
            catch {
                Write-Warning 'No se pudo parsear JSON de get_launcher_state.py. Recurriendo a TURN.md como fallback.'
            }
        }
        else {
            Write-Warning 'get_launcher_state.py fallo. Recurriendo a TURN.md como fallback.'
        }
    }

    $turnPath = Join-Path $ProjectRoot '.agent\collaboration\TURN.md'
    if (-not (Test-Path -LiteralPath $turnPath)) {
        Write-Warning 'TURN.md no encontrado. Asumiendo BUILDER para compatibilidad.'
        return 'BUILDER'
    }

    $content = Get-Content -LiteralPath $turnPath -Raw
    if ($content -match '\*\*ROL\*\*\s*\|\s*\*\*(\w+)\*\*') {
        return $matches[1]
    }

    Write-Warning 'No se pudo parsear ROL de TURN.md. Asumiendo BUILDER para compatibilidad.'
    return 'BUILDER'
}

function Get-StartupAlignment {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $workPlanPath = Join-Path $ProjectRoot '.agent\collaboration\work_plan.md'
    $turnPath = Join-Path $ProjectRoot '.agent\collaboration\TURN.md'
    $statePath = Join-Path $ProjectRoot '.agent\collaboration\STATE.md'
    $bridgeStatePath = Join-Path $ProjectRoot '.agent\runtime\manager_bridge_state.json'

    $workPlanContent = Get-Content -LiteralPath $workPlanPath -Raw
    $turnContent = Get-Content -LiteralPath $turnPath -Raw
    $stateContent = Get-Content -LiteralPath $statePath -Raw

    $planIdPattern = '(?:WP|WT)-\d{4}-[A-Za-z0-9]+'
    $workPlanId = Get-PlanIdFromWorkPlanContent -Content $workPlanContent
    $turnPlanId = Get-OptionalPlanIdFromTurnContent -Content $turnContent
    if ($null -eq $turnPlanId) {
        $turnPlanId = $workPlanId
    }
    $statePlanId = Get-PlanIdFromStateContent -Content $stateContent
    $activeRole = Get-ActiveRole -ProjectRoot $ProjectRoot

    $bridgeState = $null
    $bridgeStateCorrupt = $false
    if (Test-Path -LiteralPath $bridgeStatePath) {
        try {
            $bridgeState = Get-Content -LiteralPath $bridgeStatePath -Raw | ConvertFrom-Json
        }
        catch {
            Write-Warning 'manager_bridge_state.json esta corrupto o vacio; se regenerara en el siguiente arranque.'
            $bridgeStateCorrupt = $true
        }
    }

    return [pscustomobject]@{
        WorkPlanId = $workPlanId
        TurnPlanId = $turnPlanId
        StatePlanId = $statePlanId
        ActiveRole = $activeRole
        BridgeStatePath = $bridgeStatePath
        BridgeLastTicketId = Get-OptionalPropertyValue -Object $bridgeState -Names @('last_ticket_id', 'ticket_id', 'active_ticket')
        BridgeState = $bridgeState
        BridgeStateCorrupt = $bridgeStateCorrupt
    }
}

function Repair-StartupBridgeState {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $alignment = Get-StartupAlignment -ProjectRoot $ProjectRoot
    if ($alignment.BridgeStateCorrupt) {
        Remove-Item -LiteralPath $alignment.BridgeStatePath -Force -ErrorAction SilentlyContinue
    }
    elseif ($null -ne $alignment.BridgeState -and $alignment.BridgeLastTicketId -and $alignment.BridgeLastTicketId -ne $alignment.WorkPlanId) {
        Write-Warning "manager_bridge_state.json apunta a $($alignment.BridgeLastTicketId) y el ticket activo es $($alignment.WorkPlanId). Se limpiara para evitar arrastrar estado viejo."
        Remove-Item -LiteralPath $alignment.BridgeStatePath -Force -ErrorAction SilentlyContinue
    }

    return $alignment
}

function Get-SupervisorStateAlignment {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $supervisorStatePath = Join-Path $ProjectRoot '.agent\runtime\supervisor_state.json'
    $supervisorState = $null
    $supervisorStateCorrupt = $false
    if (Test-Path -LiteralPath $supervisorStatePath) {
        try {
            $supervisorState = Get-Content -LiteralPath $supervisorStatePath -Raw | ConvertFrom-Json
        }
        catch {
            Write-Warning 'supervisor_state.json esta corrupto o vacio; se regenerara en el siguiente arranque.'
            $supervisorStateCorrupt = $true
        }
    }

    return [pscustomobject]@{
        SupervisorStatePath = $supervisorStatePath
        SupervisorState = $supervisorState
        SupervisorLastTicketId = Get-OptionalPropertyValue -Object $supervisorState -Names @('active_ticket', 'ticket_id')
        SupervisorStateCorrupt = $supervisorStateCorrupt
    }
}

function Repair-StartupSupervisorState {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $alignment = Get-StartupAlignment -ProjectRoot $ProjectRoot
    $supervisorAlignment = Get-SupervisorStateAlignment -ProjectRoot $ProjectRoot

    if ($supervisorAlignment.SupervisorStateCorrupt) {
        Remove-Item -LiteralPath $supervisorAlignment.SupervisorStatePath -Force -ErrorAction SilentlyContinue
    }
    elseif ($null -ne $supervisorAlignment.SupervisorState -and $supervisorAlignment.SupervisorLastTicketId -and $supervisorAlignment.SupervisorLastTicketId -ne $alignment.WorkPlanId) {
        Write-Warning "supervisor_state.json apunta a $($supervisorAlignment.SupervisorLastTicketId) y el ticket activo es $($alignment.WorkPlanId). Se limpiara para evitar arrastrar estado viejo."
        Remove-Item -LiteralPath $supervisorAlignment.SupervisorStatePath -Force -ErrorAction SilentlyContinue
    }

    $alignment | Add-Member -NotePropertyName SupervisorStatePath -NotePropertyValue $supervisorAlignment.SupervisorStatePath -Force
    $alignment | Add-Member -NotePropertyName SupervisorState -NotePropertyValue $supervisorAlignment.SupervisorState -Force
    $alignment | Add-Member -NotePropertyName SupervisorLastTicketId -NotePropertyValue $supervisorAlignment.SupervisorLastTicketId -Force
    $alignment | Add-Member -NotePropertyName SupervisorStateCorrupt -NotePropertyValue $supervisorAlignment.SupervisorStateCorrupt -Force
    return $alignment
}

function Wait-SupervisorExit {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [int]$TimeoutSeconds = 30
    )

    $supervisorLockPath = Join-Path $ProjectRoot '.agent\runtime\supervisor_lock.txt'
    $startTime = Get-Date

    Write-Host "[launcher] Waiting for supervisor lock to be released..."

    while ($true) {
        if (-not (Test-Path -LiteralPath $supervisorLockPath)) {
            Write-Host "[launcher] Supervisor lock released successfully"
            return $true
        }

        $elapsed = (Get-Date) - $startTime
        if ($elapsed.TotalSeconds -gt $TimeoutSeconds) {
            Write-Error "[launcher] Timeout waiting for supervisor exit (${TimeoutSeconds}s). Lock still present: $supervisorLockPath"
            return $false
        }

        Start-Sleep -Milliseconds 500
    }
}

function Assert-StartupAlignment {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $alignment = Repair-StartupBridgeState -ProjectRoot $ProjectRoot
    $alignment = Repair-StartupSupervisorState -ProjectRoot $ProjectRoot
    $issues = @()

    if ($alignment.WorkPlanId -ne $alignment.TurnPlanId) {
        $issues += "work_plan.md ($($alignment.WorkPlanId)) != TURN.md ($($alignment.TurnPlanId))"
    }

    if ($alignment.WorkPlanId -ne $alignment.StatePlanId) {
        $issues += "work_plan.md ($($alignment.WorkPlanId)) != STATE.md ($($alignment.StatePlanId))"
    }

    if ($issues.Count -gt 0) {
        throw "Alineacion inicial invalida:`n- " + ($issues -join "`n- ")
    }

    return $alignment
}

function Invoke-PreflightReconcile {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [Parameter(Mandatory)] [object]$Alignment
    )

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $helperPath = Join-Path $script:_MotorCodeRoot 'scripts\preflight_reconcile.py'

    if (-not (Test-Path -LiteralPath $helperPath)) {
        Write-Host "[preflight-reconcile] Helper no encontrado en $helperPath; se omite la comprobacion."
        return $null
    }

    Write-Host "[preflight-reconcile] Evaluando drift para $($Alignment.WorkPlanId)..."
    $output = & $venvPython $helperPath --project-root $ProjectRoot --work-plan-id $Alignment.WorkPlanId 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = ($output | Out-String).Trim()

    if ($exitCode -eq 0) {
        # Parse JSON decision for ALIGNED / CLEANUP_LOCAL / RECONCILE
        try {
            $decision = $outputText | ConvertFrom-Json
        } catch {
            Write-Warning "[preflight-reconcile] No se pudo parsear la salida JSON; se omite la comprobacion."
            return $null
        }

        Write-Host "[preflight-reconcile] Decision=$($decision.decision) prev=$($decision.prev_ticket_id) state=$($decision.prev_ticket_state)"

        if ($decision.decision -eq 'RECONCILE') {
            $reconcilerPath = Join-Path $script:_MotorCodeRoot 'scripts\reconcile_ticket.py'
            Write-Host "[preflight-reconcile] El ticket anterior $($decision.prev_ticket_id) no es terminal. Ejecutando reconciliacion..."
            & $venvPython $reconcilerPath --project-root $ProjectRoot --ticket $decision.prev_ticket_id --reason 'preflight forced close' --json 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "La reconciliacion fallo para $($decision.prev_ticket_id). Vease la salida del reconciler arriba."
            }
            Write-Host "[preflight-reconcile] Reconciliacion completada para $($decision.prev_ticket_id)"
        } elseif ($decision.decision -eq 'CLEANUP_LOCAL') {
            Write-Host "[preflight-reconcile] Ticket anterior ya terminal; solo limpieza local."
        } elseif ($decision.decision -eq 'ALIGNED') {
            Write-Host "[preflight-reconcile] Sin drift; procediendo normalmente."
        }
        return $decision
    } elseif ($exitCode -eq 2) {
        # ABORT decision
        $reason = "El bus es ilegible o contradictorio"
        try {
            $abortDecision = $outputText | ConvertFrom-Json
            if ($abortDecision.reason) { $reason = $abortDecision.reason }
        } catch {}
        throw "Preflight reconcile ABORT: $reason"
    } else {
        Write-Warning "[preflight-reconcile] El helper fallo con codigo $exitCode. Se omite la comprobacion."
    }

    return $null
}

function Invoke-PostPreflightProjectionSync {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $supervisorPath = Join-Path $script:_MotorCodeRoot 'scripts\ticket_supervisor.py'

    if (-not (Test-Path -LiteralPath $supervisorPath)) {
        Write-Warning "[preflight-reconcile] ticket_supervisor.py no encontrado en $supervisorPath; se omite la reproyeccion canonica."
        return
    }

    Write-Host "[preflight-reconcile] Reproyectando estado canonico tras reconciliacion..."
    $previousProjectRoot = [System.Environment]::GetEnvironmentVariable('AGENT_PROJECT_ROOT', 'Process')
    try {
        [System.Environment]::SetEnvironmentVariable('AGENT_PROJECT_ROOT', $ProjectRoot, 'Process')
        & $venvPython $supervisorPath --once --no-auto-sync 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "ticket_supervisor.py --once fallo al reproyectar estado canonico."
        }
    }
    finally {
        if ($null -ne $previousProjectRoot) {
            [System.Environment]::SetEnvironmentVariable('AGENT_PROJECT_ROOT', $previousProjectRoot, 'Process')
        }
        else {
            [System.Environment]::SetEnvironmentVariable('AGENT_PROJECT_ROOT', $null, 'Process')
        }
    }
}

function Invoke-ImportPreflight {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [string]$MotorRoot = ""
    )

    # WP-2026-118: Preflight ligero de imports criticos antes de abrir ventanas.
    # Solo valida que los modulos del bus y agent_controller importen sin error.
    # No ejecuta gates pesadas (ruff/pytest) en el arranque.
    # WP-2026-176: Con workspace externo, el codigo del motor esta en MotorRoot,
    # no en ProjectRoot. Se usa MotorRoot para imports y venv cuando esta disponible.

    $codeRoot = if ($MotorRoot -ne "" -and (Test-Path -LiteralPath $MotorRoot)) { $MotorRoot } else { $ProjectRoot }
    $venvPython = Resolve-VenvPython -Root $codeRoot
    $criticalModules = @(
        'bus.event_bus',
        'bus.review_bridge',
        'agent_controller'
    )

    $failedImports = @()
    foreach ($module in $criticalModules) {
        $result = & $venvPython -c "import sys; sys.path.insert(0, r'$codeRoot\.agent'); sys.path.insert(0, r'$codeRoot'); __import__('$module')" 2>&1
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne 0) {
            $failedImports += $module
            Write-Warning "Import fallido: $module"
        }
    }

    if ($failedImports.Count -gt 0) {
        $errorMsg = "Preflight de imports fallido. Modulos criticos con error:`n"
        foreach ($mod in $failedImports) {
            $errorMsg += "  - $mod`n"
        }
        $errorMsg += "`nEl launcher aborta para evitar abrir ventanas con el bus roto."
        throw $errorMsg
    }

    Write-Host "Preflight de imports: OK (bus.event_bus, bus.review_bridge, agent_controller)"
}

function Is-BuilderRunningInProject {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    return $null -ne (Repair-BuilderLockState -ProjectRoot $ProjectRoot)
}

function Stop-ProjectAgentProcesses {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    $normalizedRoot = [regex]::Escape((Resolve-Path -LiteralPath $ProjectRoot).Path)
    $staleProcessPatterns = @(
        'ticket_supervisor\.py',
        'manager_review_bridge\.py',
        'kilo\.exe\s+run\s+--auto',
        'builder_lock\.txt'
    )

    $staleProcesses = @()
    try {
        $staleProcesses = Get-CimInstance Win32_Process | Where-Object {
            $commandLine = $_.CommandLine
            $null -ne $commandLine -and
            $_.ProcessId -ne $PID -and
            ($commandLine -match $normalizedRoot) -and
            (($staleProcessPatterns | Where-Object { $commandLine -match $_ }) -ne $null)
        }
    }
    catch {
        Write-Warning "No se pudieron inspeccionar procesos viejos del proyecto; se continuara sin esa limpieza. Detalle: $($_.Exception.Message)"
        return
    }

    foreach ($process in $staleProcesses) {
        try {
            Write-Warning "Cerrando sesion vieja del proyecto: PID $($process.ProcessId) -> $($process.Name)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "No se pudo cerrar el proceso $($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Resolve-BackendExecutable {
    param(
        [Parameter(Mandatory)] [string]$BackendName,
        [string]$OverridePath
    )

    if (-not [string]::IsNullOrWhiteSpace($OverridePath)) {
        if (Test-Path -LiteralPath $OverridePath) {
            return $OverridePath
        }
        throw "No se encontro el ejecutable en la ruta indicada: $OverridePath"
    }

    # Get discovery method from config
    $discoveryMethod = Get-BackendDiscoveryMethod -BackendName $BackendName
    $executableName = Get-BackendExecutableName -BackendName $BackendName

    if ($discoveryMethod -eq 'vscode_extension') {
        $userProfile = [Environment]::GetFolderPath('UserProfile')
        $extensionRoot = Join-Path $userProfile '.vscode\extensions'
        if (Test-Path -LiteralPath $extensionRoot) {
            $extensionGlob = Get-BackendExtensionGlob -BackendName $BackendName
            $binaryName = Get-BackendBinaryName -BackendName $BackendName
            $extensionMatch = Get-ChildItem -Path $extensionRoot -Filter $extensionGlob -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -eq $binaryName } |
                Sort-Object FullName -Descending |
                Select-Object -First 1
            if ($null -ne $extensionMatch) {
                return $extensionMatch.FullName
            }
        }
    }

    # Fallback to PATH
    foreach ($candidate in @($executableName, "$executableName.exe")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw "No se encontro el ejecutable para el backend '$BackendName' en las extensiones de VS Code ni en PATH."
}

function Get-BackendFromConfig {
    param([Parameter(Mandatory)] [string]$Role)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $agentsConfigPath = Join-Path $script:_MotorCodeRoot '.agent\agents_config.py'

    try {
        $backend = & $venvPython $agentsConfigPath get_backend_for_role $Role 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Error al obtener backend para rol '$Role': $backend"
        }
        return $backend.Trim()
    }
    catch {
        throw "Error al leer configuracion de agentes: $($_.Exception.Message)"
    }
}

function Get-BackendExecutableName {
    param([Parameter(Mandatory)] [string]$BackendName)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $agentsConfigPath = Join-Path $script:_MotorCodeRoot '.agent\agents_config.py'

    try {
        $exe = & $venvPython $agentsConfigPath get_executable $BackendName 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Error al obtener ejecutable para backend '$BackendName': $exe"
        }
        return $exe.Trim()
    }
    catch {
        throw "Error al leer configuracion de agentes: $($_.Exception.Message)"
    }
}

function Get-BackendArgs {
    param([Parameter(Mandatory)] [string]$BackendName)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $agentsConfigPath = Join-Path $script:_MotorCodeRoot '.agent\agents_config.py'

    try {
        $args = & $venvPython $agentsConfigPath get_args $BackendName 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Error al obtener argumentos para backend '$BackendName': $args"
        }
        return $args.Trim()
    }
    catch {
        throw "Error al leer configuracion de agentes: $($_.Exception.Message)"
    }
}

function Get-BackendDiscoveryMethod {
    param([Parameter(Mandatory)] [string]$BackendName)

    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $agentsConfigPath = Join-Path $script:_MotorCodeRoot '.agent\agents_config.py'

    try {
        $method = & $venvPython $agentsConfigPath get_discovery $BackendName 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Error al obtener metodo de discovery para backend '$BackendName': $method"
        }
        return $method.Trim()
    }
    catch {
        throw "Error al leer configuracion de agentes: $($_.Exception.Message)"
    }
}

function Get-BackendExtensionGlob {
    param([Parameter(Mandatory)] [string]$BackendName)

    # Read extension_glob from config JSON directly for efficiency
    $configPath = Join-Path $ProjectRoot '.agent\config\agents.json'
    if (Test-Path -LiteralPath $configPath) {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $backend = $config.backends.$BackendName
        if ($null -ne $backend -and $null -ne $backend.discovery -and $null -ne $backend.discovery.extension_glob) {
            return $backend.discovery.extension_glob
        }
    }
    # Fallback: return executable-based glob from config or default wildcard
    return '*'
}

function Get-BackendBinaryName {
    param([Parameter(Mandatory)] [string]$BackendName)

    # Read binary_name from config JSON directly for efficiency
    $configPath = Join-Path $ProjectRoot '.agent\config\agents.json'
    if (Test-Path -LiteralPath $configPath) {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $backend = $config.backends.$BackendName
        if ($null -ne $backend -and $null -ne $backend.discovery -and $null -ne $backend.discovery.binary_name) {
            return $backend.discovery.binary_name
        }
    }
    # Fallback to executable name from config
    return Get-BackendExecutableName -BackendName $BackendName
}

function Get-OpenCodeBuilderPrompt {
    param(
        [Parameter(Mandatory)] [string]$TicketId,
        [Parameter(Mandatory)] [string]$ProjectRoot
    )

    # Composicion del prompt para OpenCode Builder
    # Incluye ticket_id real, recordatorio de Files Likely Touched y cierre obligatorio
    $prompt = @"
Actua como BUILDER para $TicketId.
Lee .agent/collaboration/TURN.md, .agent/collaboration/work_plan.md, .agent/collaboration/execution_log.md, .agent/collaboration/STATE.md y PROJECT.md.
Implementa solo $TicketId siguiendo .agent/collaboration/work_plan.md y los Files Likely Touched.
No cambies el alcance. No reescribas el plan.
Registra evidencia clara en .agent/collaboration/execution_log.md.
Mantente en el runtime bus-first y evita editar .agent/collaboration/TURN.md, .agent/collaboration/STATE.md o .agent/collaboration/execution_log.md a mano.
Ejecuta ruff y pytest-safe sobre lo tocado.

CIERRE OBLIGATORIO (dos pasos, en orden):
1. Ejecuta python .agent/agent_controller.py --pre-handoff para stagear, commitear y crear el checkpoint M3.
2. Ejecuta python .agent/agent_controller.py --mark-ready --json --force para emitir BUILDER_EXIT.
Usa --pre-handoff primero; --mark-ready sin el solo sera bloqueado por el guard.
"@
    return $prompt
}

function Get-CanonicalFilesForOpenCode {
    param([Parameter(Mandatory)] [string]$ProjectRoot)

    # Ficheros canonicos base que siempre se adjuntan.
    # Rutas absolutas desde $ProjectRoot: en Model B el workspace esta fuera del
    # motor; pasar rutas absolutas garantiza que OpenCode los embebe en el prompt
    # via -f sin necesidad de acceso de tool al directorio externo.
    $canonicalFiles = @(
        (Join-Path $ProjectRoot '.agent\collaboration\work_plan.md'),
        (Join-Path $ProjectRoot '.agent\collaboration\TURN.md'),
        (Join-Path $ProjectRoot '.agent\collaboration\execution_log.md'),
        (Join-Path $ProjectRoot '.agent\collaboration\STATE.md')
    )

    # Verificar si existen PLAN_<ticket>.md y AUDIT_<ticket>.md
    $ticketId = $null
    $workPlanPath = Join-Path $ProjectRoot '.agent\collaboration\work_plan.md'
    if (Test-Path -LiteralPath $workPlanPath) {
        $workPlanContent = Get-Content -LiteralPath $workPlanPath -Raw
        try {
            $ticketId = Get-PlanIdFromWorkPlanContent -Content $workPlanContent
        }
        catch {
            # Si no se puede extraer el ticket, continuamos sin los archivos extra
        }
    }

    if ($ticketId) {
        $planPath = Join-Path $ProjectRoot ".agent\collaboration\PLAN_$ticketId.md"
        $auditPath = Join-Path $ProjectRoot ".agent\collaboration\AUDIT_$ticketId.md"
        $feedbackPath = Join-Path $ProjectRoot ".agent\collaboration\manager_feedback_$ticketId.md"

        if (Test-Path -LiteralPath $planPath) {
            $canonicalFiles += $planPath
        }
        if (Test-Path -LiteralPath $auditPath) {
            $canonicalFiles += $auditPath
        }
        # WP-2026-156: Adjuntar feedback normalizado si existe (requeue tras CHANGES)
        if (Test-Path -LiteralPath $feedbackPath) {
            $canonicalFiles += $feedbackPath
            Write-Host "Feedback normalizado detectado: $feedbackPath"
        }
    }

    # WT-2026-182: Repomix context bootstrapping (X-ray vision)
    # Generates compressed project context using repomix for agent session bootstrap.
    # This is a best-effort step: if repomix fails or times out, the session
    # continues with the standard canonical files only.
    $repomixOutputPath = Join-Path $ProjectRoot '.agent\context\repomix.xml'
    $repomixDir = Split-Path -Parent $repomixOutputPath
    if (-not (Test-Path -LiteralPath $repomixDir)) {
        New-Item -ItemType Directory -Path $repomixDir -Force -ErrorAction SilentlyContinue | Out-Null
    }

    # Check if repomix config exists in workspace root
    $repomixConfigPath = Join-Path $ProjectRoot 'repomix.config.json'
    $configArg = if (Test-Path -LiteralPath $repomixConfigPath) { "--config $(ConvertTo-SingleQuotedLiteral $repomixConfigPath)" } else { "" }

    # Run repomix with 15s timeout via background job to avoid blocking the launcher
    $repomixJob = Start-Job -ScriptBlock {
        param($OutPath, $ConfigArg)
        $result = & npx -y repomix --style xml --compress --output $OutPath $ConfigArg 2>&1
        return $result
    } -ArgumentList $repomixOutputPath, $configArg

    $repomixCompleted = $repomixJob | Wait-Job -Timeout 15
    if ($null -eq $repomixCompleted) {
        # Timeout: stop the job and continue without repomix
        $repomixJob | Stop-Job -ErrorAction SilentlyContinue | Out-Null
        Write-Warning "[repomix] Timed out after 15s; skipping context injection"
    } else {
        $null = $repomixJob | Receive-Job -ErrorAction SilentlyContinue
        $repomixJob | Remove-Job -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $repomixOutputPath) {
            $canonicalFiles += $repomixOutputPath
            Write-Host "[repomix] Context generated: $repomixOutputPath"
        } else {
            Write-Warning "[repomix] Failed to generate context; continuing without repomix"
        }
    }

    return $canonicalFiles
}

function Resolve-KiloExecutable {
    return Resolve-BackendExecutable -BackendName 'kilo' -OverridePath ''
}

function Get-TemplateContent {
    param([Parameter(Mandatory)] [string]$ProjectRoot, [Parameter(Mandatory)] [string]$TemplateName)

    $templatePath = Join-Path $ProjectRoot "templates/startup/$TemplateName.md"
    if (-not (Test-Path -LiteralPath $templatePath)) {
        throw "Plantilla no encontrada: $templatePath"
    }
    return Get-Content -LiteralPath $templatePath -Raw
}

function Fill-TemplateVariables {
    param(
        [Parameter(Mandatory)] [string]$TemplateContent,
        [Parameter(Mandatory)] [string]$TicketId,
        [Parameter(Mandatory)] [string]$WorkPlan,
        [string]$CloseCommand = "",
        [Parameter(Mandatory)] [string]$Role,
        [Parameter(Mandatory)] [string]$Backend
    )

    $filled = $TemplateContent
    $filled = $filled -replace '\{\{ticket_id\}\}', $TicketId
    $filled = $filled -replace '\{\{work_plan\}\}', $WorkPlan
    $filled = $filled -replace '\{\{close_command\}\}', $CloseCommand
    $filled = $filled -replace '\{\{role\}\}', $Role
    $filled = $filled -replace '\{\{backend\}\}', $Backend
    return $filled
}


function Add-BuilderCloseout {
    param(
        [Parameter(Mandatory)] [string]$RunnerCommand,
        [Parameter(Mandatory)] [string]$PreHandoffCommand,
        [Parameter(Mandatory)] [string]$MarkReadyCommand
    )
    # Wrap the Builder runner in try/finally so --pre-handoff and --mark-ready
    # execute even when the runner crashes or is killed (e.g. spawn-setup-refresh).
    # The evidence gate in --mark-ready is the safety net: if there is no real
    # implementation it rejects the call and the supervisor requeues normally.
    # The Builder terminal uses the default ErrorActionPreference=Continue, so
    # a non-zero exit from --pre-handoff does not suppress --mark-ready.
    # Each step is logged individually so the terminal shows exactly which step
    # failed - 'closeout done' is only printed on full success.
    return @"
try { $RunnerCommand } finally {
    Write-Host '[Builder] runner exited - starting closeout'
    Write-Host '[Builder] pre-handoff starting...'
    $PreHandoffCommand
    `$_ph = `$LASTEXITCODE
    if (`$_ph -eq 0) { Write-Host '[Builder] pre-handoff OK' } else { Write-Host ('[Builder] pre-handoff FAILED code ' + `$_ph) }
    Write-Host '[Builder] mark-ready starting...'
    $MarkReadyCommand
    `$_mr = `$LASTEXITCODE
    if (`$_mr -eq 0) { Write-Host '[Builder] mark-ready OK - ticket submitted for review' } else { Write-Host ('[Builder] mark-ready FAILED code ' + `$_mr + ' - supervisor will requeue') }
    if (`$_ph -eq 0 -and `$_mr -eq 0) { Write-Host '[Builder] closeout done' } else { Write-Host '[Builder] closeout completed with errors - check output above' }
}
"@
}


function Start-AgentWindow {
    param(
        [Parameter(Mandatory)] [string]$Title,
        [Parameter(Mandatory)] [string]$Command
    )

    $shellExecutable = Resolve-HostShellExecutable
    $payload = "Set-Location -LiteralPath $(ConvertTo-SingleQuotedLiteral $ProjectRoot); $Command"

    return Start-Process -PassThru -FilePath $shellExecutable -WorkingDirectory $ProjectRoot -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy', 'Bypass',
        '-Command',
        $payload
    )
}

if (-not $ResumeBuilder) {
    $ProjectRoot = Assert-CanonicalProjectRoot -ProjectRoot $ProjectRoot
    Stop-ProjectAgentProcesses -ProjectRoot $ProjectRoot
    Write-Host 'Limpieza previa: sesiones viejas del proyecto cerradas antes del nuevo arranque'

    # WT-2026-214: Preflight reconcile — detect drift between runtime and bus,
    # decide between cleanup-local and canonical reconcile BEFORE destructive
    # repair operations. This must happen before Assert-StartupAlignment or
    # Repair-StartupSupervisorState delete the stale state evidence.
    $preAlignment = Get-StartupAlignment -ProjectRoot $ProjectRoot
    $preflightDecision = Invoke-PreflightReconcile -ProjectRoot $ProjectRoot -Alignment $preAlignment
    if ($null -ne $preflightDecision -and @('RECONCILE', 'CLEANUP_LOCAL') -contains $preflightDecision.decision) {
        Invoke-PostPreflightProjectionSync -ProjectRoot $ProjectRoot
    }

    if ($StrictLaunch) {
        $alignment = Assert-StartupAlignment -ProjectRoot $ProjectRoot
        Write-Host "Preflight estricto: alineacion validada para $($alignment.WorkPlanId)"
    }
    else {
        $alignment = Repair-StartupSupervisorState -ProjectRoot $ProjectRoot
        Write-Host "Preflight flexible: alineacion reparada para $($alignment.WorkPlanId) | bridge_reparado=$($alignment.BridgeStateCorrupt -or ($null -ne $alignment.BridgeState -and $alignment.BridgeLastTicketId -and $alignment.BridgeLastTicketId -ne $alignment.WorkPlanId)) | supervisor_reparado=$($alignment.SupervisorStateCorrupt -or ($null -ne $alignment.SupervisorState -and $alignment.SupervisorLastTicketId -and $alignment.SupervisorLastTicketId -ne $alignment.WorkPlanId))"
    }

    $artifactCleanup = Remove-StaleRuntimeArtifacts -ProjectRoot $ProjectRoot
    if ($artifactCleanup.BuilderLockRemoved -or $artifactCleanup.SupervisorLockRemoved -or $artifactCleanup.ManagerPromptRemoved -gt 0 -or $artifactCleanup.BridgeStateRepaired -or $artifactCleanup.SupervisorStateRepaired) {
        Write-Host "Limpieza de runtime: builder_lock=$($artifactCleanup.BuilderLockRemoved), supervisor_lock=$($artifactCleanup.SupervisorLockRemoved), prompts=$($artifactCleanup.ManagerPromptRemoved), bridge_state_reparado=$($artifactCleanup.BridgeStateRepaired), supervisor_state_reparado=$($artifactCleanup.SupervisorStateRepaired)"
    }

    # WP-2026-118: Preflight de imports criticos antes de abrir ventanas
    $preflightScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
    $preflightMotorRoot = (Resolve-Path (Join-Path $preflightScriptDir '..')).Path
    Invoke-ImportPreflight -ProjectRoot $ProjectRoot -MotorRoot $preflightMotorRoot
} else {
    # WP-2026-160: -ResumeBuilder debe garantizar un supervisor fresco
    Write-Host "[launcher] Resume mode: waiting for stale supervisor exit..."
    $ProjectRoot = Assert-CanonicalProjectRoot -ProjectRoot $ProjectRoot

    # WP-2026-160: Esperar a que el supervisor viejo libere el lock.
    # -SkipSupervisorWait se pasa cuando el relanzado es interno (llamado desde el
    # propio supervisor via _relaunch_builder): el lock sigue activo porque el
    # supervisor aun no ha salido, por lo que esperar causaria un deadlock.
    $supervisorLockPath = Join-Path $ProjectRoot '.agent\runtime\supervisor_lock.txt'
    if ($SkipSupervisorWait) {
        Write-Host "[launcher] SkipSupervisorWait: internal requeue relaunch, skipping Wait-SupervisorExit"
    } elseif (Test-Path -LiteralPath $supervisorLockPath) {
        $waitResult = Wait-SupervisorExit -ProjectRoot $ProjectRoot -TimeoutSeconds 30
        if (-not $waitResult) {
            # Timeout: el supervisor viejo no salio limpiamente
            Write-Error "[launcher] Cannot guarantee fresh supervisor: stale supervisor did not exit within timeout"
            exit 1
        }
    } else {
        Write-Host "[launcher] No stale supervisor lock found; proceeding with fresh start"
    }

    # Resume path still needs alignment metadata (ticket id, active role) to
    # spawn Builder against the right ticket. Use the pure read function
    # (no repair, no cleanup) so $alignment is defined downstream.
    $alignment = Get-StartupAlignment -ProjectRoot $ProjectRoot

    # WP-2026-160: Ahora el launcher arranca un supervisor fresco antes de Builder
    # usando el mismo patron de arranque normal. Solo Supervisor + Builder en requeue.
    # WT-2026-200: -OnlyBuilder manda sobre la politica de supervisor: si esta activo,
    # no se arranca supervisor fresco incluso en resume. La asignacion truthy/falsey
    # funciona correctamente bajo if ($LaunchSupervisor).
    $LaunchSupervisor = -not $OnlyBuilder
    $LaunchBridge = $false
    $LaunchMonitor = $false
    $LaunchWatcher = $false
    # WP-2026-160: Signal the fresh supervisor to emit SUPERVISOR_RESTARTED at startup
    $env:SUPERVISOR_RESTART_REASON = "resume-builder"
    Write-Host "[launcher] Will launch fresh supervisor before Builder"
}

# Leer work_plan.md para {{work_plan}}
$workPlanPath = Join-Path $ProjectRoot '.agent\collaboration\work_plan.md'
$workPlanContent = Get-Content -LiteralPath $workPlanPath -Raw

# Variables comunes
$ticketId = $alignment.WorkPlanId
$role = $alignment.ActiveRole
# Get backend from centralized config instead of hardcoding
$backend = Get-BackendFromConfig -Role $role

# WP-2026-176: Resolve motor root for external controller support.
# Derive from script location first (the launcher lives in the motor repo),
# then override from workspace's motor_destination_link.json if present.
$launcherScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
$resolvedMotorRoot = (Resolve-Path (Join-Path $launcherScriptDir '..')).Path
$workspaceMotorLink = Join-Path $ProjectRoot '.agent\config\motor_destination_link.json'
if (Test-Path -LiteralPath $workspaceMotorLink) {
    try {
        $link = Get-Content -LiteralPath $workspaceMotorLink -Raw | ConvertFrom-Json
        if ($null -ne $link.motor_root -and (Test-Path -LiteralPath $link.motor_root)) {
            $resolvedMotorRoot = (Resolve-Path -LiteralPath $link.motor_root).Path
        }
    }
    catch {
        Write-Warning "motor_destination_link.json in workspace not readable; using default motor root"
    }
}
# If motor root differs from ProjectRoot, use external controller with --project-root
$useExternalController = (Resolve-Path -LiteralPath $resolvedMotorRoot).Path -ne (Resolve-Path -LiteralPath $ProjectRoot).Path
if ($useExternalController) {
    $closePreHandoff = "python $resolvedMotorRoot\.agent\agent_controller.py --pre-handoff --project-root $ProjectRoot"
    $closeMarkReady  = "python $resolvedMotorRoot\.agent\agent_controller.py --mark-ready --json --force --project-root $ProjectRoot"
    $controllerPath  = Join-Path $resolvedMotorRoot '.agent\agent_controller.py'
    Write-Host "Motor controller externo: $controllerPath para workspace $ProjectRoot"
} else {
    $closePreHandoff = "python .agent/agent_controller.py --pre-handoff"
    $closeMarkReady  = "python .agent/agent_controller.py --mark-ready --json --force"
    $controllerPath  = Join-Path $script:_MotorCodeRoot '.agent\agent_controller.py'
}


# Bootstrap bus event for active ticket to prevent bridge UNKNOWN state
$venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
$bootstrapResult = & $venvPython $controllerPath --bootstrap-ticket --json --project-root $ProjectRoot 2>&1
$bootstrapExitCode = $LASTEXITCODE
$bootstrapResultText = ($bootstrapResult | Out-String).Trim()
Write-Host "Bus bootstrap: $bootstrapResultText"

if ($bootstrapExitCode -ne 0) {
    throw "Bus bootstrap failed with exit code ${bootstrapExitCode}: $bootstrapResultText"
}

try {
    $bootstrapJson = $bootstrapResultText | ConvertFrom-Json
} catch {
    throw "Bus bootstrap returned invalid JSON: $bootstrapResultText"
}

if ($bootstrapJson.PSObject.Properties['error']) {
    throw "Bus bootstrap error: $($bootstrapJson.error)"
}

if ($bootstrapJson.PSObject.Properties['status'] -and $bootstrapJson.status -eq 'skipped') {
    $skippedPlanId = if ($bootstrapJson.PSObject.Properties['plan_id']) { $bootstrapJson.plan_id } else { 'unknown' }
    $skippedReason = if ($bootstrapJson.PSObject.Properties['reason']) { $bootstrapJson.reason } else { 'no reason given' }
    throw "Bus bootstrap skipped for ${skippedPlanId}: $skippedReason"
}

if ($LaunchSupervisor) {
    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $venvPythonLiteral = ConvertTo-SingleQuotedLiteral $venvPython
    $supervisorScriptLiteral = ConvertTo-SingleQuotedLiteral (Join-Path $script:_MotorCodeRoot 'scripts\ticket_supervisor.py')
    # WP-2026-122: Export AGENT_PROJECT_ROOT for child processes
    $env:AGENT_PROJECT_ROOT = (Resolve-Path -LiteralPath $ProjectRoot).Path
    Start-AgentWindow -Title 'Supervisor' -Command "& $venvPythonLiteral $supervisorScriptLiteral --reactive"
    Write-Host "Supervisor: lanzado con ticket_supervisor.py --reactive"
}

if ($LaunchWatcher) {
    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $venvPythonLiteral = ConvertTo-SingleQuotedLiteral $venvPython
    $watcherPath = Join-Path $script:_MotorCodeRoot 'scripts\requeue_watcher.py'
    if (Test-Path -LiteralPath $watcherPath) {
        $watcherScriptLiteral = ConvertTo-SingleQuotedLiteral $watcherPath
        Start-AgentWindow -Title 'Requeue Watcher' -Command "& $venvPythonLiteral $watcherScriptLiteral --project-root . --poll-interval 5 --max-age 30"
        Write-Host "Requeue Watcher: lanzado para vigilar eventos de requeue"
    }
    else {
        Write-Host "Requeue Watcher: no lanzado - scripts\requeue_watcher.py no existe en este snapshot"
    }
}

if ($LaunchBridge) {
    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $venvPythonLiteral = ConvertTo-SingleQuotedLiteral $venvPython
    $bridgeScriptLiteral = ConvertTo-SingleQuotedLiteral (Join-Path $script:_MotorCodeRoot 'scripts\manager_review_bridge.py')
    # WP-2026-122: Export AGENT_PROJECT_ROOT for child processes
    $env:AGENT_PROJECT_ROOT = (Resolve-Path -LiteralPath $ProjectRoot).Path
    # Get Manager backend from config
    $managerBackend = Get-BackendFromConfig -Role 'MANAGER'
    $managerExe = Resolve-BackendExecutable -BackendName $managerBackend -OverridePath $ManagerBackendPath
    $managerExeLiteral = ConvertTo-SingleQuotedLiteral $managerExe
    $projectRootLiteral = ConvertTo-SingleQuotedLiteral $ProjectRoot
    Start-AgentWindow -Title 'Review Bridge' -Command "& $venvPythonLiteral $bridgeScriptLiteral --watch --backend-path $managerExeLiteral --project-root $projectRootLiteral"
    Write-Host "Review Bridge: lanzado"
}

if ($LaunchMonitor) {
    $venvPython = Resolve-VenvPython -Root $script:_MotorCodeRoot
    $venvPythonLiteral = ConvertTo-SingleQuotedLiteral $venvPython
    $monitorScriptLiteral = ConvertTo-SingleQuotedLiteral (Join-Path $script:_MotorCodeRoot 'scripts\ticket_activity_monitor.py')
    # WP-2026-122: Export AGENT_PROJECT_ROOT for child processes
    $env:AGENT_PROJECT_ROOT = (Resolve-Path -LiteralPath $ProjectRoot).Path
    Start-AgentWindow -Title 'Ticket Activity Monitor' -Command "& $venvPythonLiteral $monitorScriptLiteral"
    Write-Host "Ticket Activity Monitor: lanzado para el ticket activo"
}

if ($LaunchBuilder) {
    $activeRole = Get-ActiveRole -ProjectRoot $ProjectRoot
    $launchBuilderAnyway = -not [string]::IsNullOrWhiteSpace($BuilderPrompt)
    if ($activeRole -eq 'BUILDER' -or $launchBuilderAnyway) {
        $lockPath = Join-Path $ProjectRoot '.agent\runtime\builder_lock.txt'
        Remove-StaleLegacyLock -LockPath $lockPath -MaxAgeSeconds 300 | Out-Null
        if (-not (Is-BuilderRunningInProject -ProjectRoot $ProjectRoot)) {
            $builderProcess = $null
            # Get Builder backend from config (already set in $backend at line ~863)
            $builderBackend = $backend
            $builderExe = Resolve-BackendExecutable -BackendName $builderBackend -OverridePath ''
            $builderExeLiteral = ConvertTo-SingleQuotedLiteral $builderExe
            $currentRound = Get-CurrentBuilderRound -ProjectRoot $ProjectRoot
            $windowTitle = "BR$currentRound | $ticketId"

            # For opencode backend, use opencode run with composed prompt, model from config, and canonical files
            # For other backends, use template startup/{role}_{backend}.md
            if ($builderBackend -eq 'opencode') {
                # WP-2026-122: Export AGENT_PROJECT_ROOT for child processes
                $env:AGENT_PROJECT_ROOT = (Resolve-Path -LiteralPath $ProjectRoot).Path
                # Read model from .opencode/opencode.json config (lives in motor, not workspace)
                $opencodeConfigPath = Join-Path $script:_MotorCodeRoot '.opencode\opencode.json'
                if (-not (Test-Path -LiteralPath $opencodeConfigPath)) {
                    throw "OpenCode config not found: $opencodeConfigPath"
                }
                $opencodeConfig = Get-Content -LiteralPath $opencodeConfigPath -Raw | ConvertFrom-Json
                $model = $opencodeConfig.model
                if ([string]::IsNullOrWhiteSpace($model)) {
                    throw "OpenCode config does not specify a model."
                }

                # Compose prompt from active ticket
                $builderPrompt = Get-OpenCodeBuilderPrompt -TicketId $ticketId -ProjectRoot $ProjectRoot

                # Get canonical files to attach
                $canonicalFiles = Get-CanonicalFilesForOpenCode -ProjectRoot $ProjectRoot

                # Build opencode run command with proper single-quoted literals so that
                # the multi-word prompt and file paths survive the stringification into
                # Start-AgentWindow's -Command payload. Stringifying a PowerShell array
                # directly into "$arr" joins elements with spaces and destroys quoting,
                # which was the WP-2026-067 regression that prevented Builder startup.
                $promptLiteral = ConvertTo-SingleQuotedLiteral $builderPrompt
                $modelLiteral = ConvertTo-SingleQuotedLiteral $model
                # WP-2026-176: --dir must point to the motor so OpenCode can find
                # .opencode/agents/builder.md. The workspace (ProjectRoot) is passed
                # to the agent via AGENT_PROJECT_ROOT, not via --dir.
                $rootLiteral = ConvertTo-SingleQuotedLiteral $script:_MotorCodeRoot

                $fileFlags = @()
                foreach ($file in $canonicalFiles) {
                    $fileLiteral = ConvertTo-SingleQuotedLiteral $file
                    $fileFlags += "-f $fileLiteral"
                }
                $fileFlagsString = $fileFlags -join ' '

                # --port 0 makes opencode run spawn its own local server before executing.
                # Required since v1.15.x: without a running server the CLI fails with
                # "InstanceRef not provided" when launched from Start-Process (no TTY).
                # WP-2026-180: Inject deterministic --title for session ID capture on pre-handoff.
                $sessionTitle = "$ticketId-R$currentRound"
                $sessionTitleLiteral = ConvertTo-SingleQuotedLiteral $sessionTitle
                # WP-2026-180: On resume, read builder_session.json for session reuse.
                $sessionId = ""
                if ($ResumeBuilder) {
                    $sessionJsonPath = Join-Path $ProjectRoot '.agent\runtime\builder_session.json'
                    if (Test-Path -LiteralPath $sessionJsonPath) {
                        try {
                            $sessionData = Get-Content -LiteralPath $sessionJsonPath -Raw | ConvertFrom-Json
                            if ($sessionData.ticket_id -eq $ticketId -and -not [string]::IsNullOrWhiteSpace($sessionData.session_id)) {
                                $sessionId = $sessionData.session_id
                                Write-Host "[launcher] Reusing session $sessionId for $ticketId"
                            } else {
                                Write-Host "[launcher] builder_session.json found but ticket or session_id mismatch; falling back to clean session"
                            }
                        }
                        catch {
                            Write-Host "[launcher] builder_session.json corrupt; falling back to clean session"
                        }
                    }
                }
                $sessionFlag = if ($sessionId) { "--session $sessionId" } else { "" }
                $command = "& $builderExeLiteral run $promptLiteral --agent builder --model $modelLiteral --dir $rootLiteral --port 0 --title $sessionTitleLiteral $sessionFlag $fileFlagsString"
                $builderProcess = Start-AgentWindow -Title $windowTitle -Command (Add-BuilderCloseout $command $closePreHandoff $closeMarkReady)
                Write-Host "Builder: lanzado para rol $activeRole con backend OpenCode (opencode run con prompt compuesto)"
            }
            else {
                # Use template for other backends
                if ([string]::IsNullOrWhiteSpace($BuilderPrompt)) {
                    $templateName = "builder_$builderBackend"
                    $templateContent = Get-TemplateContent -ProjectRoot $ProjectRoot -TemplateName $templateName
                    $filledPrompt = Fill-TemplateVariables -TemplateContent $templateContent -TicketId $ticketId -WorkPlan $workPlanContent -Role $role -Backend $builderBackend
                    $builderPromptLiteral = ConvertTo-SingleQuotedLiteral $filledPrompt
                    $builderProcess = Start-AgentWindow -Title $windowTitle -Command (Add-BuilderCloseout "& $builderExeLiteral run --auto $builderPromptLiteral" $closePreHandoff $closeMarkReady)
                }
                else {
                    $builderPromptLiteral = ConvertTo-SingleQuotedLiteral $BuilderPrompt
                    $builderProcess = Start-AgentWindow -Title $windowTitle -Command (Add-BuilderCloseout "& $builderExeLiteral run --auto $builderPromptLiteral" $closePreHandoff $closeMarkReady)
                }
                Write-Host "Builder: lanzado para rol $activeRole con plantilla $templateName"
            }

            # WP-2026-117: Lock minimo sin PID - solo ticket_id + started_at como apoyo operativo
            $builderLockState = [ordered]@{
                ticket_id    = $ticketId
                project_root = (Resolve-Path -LiteralPath $ProjectRoot).Path
                started_at   = [DateTimeOffset]::UtcNow.ToString('o')
                role         = 'BUILDER'
                backend      = $backend
                round        = $currentRound
            }
            $builderLockState | ConvertTo-Json -Depth 4 | Out-File -LiteralPath $lockPath -Encoding UTF8
        }
        else {
            Write-Host 'Builder: no lanzado - ya esta ejecutandose en este proyecto'
        }
    }
    else {
        Write-Host "Builder: no lanzado - rol activo es $activeRole y no hay override manual"
    }
}

Write-Host "Arranque terminal-driven completado para $ProjectRoot"
