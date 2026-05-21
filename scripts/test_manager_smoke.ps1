# test_manager_smoke.ps1
# Smoke test del Manager (OpenCode/agente "manager") con varias estrategias
# de invocacion para diagnosticar el bug "INSPECT" del bridge.

$ErrorActionPreference = 'Continue'
$root = 'c:\Users\fdl\Proyectos_Python\z_scripts\orquestacion_agentes'
$model = 'openai/gpt-5.4-mini'
Set-Location $root

# Prompt de una linea para aislar problemas de parsing
$prompt1 = 'Smoke test. Responde solo con la linea siguiente, sin nada mas: DECISION: APPROVE'

function Invoke-OpencodeTest {
    param(
        [string]$Label,
        [string[]]$ArgList
    )
    Write-Host ""
    Write-Host "=============================================================" -ForegroundColor Cyan
    Write-Host "TEST: $Label" -ForegroundColor Cyan
    Write-Host "ARGS: $($ArgList -join ' | ')" -ForegroundColor DarkGray
    Write-Host "=============================================================" -ForegroundColor Cyan

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $stdout = & opencode.cmd @ArgList 2>&1 | Out-String
    $sw.Stop()
    $exit = $LASTEXITCODE

    Write-Host ("exit=$exit  duracion=$([int]$sw.Elapsed.TotalSeconds)s  out={0}b" -f $stdout.Length)
    Write-Host "--- OUTPUT (ultimas 25 lineas) ---" -ForegroundColor Yellow
    ($stdout -split "`n" | Select-Object -Last 25) -join "`n" | Write-Host

    $up = $stdout.ToUpper()
    if     ($up -match 'DECISION:\s*APPROVE') { $decision = 'APPROVE' }
    elseif ($up -match 'DECISION:\s*CHANGES') { $decision = 'CHANGES' }
    elseif ($up -match 'APPROVE')             { $decision = 'APPROVE (legacy)' }
    elseif ($up -match 'CHANGES')             { $decision = 'CHANGES (legacy)' }
    else                                       { $decision = 'INSPECT (no parseable)' }

    # Detectar que agente/modelo uso realmente
    $usedAgent = if ($up -match '>\s*MANAGER\s*') { 'manager' }
                 elseif ($up -match '>\s*BUILDER\s*') { 'builder (FALLBACK)' }
                 elseif ($up -match '>\s*([A-Z0-9_-]+)\s*[·.]') { $matches[1] }
                 else { '?' }
    $usedModel = if ($stdout -match '·\s*([A-Za-z0-9._\-/]+)') { $matches[1] } else { '?' }

    $color = if ($decision -like 'APPROVE*' -and $usedAgent -eq 'manager') { 'Green' }
             elseif ($usedAgent -like '*FALLBACK*') { 'Red' }
             else { 'Yellow' }
    Write-Host ""
    Write-Host "  Agente usado : $usedAgent" -ForegroundColor $color
    Write-Host "  Modelo usado : $usedModel" -ForegroundColor $color
    Write-Host "  Decision     : $decision" -ForegroundColor $color
    return [pscustomobject]@{
        Label=$Label; Agent=$usedAgent; Model=$usedModel; Decision=$decision; Exit=$exit
    }
}

$results = @()

# Test A: flags ANTES del prompt (orden recomendado por convenciones CLI)
$results += Invoke-OpencodeTest -Label 'A: flags antes del prompt' -ArgList @(
    'run', '--agent', 'manager', '--model', $model, '--dir', $root, $prompt1
)

# Test B: orden actual del bridge (prompt antes de los flags)
$results += Invoke-OpencodeTest -Label 'B: prompt antes de flags (como el bridge)' -ArgList @(
    'run', $prompt1, '--agent', 'manager', '--model', $model, '--dir', $root
)

# Test C: solo --agent, sin --model (a ver si --agent solo se respeta)
$results += Invoke-OpencodeTest -Label 'C: solo --agent, sin --model' -ArgList @(
    'run', '--agent', 'manager', '--dir', $root, $prompt1
)

# Test D: con --port 0 como hace el bridge
$results += Invoke-OpencodeTest -Label 'D: como el bridge con --port 0' -ArgList @(
    'run', '--agent', 'manager', '--model', $model, '--dir', $root, '--port', '0', $prompt1
)

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "RESUMEN" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
$results | Format-Table -AutoSize
