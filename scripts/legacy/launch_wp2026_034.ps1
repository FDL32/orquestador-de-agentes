# Script para arrancar WP-2026-034 en 3 ventanas (Supervisor, Review Bridge, Builder)
# Detecta procesos existentes y ofrece terminarlos
# Soporta modo no interactivo: usa --auto para terminar procesos automaticamente

param(
    [switch]$auto = $false
)

$root = "C:\Users\fdl\Proyectos_Python\z_scripts\orquestacion_agentes"
$codexExe = "C:\Users\fdl\.vscode\extensions\openai.chatgpt-26.506.31421-win32-x64\bin\windows-x86_64\codex.exe"
$kiloExe = "C:\Users\fdl\.vscode\extensions\kilocode.kilo-code-7.2.52-win32-x64\bin\kilo.exe"
$bridgeState = Join-Path $root ".agent\runtime\manager_bridge_state.json"

Write-Host "=== WP-2026-034 Launcher ===" -ForegroundColor Cyan
Write-Host ""

# 1. Detectar procesos existentes
Write-Host "[1/4] Detectando procesos existentes..." -ForegroundColor Yellow

$supervisorProcess = $null
$bridgeProcess = $null
$kiloProcess = Get-Process -Name "kilo" -ErrorAction SilentlyContinue

try {
    $supervisorProcess = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "ticket_supervisor.py" }
    $bridgeProcess = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "codex_review_bridge.py" }
} catch {
    # Ignore errors
}

$activeProcesses = @()
if ($supervisorProcess) { $activeProcesses += "Supervisor (PID: $($supervisorProcess.Id))" }
if ($bridgeProcess) { $activeProcesses += "Review Bridge (PID: $($bridgeProcess.Id))" }
if ($kiloProcess) { $activeProcesses += "Kilo Builder (PID: $($kiloProcess.Id))" }

if ($activeProcesses.Count -gt 0) {
    Write-Host "[!] Procesos activos detectados:" -ForegroundColor Red
    $activeProcesses | ForEach-Object { Write-Host "    - $_" }
    Write-Host ""

    if ($auto) {
        Write-Host "[AUTO] Terminando procesos automaticamente..." -ForegroundColor Yellow
        $shouldTerminate = $true
    } else {
        # Si estamos en modo interactivo, pedir confirmacion
        Write-Host "Ejecuta con -auto para terminar automaticamente." -ForegroundColor Cyan
        exit 0
    }

    if ($shouldTerminate) {
        if ($supervisorProcess) { Stop-Process -Id $supervisorProcess.Id -Force -ErrorAction SilentlyContinue; Write-Host "[OK] Supervisor terminado" }
        if ($bridgeProcess) { Stop-Process -Id $bridgeProcess.Id -Force -ErrorAction SilentlyContinue; Write-Host "[OK] Review Bridge terminado" }
        if ($kiloProcess) { Stop-Process -Id $kiloProcess.Id -Force -ErrorAction SilentlyContinue; Write-Host "[OK] Kilo Builder terminado" }
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "[OK] No hay procesos activos. Arranque limpio." -ForegroundColor Green
}

Write-Host ""

# 2. Limpiar estado anterior
Write-Host "[2/4] Limpiando estado anterior..." -ForegroundColor Yellow
if (Test-Path $bridgeState) {
    Remove-Item -LiteralPath $bridgeState -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] manager_bridge_state.json removido"
}

Write-Host ""

# 3. Validar archivos clave
Write-Host "[3/4] Validando archivos clave..." -ForegroundColor Yellow
$requiredFiles = @(
    ".agent\collaboration\work_plan.md",
    ".agent\collaboration\execution_log.md",
    ".agent\collaboration\TURN.md",
    ".agent\collaboration\STATE.md"
)

$missingFiles = @()
$requiredFiles | ForEach-Object {
    $path = Join-Path $root $_
    if (-not (Test-Path $path)) {
        $missingFiles += $_
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host "[!] Archivos faltantes:" -ForegroundColor Red
    $missingFiles | ForEach-Object { Write-Host "    - $_" }
    if ($auto) {
        Write-Host "[AUTO] Continuando a pesar de archivos faltantes..." -ForegroundColor Yellow
    } else {
        Write-Host "Ejecuta con -auto para continuar a pesar de los archivos faltantes." -ForegroundColor Cyan
        exit 1
    }
} else {
    Write-Host "[OK] Todos los archivos clave presentes" -ForegroundColor Green
}

Write-Host ""

# 4. Arrancar 3 ventanas
Write-Host "[4/4] Arrancando 3 ventanas..." -ForegroundColor Yellow
Write-Host ""

Write-Host "[->] Supervisor (ticket_supervisor.py --reactive)" -ForegroundColor Cyan
Start-Process powershell.exe -WorkingDirectory $root -ArgumentList @(
    "-NoExit",
    "-Command",
    "python scripts\ticket_supervisor.py --reactive"
)

Start-Sleep -Milliseconds 500

Write-Host "[->] Review Bridge (codex_review_bridge.py --watch)" -ForegroundColor Cyan
Start-Process powershell.exe -WorkingDirectory $root -ArgumentList @(
    "-NoExit",
    "-Command",
    "python scripts\codex_review_bridge.py --watch --codex-path `"$codexExe`""
)

Start-Sleep -Milliseconds 500

Write-Host "[->] Builder (Interactive - controlado por Supervisor)" -ForegroundColor Cyan
Start-Process powershell.exe -WorkingDirectory $root -ArgumentList @(
    "-NoExit",
    "-Command",
    "Write-Host 'BUILDER SHELL para WP-2026-034' -ForegroundColor Green; Write-Host 'El Supervisor controla este flujo automaticamente.' -ForegroundColor Yellow; Write-Host 'Espera instrucciones del Supervisor o del Manager...' -ForegroundColor Gray; Write-Host ''"
)

Write-Host ""
Write-Host "[OK] 3 ventanas arrancadas:" -ForegroundColor Green
Write-Host "     1. Supervisor"
Write-Host "     2. Review Bridge"
Write-Host "     3. Builder (Kilo)"
Write-Host ""
Write-Host "CICLO:" -ForegroundColor Cyan
Write-Host "     Builder -> READY_FOR_REVIEW -> Manager revisa -> aprueba/rechaza -> (repeat)"
Write-Host ""
Write-Host "[*] Monitorea en las 3 ventanas." -ForegroundColor Yellow
