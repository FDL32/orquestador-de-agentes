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
         existe, se crea con `uv venv` dentro de la worktree. Si ya existe,
         se reporta y se continua (creacion del venv idempotente). En ambos
         casos se ejecuta `uv sync` a continuacion, siempre, para que las
         dependencias queden sincronizadas aunque el venv ya existiera con
         dependencias faltantes o desactualizadas (`uv sync` es idempotente
         por diseno: no reinstala lo ya sincronizado).

    Modo `-Remove`: `git worktree remove ..\orquestador_de_agentes_dev`
    seguido de `git checkout main` en el checkout principal (re-ata la
    rama). Si la worktree tiene cambios sin commitear, falla cerrado (exit
    2), sin forzar el borrado y sin tocar el checkout principal.

    Modo `-Flight NNN` (WOT-2026-040p): provisiona un worktree POR VUELO
    aislado en `..\orquestador_de_agentes_dev_wt_NNN`, en la rama
    `flight/NNN`, creada desde `main`. Es el mismo procedimiento que el
    split `_dev`/`main`, pero con nombre de worktree y rama distintos: git
    rechaza `main` en dos worktrees a la vez, asi que cada vuelo paralelo
    NECESITA su propia rama. Tras crear la worktree se VALIDA la topologia
    (la rama checked-out es `flight/NNN` y el INDICE esta limpio, no solo
    el working tree). `-Flight NNN -Remove` retira la worktree y elimina la
    rama `flight/NNN` (fail-closed si tiene commits sin fusionar en `main`,
    para NO perder trabajo sin publicar), sin residuo de rama ni worktree.

.PARAMETER Remove
    Desmonta la worktree-dev (o la del vuelo, si se pasa `-Flight`) y, en
    modo `_dev`, re-ata `main` al checkout principal.

.PARAMETER Flight
    Sufijo `NNN` de un vuelo (p. ej. `040p`). Activa el modo worktree-por-
    vuelo: crea/valida/retira `..\orquestador_de_agentes_dev_wt_NNN` en la
    rama `flight/NNN` en vez del split fijo `_dev`/`main`.

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

.EXAMPLE
    .\scripts\setup_dev_worktree.ps1 -Flight 040p
    Crea (o confirma ya-creada) la worktree del vuelo 040p en la rama
    `flight/040p`, con su venv, y valida su topologia e indice limpio.

.EXAMPLE
    .\scripts\setup_dev_worktree.ps1 -Flight 040p -Remove
    Desmonta la worktree del vuelo 040p y elimina su rama `flight/040p`.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Remove,
    [string]$Flight
)

$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Modo worktree-por-vuelo (WOT-2026-040p): nombre de worktree y rama propios,
# distintos del split canonico `_dev`/`main`. La rama de un vuelo es SIEMPRE
# `flight/<NNN>` (el sufijo canonico de un WOT, p. ej. `027h`), que es lo que
# `scripts/check_worktree_topology.py` reconoce como topologia valida para un
# ticket WOT en vuelo. El sufijo se valida ANTES de tocar git (fail-closed,
# exit 2): solo 3 digitos + letra minuscula opcional.
$script:IsFlight = -not [string]::IsNullOrWhiteSpace($Flight)
if ($script:IsFlight) {
    if ($Flight -notmatch '^[0-9]{3}[a-z]?$') {
        Write-Warning "[setup-dev-worktree] -Flight invalido: '$Flight'. Se espera el sufijo canonico de un WOT (3 digitos + letra minuscula opcional, p. ej. 040p)."
        exit 2
    }
    $script:WorktreeName = "orquestador_de_agentes_dev_wt_$Flight"
    $script:WorktreeBranch = "flight/$Flight"
    $script:WorktreeBase = 'main'
}
else {
    $script:WorktreeName = 'orquestador_de_agentes_dev'
    $script:WorktreeBranch = 'main'
    $script:WorktreeBase = 'main'
}
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

function Test-BranchExists {
    param([Parameter(Mandatory)] [string]$Branch)

    # `git rev-parse --verify --quiet refs/heads/<branch>` devuelve exit 0 si
    # la rama local existe y != 0 (sin imprimir nada) si no. Sirve para que el
    # modo vuelo sea idempotente: si `flight/NNN` ya existe (p. ej. tras un
    # -Remove fallido), se re-usa en vez de fallar con `-b`.
    $result = Invoke-GitCommand -ArgList @('rev-parse', '--verify', '--quiet', "refs/heads/$Branch")
    return $result.ExitCode -eq 0
}

function Test-IndexClean {
    param([Parameter(Mandatory)] [string]$Path)

    # Absorbe WOT-2026-040m: un `git checkout` que NO limpia el INDICE deja un
    # cambio STAGED (`git status` del working tree sale limpio, el staged no).
    # `git diff-index --cached --quiet HEAD` compara INDICE vs HEAD: exit 0 =
    # indice limpio, exit 1 = hay entradas staged que difieren de HEAD. A
    # diferencia de `git status --porcelain`, mira SOLO el indice, que es la
    # superficie que el incidente dejo sucia.
    $result = Invoke-GitCommand -ArgList @('diff-index', '--cached', '--quiet', 'HEAD', '--') -WorkingDirectory $Path
    return $result.ExitCode -eq 0
}

function Assert-IndexClean {
    param(
        [string]$Path = $script:RepoRoot,
        [string]$Label = 'repositorio'
    )

    if (Test-IndexClean -Path $Path) {
        return
    }
    if ($WhatIfPreference) {
        Write-Host "[setup-dev-worktree] [WhatIf] INDICE SUCIO en $Path ($Label): el modo real BLOQUEARIA aqui (exit 2)."
        return
    }
    Write-Warning "[setup-dev-worktree] INDICE SUCIO en $Path ($Label): hay cambios STAGED que difieren de HEAD (no solo working tree). Esto es el residuo de 040m: un checkout/restore que no limpio el indice. Commitea, descarta o `git restore --staged` esos cambios (exit 2)."
    exit 2
}

function Assert-WorktreeBranch {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Branch
    )

    $result = Invoke-GitCommand -ArgList @('rev-parse', '--abbrev-ref', 'HEAD') -WorkingDirectory $Path
    if ($result.ExitCode -ne 0) {
        if ($WhatIfPreference) {
            Write-Host "[setup-dev-worktree] [WhatIf] No se pudo leer la rama de $Path; el modo real BLOQUEARIA aqui (exit 2)."
            return
        }
        Write-Warning "[setup-dev-worktree] No se pudo leer la rama de la worktree ${Path}: $($result.Output) (exit 2)."
        exit 2
    }
    $actual = $result.Output.Trim()
    if ($actual -ne $Branch) {
        if ($WhatIfPreference) {
            Write-Host "[setup-dev-worktree] [WhatIf] Se esperaba rama '$Branch' en $Path y es '$actual'; el modo real BLOQUEARIA aqui (exit 2)."
            return
        }
        Write-Warning "[setup-dev-worktree] Topologia incorrecta: se esperaba la rama '$Branch' en $Path, pero se obtuvo '$actual' (exit 2)."
        exit 2
    }
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
            # WOT-2026-040m: verificar el INDICE tras el checkout, no solo el
            # working tree. Un checkout que no lo limpie dejaria residuo staged.
            Assert-IndexClean -Path $script:RepoRoot -Label 'checkout principal tras --detach'
        }
    }
    else {
        Write-Host "[setup-dev-worktree] Checkout principal ya estaba DETACHED (idempotente, sin cambios)."
    }
}

function Step-CreateWorktree {
    if (Test-WorktreeRegistered -WorktreePath $script:WorktreePath) {
        Write-Host "[setup-dev-worktree] La worktree ya existe en $($script:WorktreePath) (idempotente, sin cambios)."
        return
    }

    # Idempotencia de rama: en modo vuelo `flight/NNN` puede existir ya (p. ej.
    # tras un -Remove que fallo por commits sin fusionar). Si existe, se re-usa
    # (`worktree add <rel> <branch>`); si no, se crea desde `main`
    # (`worktree add -b <branch> <rel> main`). En modo _dev la rama `main`
    # siempre existe, asi que se toma la primera rama y el comportamiento es
    # identico al de siempre (aditividad).
    if (Test-BranchExists -Branch $script:WorktreeBranch) {
        $argList = @('worktree', 'add', $script:WorktreeRelativePath, $script:WorktreeBranch)
    }
    else {
        $argList = @('worktree', 'add', '-b', $script:WorktreeBranch, $script:WorktreeRelativePath, $script:WorktreeBase)
    }
    $description = "git $($argList -join ' ')"
    if ($PSCmdlet.ShouldProcess($script:WorktreePath, $description)) {
        $result = Invoke-GitCommand -ArgList $argList
        if ($result.ExitCode -ne 0) {
            throw "git worktree add fallo: $($result.Output)"
        }
        Write-Host "[setup-dev-worktree] Worktree creada en $($script:WorktreePath) (rama $($script:WorktreeBranch))."
    }
}

function Step-CreateVenv {
    # WOT-2026-019s: la creacion del venv (`uv venv`) sigue siendo
    # condicional a que falte python.exe, pero `uv sync` se ejecuta SIEMPRE
    # (tanto si el venv se acaba de crear como si ya existia), porque un
    # venv con python.exe presente puede tener dependencias faltantes o
    # desincronizadas (p.ej. una corrida anterior de `uv sync` fallo o se
    # interrumpio, o pyproject.toml/uv.lock cambiaron despues). `uv sync` es
    # idempotente por diseno, asi que correrlo de mas no tiene costo
    # funcional relevante frente al riesgo de un venv incompleto silencioso.
    $venvPython = Join-Path $script:WorktreePath '.venv\Scripts\python.exe'
    $venvJustCreated = $false
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($PSCmdlet.ShouldProcess($script:WorktreePath, 'uv venv')) {
            Push-Location $script:WorktreePath
            try {
                & uv venv
                if ($LASTEXITCODE -ne 0) {
                    throw "uv venv fallo con exit code $LASTEXITCODE"
                }
            }
            finally {
                Pop-Location
            }
            $venvJustCreated = $true
            Write-Host "[setup-dev-worktree] venv propio creado en $venvPython."
        }
    }
    else {
        Write-Host "[setup-dev-worktree] El venv de la worktree ya existe en $venvPython (se resincronizan dependencias)."
    }

    if ($PSCmdlet.ShouldProcess($script:WorktreePath, 'uv sync')) {
        Push-Location $script:WorktreePath
        try {
            & uv sync
            if ($LASTEXITCODE -ne 0) {
                throw "uv sync fallo con exit code $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }
        if (-not $venvJustCreated) {
            Write-Host "[setup-dev-worktree] Dependencias del venv resincronizadas con uv sync."
        }
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

        if ($script:IsFlight) {
            # Modo vuelo: retirar tambien la rama `flight/NNN` para no dejar
            # residuo. `git branch -d` (NUNCA `-D`) se niega a borrar una rama
            # con commits sin fusionar en HEAD/main: ese caso es trabajo sin
            # publicar y este script NO lo destruye (exit 2, residuo declarado).
            if (Test-BranchExists -Branch $script:WorktreeBranch) {
                $branchResult = Invoke-GitCommand -ArgList @('branch', '-d', $script:WorktreeBranch)
                if ($branchResult.ExitCode -ne 0) {
                    Write-Warning "[setup-dev-worktree] La rama $($script:WorktreeBranch) tiene commits sin fusionar en main; NO se fuerza el borrado (exit 2). Publica o fusiona primero. Residuo declarado: la rama queda. Detalle: $($branchResult.Output)"
                    return 2
                }
                Write-Host "[setup-dev-worktree] Rama $($script:WorktreeBranch) eliminada (sin residuo de rama)."
            }
        }
        else {
            $checkoutResult = Invoke-GitCommand -ArgList @('checkout', 'main')
            if ($checkoutResult.ExitCode -ne 0) {
                throw "git checkout main fallo tras eliminar la worktree: $($checkoutResult.Output)"
            }
            Write-Host "[setup-dev-worktree] Checkout principal re-atado a la rama main."
        }

        # WOT-2026-040m: el INDICE debe quedar limpio tras el checkout/retirada.
        Assert-IndexClean -Path $script:RepoRoot -Label 'checkout principal tras -Remove'
    }

    return 0
}

if ($Remove) {
    $exitCode = Invoke-RemoveWorktree
    exit $exitCode
}

Step-DetachPrincipal
Step-CreateWorktree
if ($script:IsFlight -and -not $WhatIfPreference) {
    # "crea+valida": la worktree de vuelo debe existir en SU rama y con el
    # INDICE limpio antes de darla por provisionada.
    Assert-WorktreeBranch -Path $script:WorktreePath -Branch $script:WorktreeBranch
    Assert-IndexClean -Path $script:WorktreePath -Label "worktree de vuelo flight/$($Flight)"
}
Step-CreateVenv
exit 0
