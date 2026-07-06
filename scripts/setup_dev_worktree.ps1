<#
.SYNOPSIS
    Crea (o desmonta) la worktree de desarrollo del motor,
    `orquestador_de_agentes_dev`, dejando el checkout principal en estado
    DETACHED (solo-consumo) y la worktree-dev en la rama `main`
    (donde se trabaja y se pushea).

.DESCRIPTION
    Ver QUICKSTART.md, seccion "0d. Motor dev worktree", para el
    razonamiento completo. Resumen: git no permite que la misma rama este
    checked-out en dos worktrees a la vez, asi que el procedimiento invierte
    quien lleva `main`: el checkout principal se pone detached PRIMERO, y
    solo despues se crea la worktree-dev con `main`.

    Pasos en modo creacion (por defecto, sin -Remove):
      1. Si el checkout principal no esta detached, `git checkout --detach`.
         Si ya esta detached, se reporta y se continua (idempotente).
      2. Si `..\orquestador_de_agentes_dev` no esta registrada como
         worktree, `git worktree add ..\orquestador_de_agentes_dev main`.
         Si ya existe, se reporta y se continua (idempotente).
      3. Si `..\orquestador_de_agentes_dev\.venv\Scripts\python.exe` no
         existe, `uv venv` seguido de `uv sync` dentro de la worktree. Si ya
         existe, se reporta y se continua (idempotente).

    Modo `-Remove`: `git worktree remove ..\orquestador_de_agentes_dev`
    seguido de `git checkout main` en el checkout principal (re-ata la
    rama). Si la worktree tiene cambios sin commitear, falla cerrado (exit
    2), sin forzar el borrado y sin tocar el checkout principal.

.PARAMETER Remove
    Desmonta la worktree-dev y re-ata `main` al checkout principal.

.PARAMETER WhatIf
    Parametro estandar de PowerShell (SupportsShouldProcess): imprime que
    accion se ejecutaria, en ambos modos (creacion y -Remove), sin ejecutar
    ningun comando git/uv.

.EXAMPLE
    .\scripts\setup_dev_worktree.ps1
    Crea (o confirma ya-creada) la worktree-dev con su venv.

.EXAMPLE
    .\scripts\setup_dev_worktree.ps1 -WhatIf
    Muestra el plan de accion sin modificar nada.

.EXAMPLE
    .\scripts\setup_dev_worktree.ps1 -Remove
    Desmonta la worktree-dev y devuelve `main` al checkout principal.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:WorktreeName = 'orquestador_de_agentes_dev'
$script:WorktreeRelativePath = Join-Path '..' $script:WorktreeName
$script:WorktreePath = Join-Path (Split-Path -Parent $script:RepoRoot) $script:WorktreeName

function Invoke-GitCommand {
    param(
        [Parameter(Mandatory)] [string[]]$ArgList,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    # git escribe mensajes informativos (p.ej. "HEAD is now at ...") al stream
    # de error nativo incluso en exito. Con $ErrorActionPreference = 'Stop'
    # global, capturar ese stream con 2>&1 lo convierte en una excepcion
    # terminante (NativeCommandError). Se relaja localmente a 'Continue' para
    # que el exit code (no la presencia de stderr) sea el unico criterio de
    # exito/fallo.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & git -C $WorkingDirectory @ArgList 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [pscustomobject]@{
        Output   = ($output | Out-String).Trim()
        ExitCode = $exitCode
    }
}

function Test-PrincipalDetached {
    # `git symbolic-ref -q HEAD` imprime la rama y devuelve exit 0 si HEAD
    # lleva una rama; devuelve exit distinto de 0 (sin imprimir nada util)
    # si HEAD esta detached.
    $result = Invoke-GitCommand -ArgList @('symbolic-ref', '-q', 'HEAD')
    return $result.ExitCode -ne 0
}

function Get-WorktreeListPorcelain {
    $result = Invoke-GitCommand -ArgList @('worktree', 'list', '--porcelain')
    if ($result.ExitCode -ne 0) {
        throw "git worktree list fallo: $($result.Output)"
    }
    return $result.Output
}

function Test-WorktreeRegistered {
    param([Parameter(Mandatory)] [string]$WorktreePath)

    $normalizedTarget = $WorktreePath.TrimEnd('\', '/').Replace('/', '\')
    $listing = Get-WorktreeListPorcelain
    foreach ($line in ($listing -split "`r?`n")) {
        if ($line -like 'worktree *') {
            $candidate = $line.Substring('worktree '.Length).TrimEnd('\', '/').Replace('/', '\')
            if ($candidate -ieq $normalizedTarget) {
                return $true
            }
        }
    }
    return $false
}

function Test-PrincipalHasUncommittedChanges {
    # El proposito de 019m es que el checkout principal (el que consumen los
    # destinos) quede SIEMPRE limpio. Detachar un principal sucio lo dejaria
    # detached-y-sucio, justo el estado que este script existe para evitar.
    $result = Invoke-GitCommand -ArgList @('status', '--porcelain') -WorkingDirectory $script:RepoRoot
    if ($result.ExitCode -ne 0) {
        throw "git status --porcelain fallo en el checkout principal: $($result.Output)"
    }
    return -not [string]::IsNullOrWhiteSpace($result.Output)
}

function Step-DetachPrincipal {
    # Fail-closed: si el checkout principal tiene cambios sin commitear, NO se
    # detacha (dejaria el checkout de consumo detached-y-sucio). Exit 2, mismo
    # contrato que -Remove sobre una worktree sucia. En -WhatIf se reporta el
    # bloqueo sin abortar (el dry-run nunca muta ni sale con error).
    if (Test-PrincipalHasUncommittedChanges) {
        if ($WhatIfPreference) {
            Write-Host "[setup-dev-worktree] [WhatIf] El checkout principal tiene cambios sin commitear -> el modo real BLOQUEARIA aqui (exit 2) sin detachar ni crear la worktree."
            return
        }
        Write-Warning "El checkout principal tiene cambios sin commitear. No se detacha ni se crea la worktree (exit 2). Commitea, stashea o descarta esos cambios primero."
        exit 2
    }
    if (-not (Test-PrincipalDetached)) {
        if ($PSCmdlet.ShouldProcess($script:RepoRoot, 'git checkout --detach')) {
            $result = Invoke-GitCommand -ArgList @('checkout', '--detach')
            if ($result.ExitCode -ne 0) {
                throw "git checkout --detach fallo: $($result.Output)"
            }
            Write-Host "[setup-dev-worktree] Checkout principal puesto en DETACHED HEAD."
        }
    }
    else {
        Write-Host "[setup-dev-worktree] Checkout principal ya estaba DETACHED (idempotente, sin cambios)."
    }
}

function Step-CreateWorktree {
    if (-not (Test-WorktreeRegistered -WorktreePath $script:WorktreePath)) {
        if ($PSCmdlet.ShouldProcess($script:WorktreePath, "git worktree add $($script:WorktreeRelativePath) main")) {
            $result = Invoke-GitCommand -ArgList @('worktree', 'add', $script:WorktreeRelativePath, 'main')
            if ($result.ExitCode -ne 0) {
                throw "git worktree add fallo: $($result.Output)"
            }
            Write-Host "[setup-dev-worktree] Worktree creada en $($script:WorktreePath) (rama main)."
        }
    }
    else {
        Write-Host "[setup-dev-worktree] La worktree ya existe en $($script:WorktreePath) (idempotente, sin cambios)."
    }
}

function Step-CreateVenv {
    $venvPython = Join-Path $script:WorktreePath '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($PSCmdlet.ShouldProcess($script:WorktreePath, 'uv venv && uv sync')) {
            Push-Location $script:WorktreePath
            try {
                & uv venv
                if ($LASTEXITCODE -ne 0) {
                    throw "uv venv fallo con exit code $LASTEXITCODE"
                }
                & uv sync
                if ($LASTEXITCODE -ne 0) {
                    throw "uv sync fallo con exit code $LASTEXITCODE"
                }
            }
            finally {
                Pop-Location
            }
            Write-Host "[setup-dev-worktree] venv propio creado en $venvPython."
        }
    }
    else {
        Write-Host "[setup-dev-worktree] El venv de la worktree ya existe en $venvPython (idempotente, sin cambios)."
    }
}

function Test-WorktreeHasUncommittedChanges {
    $result = Invoke-GitCommand -ArgList @('status', '--porcelain') -WorkingDirectory $script:WorktreePath
    if ($result.ExitCode -ne 0) {
        throw "git status --porcelain fallo en la worktree: $($result.Output)"
    }
    return -not [string]::IsNullOrWhiteSpace($result.Output)
}

function Invoke-RemoveWorktree {
    if (-not (Test-WorktreeRegistered -WorktreePath $script:WorktreePath)) {
        Write-Host "[setup-dev-worktree] No hay ninguna worktree registrada en $($script:WorktreePath); nada que desmontar."
        return 0
    }

    if (Test-WorktreeHasUncommittedChanges) {
        Write-Warning "La worktree en $($script:WorktreePath) tiene cambios sin commitear. No se desmonta (exit 2)."
        return 2
    }

    if ($PSCmdlet.ShouldProcess($script:WorktreePath, 'git worktree remove')) {
        $removeResult = Invoke-GitCommand -ArgList @('worktree', 'remove', $script:WorktreeRelativePath)
        if ($removeResult.ExitCode -ne 0) {
            throw "git worktree remove fallo: $($removeResult.Output)"
        }
        Write-Host "[setup-dev-worktree] Worktree eliminada."

        $checkoutResult = Invoke-GitCommand -ArgList @('checkout', 'main')
        if ($checkoutResult.ExitCode -ne 0) {
            throw "git checkout main fallo tras eliminar la worktree: $($checkoutResult.Output)"
        }
        Write-Host "[setup-dev-worktree] Checkout principal re-atado a la rama main."
    }

    return 0
}

if ($Remove) {
    $exitCode = Invoke-RemoveWorktree
    exit $exitCode
}

Step-DetachPrincipal
Step-CreateWorktree
Step-CreateVenv
exit 0
