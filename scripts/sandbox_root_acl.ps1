<#
.SYNOPSIS
  Paso UNICO con admin para el sandbox de agentes: permite al contenedor CONSULTAR los atributos de la raiz del disco.

.DESCRIPTION
  Por que existe: los agentes (opencode, node, git...) recorren los directorios padre hasta la raiz del disco con lstat y un
  AppContainer no puede consultar `C:\` (medido: `EPERM: lstat 'C:\'`). Sin admin no hay forma de cambiarlo (medido).
  Que hace: anade UNA ACE para el SID de NUESTRO contenedor (derivado de su nombre, nadie mas la usa) sobre el directorio
  indicado, SOLO esa carpeta (sin herencia). Con `-Rights minimal` (por defecto) concede leer atributos, atributos extendidos,
  permisos y sincronizar: permite el lstat pero NO listar los nombres. Con `-Rights rx` anade ademas listar y recorrer.
  Seguridad: vista previa por defecto (no cambia nada sin `-Apply`); copia de seguridad de la ACL antes de tocar;
  `rollback` quita SOLO esa ACE y comprueba que el resto queda identico a la copia.

.EXAMPLE
  # En un PowerShell ELEVADO:
  .\sandbox_root_acl.ps1 status
  .\sandbox_root_acl.ps1 apply            # vista previa
  .\sandbox_root_acl.ps1 apply -Apply     # aplica
  .\sandbox_root_acl.ps1 rollback -Apply  # deshace
#>
param(
  [Parameter(Position = 0)][ValidateSet('status', 'apply', 'rollback')][string]$Command = 'status',
  [string]$ContainerName = 'agent_sandbox_ac',
  [string]$Target = ($env:SystemDrive + '\'),
  [ValidateSet('minimal', 'rx')][string]$Rights = 'minimal',
  [string]$BackupDir = (Join-Path $env:USERPROFILE 'sandbox_acl_backup'),
  [switch]$Apply,
  [switch]$SkipElevationCheck
)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SbxRootAcl {
  [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeriveAppContainerSidFromAppContainerName(string n, out IntPtr sid);
  [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertSidToStringSid(IntPtr sid, out string s);
  public static string SidOf(string name) {
    IntPtr sid; int hr = DeriveAppContainerSidFromAppContainerName(name, out sid);
    if (hr != 0) throw new Exception("Derive hr=0x" + hr.ToString("X"));
    string s; ConvertSidToStringSid(sid, out s); return s;
  }
}
'@

function Say($m) { Write-Host "[root-acl] $m" }
$sid = [SbxRootAcl]::SidOf($ContainerName)
$tail = ($sid -split '-')[-1]
$spec = if ($Rights -eq 'rx') { '(RX)' } else { '(RA,REA,RC,S)' }
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Show-Acl($title) {
  Say $title
  (& icacls $Target) | Where-Object { $_ -and $_ -notmatch 'Se procesaron|Successfully processed' } | ForEach-Object { Write-Host "    $_" }
}
function Test-OurAce { [bool]((& icacls $Target | Out-String) -match [regex]::Escape($tail)) }
function Get-AclWithoutOurAce {
  # la primera linea de icacls lleva la ruta pegada a la primera ACE: se quita la ruta y se ordena antes de comparar
  $rx = [regex]::Escape($Target)
  $l = & icacls $Target | ForEach-Object { ($_ -replace $rx, '').Trim() } |
    Where-Object { $_ -and $_ -notmatch [regex]::Escape($tail) -and $_ -notmatch 'Se procesaron|Successfully processed' }
  ($l | Sort-Object) -join "`n"
}

Say "objetivo: $Target"
Say "contenedor: $ContainerName  SID: $sid"
Say "derechos: $Rights $spec   elevado: $elevated   modo: $(if ($Apply) { 'APLICAR' } else { 'VISTA PREVIA' })"

switch ($Command) {
  'status' { Show-Acl "ACL actual de $Target"; Say "ACE del contenedor presente: $(Test-OurAce)" }
  'apply' {
    $cmdLine = "icacls `"$Target`" /grant `"*${sid}:$spec`""
    Say "comando que se ejecutara: $cmdLine"
    Say "efecto: el contenedor podra $(if ($Rights -eq 'rx') { 'consultar atributos, LISTAR y recorrer' } else { 'consultar atributos (lstat); NO podra listar nombres' }) en $Target, solo esa carpeta, sin herencia"
    if (-not $Apply) { Say 'VISTA PREVIA: no se ha cambiado nada. Repite con -Apply para aplicar.'; break }
    if (-not $elevated -and -not $SkipElevationCheck) { Say 'ERROR: hace falta un PowerShell elevado (Ejecutar como administrador).'; exit 2 }
    New-Item -ItemType Directory -Force $BackupDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $bk = Join-Path $BackupDir "acl_${stamp}.txt"
    & icacls $Target /save $bk | Out-Null
    (& icacls $Target) | Set-Content (Join-Path $BackupDir "acl_${stamp}_antes.txt") -Encoding utf8
    Say "copia de seguridad: $bk"
    if (Test-OurAce) { Say 'la ACE del contenedor ya existe; se sustituye'; & icacls $Target /remove:g "*$sid" | Out-Null }
    & icacls $Target /grant "*${sid}:$spec" | Out-Null
    if ($LASTEXITCODE -ne 0) { Say "ERROR: icacls fallo (rc=$LASTEXITCODE)"; exit 1 }
    Show-Acl "ACL tras aplicar"
    Say "verificacion: ACE presente = $(Test-OurAce)"
    Say "para deshacer:  .\sandbox_root_acl.ps1 rollback -Apply"
  }
  'rollback' {
    $cmdLine = "icacls `"$Target`" /remove:g `"*$sid`""
    Say "comando que se ejecutara: $cmdLine"
    if (-not $Apply) { Say 'VISTA PREVIA: no se ha cambiado nada. Repite con -Apply para deshacer.'; break }
    if (-not $elevated -and -not $SkipElevationCheck) { Say 'ERROR: hace falta un PowerShell elevado (Ejecutar como administrador).'; exit 2 }
    $antes = Get-AclWithoutOurAce
    & icacls $Target /remove:g "*$sid" | Out-Null
    if ($LASTEXITCODE -ne 0) { Say "ERROR: icacls fallo (rc=$LASTEXITCODE)"; exit 1 }
    $despues = Get-AclWithoutOurAce
    Show-Acl "ACL tras deshacer"
    Say "ACE del contenedor presente = $(Test-OurAce)  (debe ser False)"
    Say "el resto de la ACL no cambio: $($antes -eq $despues)"
  }
}
