<#
.SYNOPSIS
  Lanzador de agentes dentro de un AppContainer de Windows (barrera de ficheros sin admin).

.DESCRIPTION
  Before: Windows 10/11, PowerShell 5.1, usuario SIN admin. El agente a contener es un ejecutable normal
          (opencode, claude, node, python, git...). Nada de este script modifica el sistema salvo lo que
          crea explicitamente: un perfil AppContainer en HKCU, ACE del contenedor SOLO bajo la raiz del sandbox,
          y una unidad `subst`.
  During: `up` crea el perfil, el arbol de la raiz, copia las herramientas, concede permisos y monta la unidad.
          `run` y `shell` limpian el entorno del PROCESO lanzador (lista blanca), relocalizan HOME dentro del
          sandbox, ejecutan un CANARIO fail-closed y lanzan el hijo con el token del contenedor, heredando
          stdin/stdout/stderr del terminal (sirve en terminales interactivos de un IDE).
  After:  `down` quita los permisos, borra el perfil y la unidad. Los datos de la raiz se conservan salvo `-Purge`.

  Limites declarados (medidos en el spike 2026-10-02, ver SPIKE_barrera_fs_appcontainer): la red es todo o nada
  (`-Net` concede internetClient); solo protege lo que arranca ESTE lanzador; el entorno hereda secretos si no se
  limpia (se limpia aqui); nada bajo C:\Users es accesible, por eso el trabajo vive bajo la raiz del sandbox.

.EXAMPLE
  .\sandbox_launcher.ps1 up
  .\sandbox_launcher.ps1 clone -Source C:\ruta\repo -Name repo
  .\sandbox_launcher.ps1 run -Exe opencode -ExeArgs 'run "resumen"' -Cwd repo -Net
  .\sandbox_launcher.ps1 shell -Net
  .\sandbox_launcher.ps1 down
#>
param(
  [Parameter(Position = 0)][ValidateSet('status', 'up', 'run', 'shell', 'clone', 'snapshot', 'down', 'sid', 'verify')][string]$Command = 'status',
  [string]$Root = (Join-Path $env:SystemDrive 'agent_sandbox'),
  [string]$ContainerName = 'agent_sandbox_ac',
  [string[]]$Tools = @('node', 'python', 'git', 'opencode', 'claude'),
  [string]$Exe,
  [string]$ExeArgs = '',
  [string]$Cwd = '',
  [string]$Source,
  [string]$Name,
  [string]$Ref = 'HEAD',
  [string[]]$PassEnv = @(),
  [int]$TimeoutSec = 0,
  [switch]$Net,
  [switch]$NoCanary,
  [switch]$NullStdin,
  [switch]$Purge
)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class SbxAc {
  [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int CreateAppContainerProfile(string n,string d,string ds,IntPtr caps,uint cc,out IntPtr sid);
  [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeriveAppContainerSidFromAppContainerName(string n,out IntPtr sid);
  [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeleteAppContainerProfile(string n);
  [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertSidToStringSid(IntPtr sid,out string s);
  [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertStringSidToSid(string s,out IntPtr sid);
  [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int n);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetHandleInformation(IntPtr h,uint mask,uint flags);
  [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateFileW(string n,uint acc,uint share,ref SA sa,uint disp,uint fl,IntPtr t);
  [StructLayout(LayoutKind.Sequential)] struct SA { public int n; public IntPtr d; public bool inh; }
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr h);
  [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr h,uint ms);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr h,out uint c);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr h,uint c);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr l,int n,int f,ref IntPtr sz);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr l,uint f,IntPtr a,IntPtr v,IntPtr sz,IntPtr pv,IntPtr prs);
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool CreateProcessW(string app,StringBuilder cmd,IntPtr pa,IntPtr ta,bool inh,uint fl,IntPtr env,string cwd,ref SIEX si,out PI pi);
  [StructLayout(LayoutKind.Sequential)] struct SIEXBASE { public int cb; public IntPtr r; public IntPtr desk; public IntPtr title; public int x,y,xs,ys,xc,yc,fill,flags; public short show,res2; public IntPtr res2p; public IntPtr hin,hout,herr; }
  [StructLayout(LayoutKind.Sequential)] struct SIEX { public SIEXBASE b; public IntPtr attrs; }
  [StructLayout(LayoutKind.Sequential)] struct PI { public IntPtr hp,ht; public int pid,tid; }
  [StructLayout(LayoutKind.Sequential)] struct SECCAP { public IntPtr sid; public IntPtr caps; public uint n; public uint res; }
  [StructLayout(LayoutKind.Sequential)] struct SIDATTR { public IntPtr sid; public uint attr; }

  public static string Create(string name) {
    IntPtr sid; int hr = CreateAppContainerProfile(name, name, "agent sandbox", IntPtr.Zero, 0, out sid);
    if (hr == unchecked((int)0x800700B7)) hr = DeriveAppContainerSidFromAppContainerName(name, out sid);
    if (hr != 0) throw new Exception("CreateAppContainerProfile hr=0x" + hr.ToString("X"));
    string s; ConvertSidToStringSid(sid, out s); return s;
  }
  public static string SidOf(string name) {
    IntPtr sid; int hr = DeriveAppContainerSidFromAppContainerName(name, out sid);
    if (hr != 0) throw new Exception("Derive hr=0x" + hr.ToString("X"));
    string s; ConvertSidToStringSid(sid, out s); return s;
  }
  public static int Delete(string name) { return DeleteAppContainerProfile(name); }
  static IntPtr Inheritable(int std) { IntPtr h = GetStdHandle(std); if (h != IntPtr.Zero && h != (IntPtr)(-1)) SetHandleInformation(h, 1, 1); return h; }

  // Devuelve el codigo de salida del hijo (99 si se corto por plazo, -1 si no pudo crearse). El hijo hereda stdin/stdout/stderr del lanzador.
  public static int Run(string name, string exe, string args, string cwd, bool net, int timeoutMs, bool nullStdin, out string error) {
    error = "";
    IntPtr acsid; if (DeriveAppContainerSidFromAppContainerName(name, out acsid) != 0) { error = "derive"; return -1; }
    IntPtr capSid = IntPtr.Zero, capArr = IntPtr.Zero; uint capN = 0;
    if (net) {
      ConvertStringSidToSid("S-1-15-3-1", out capSid);
      capArr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(SIDATTR)));
      SIDATTR a = new SIDATTR(); a.sid = capSid; a.attr = 4; Marshal.StructureToPtr(a, capArr, false); capN = 1;
    }
    SECCAP sc = new SECCAP(); sc.sid = acsid; sc.caps = capArr; sc.n = capN;
    IntPtr scp = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(SECCAP))); Marshal.StructureToPtr(sc, scp, false);
    IntPtr sz = IntPtr.Zero; InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref sz);
    IntPtr al = Marshal.AllocHGlobal(sz);
    if (!InitializeProcThreadAttributeList(al, 1, 0, ref sz)) { error = "InitAttr " + Marshal.GetLastWin32Error(); return -1; }
    if (!UpdateProcThreadAttribute(al, 0, (IntPtr)0x20009, scp, (IntPtr)Marshal.SizeOf(typeof(SECCAP)), IntPtr.Zero, IntPtr.Zero)) { error = "UpdAttr " + Marshal.GetLastWin32Error(); return -1; }
    SIEX si = new SIEX(); si.b.cb = Marshal.SizeOf(typeof(SIEX)); si.b.flags = 0x100;
    si.b.hin = Inheritable(-10); si.b.hout = Inheritable(-11); si.b.herr = Inheritable(-12); si.attrs = al;
    if (nullStdin) { SA nsa = new SA(); nsa.n = Marshal.SizeOf(typeof(SA)); nsa.inh = true; si.b.hin = CreateFileW("NUL", 0x80000000, 3, ref nsa, 3, 0, IntPtr.Zero); }
    uint cf = 0x80000 | 0x400; if (GetConsoleWindow() == IntPtr.Zero) cf |= 0x08000000;
    StringBuilder cmd = new StringBuilder("\"" + exe + "\" " + args);
    PI pi;
    bool ok = CreateProcessW(null, cmd, IntPtr.Zero, IntPtr.Zero, true, cf, IntPtr.Zero, cwd, ref si, out pi);
    if (!ok) { error = "CreateProcess win32=" + Marshal.GetLastWin32Error(); return -1; }
    uint wr = WaitForSingleObject(pi.hp, timeoutMs > 0 ? (uint)timeoutMs : 0xFFFFFFFF); uint code = 0;
    if (wr != 0) { TerminateProcess(pi.hp, 99); code = 99; } else GetExitCodeProcess(pi.hp, out code);
    CloseHandle(pi.hp); CloseHandle(pi.ht);
    return (int)code;
  }
}
'@

# ---------------------------------------------------------------- utilidades
# Los mensajes del lanzador van a STDERR: un agente ACP (Zed) o cualquier cliente que lea el stdout del hijo no debe recibir texto ajeno.
function Say($m) { [Console]::Error.WriteLine("[sandbox] $m") }
function Out-Result($m) { Write-Output "[sandbox] $m" }
function Get-Sid { try { [SbxAc]::SidOf($ContainerName) } catch { $null } }
function Test-Profile {
  # DeriveAppContainerSid siempre responde: la prueba fiable es la clave del perfil en el registro
  $k = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppContainer\Storage'
  [bool](Get-ChildItem $k -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -like "*$ContainerName*" })
}
function Add-Ace($path, $sidStr, $rights, $inherit = 'ContainerInherit,ObjectInherit') {
  $sid = New-Object System.Security.Principal.SecurityIdentifier($sidStr)
  $acl = Get-Acl $path
  $acl.PurgeAccessRules($sid)
  $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $rights, $inherit, 'None', 'Allow')))
  Set-Acl -Path $path -AclObject $acl
}
function Clear-Ace($path, $sidStr) {
  if (-not (Test-Path $path)) { return }
  $sid = New-Object System.Security.Principal.SecurityIdentifier($sidStr)
  $acl = Get-Acl $path; $acl.PurgeAccessRules($sid); Set-Acl -Path $path -AclObject $acl
}
function Get-Letter {
  $m = (& cmd /c subst) | Where-Object { $_ -match '^([A-Z]):\\: => (.+)$' }
  foreach ($l in $m) { if ($l -match '^([A-Z]):\\: => (.+)$' -and ($Matches[2].TrimEnd('\') -ieq $Root.TrimEnd('\'))) { return $Matches[1] } }
  foreach ($c in 'Z', 'Y', 'X', 'W', 'V', 'U', 'T', 'S') { if (-not (Test-Path ($c + ':\'))) { return $c } }
  throw 'no hay letra de unidad libre'
}
function Mount-Drive {
  $l = Get-Letter
  if (-not (Test-Path ($l + ':\'))) { & cmd /c "subst ${l}: `"$Root`"" | Out-Null }
  return $l
}

# ---------------------------------------------------------------- herramientas
function Resolve-Tool($n) {
  $g = Get-Command $n -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
  if ($g) { return $g.Source } else { return $null }
}
function Sync-Tools {
  $t = Join-Path $Root 'tools'
  New-Item -ItemType Directory -Force $t | Out-Null
  foreach ($n in $Tools) {
    if ($n -eq 'git') { continue }   # git de Program Files es legible por el contenedor: no se copia
    $src = Resolve-Tool $n
    if (-not $src) { Say "AVISO: herramienta '$n' no encontrada, se omite"; continue }
    if ($n -eq 'python') {
      $py = (& $src -c 'import sys;print(sys.base_prefix)').Trim()
      foreach ($f in 'python.exe', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') { if (Test-Path "$py\$f") { Copy-Item "$py\$f" "$t\$f" -Force } }
      Get-ChildItem $py -Filter 'python3*.dll' | ForEach-Object { Copy-Item $_.FullName "$t\$($_.Name)" -Force }
      & robocopy "$py\DLLs" "$t\DLLs" /E /NFL /NDL /NJH /NJS /NP | Out-Null
      & robocopy "$py\Lib" "$t\Lib" /E /XD site-packages test tests idlelib turtledemo tkinter __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    } else {
      $dst = Join-Path $t (Split-Path $src -Leaf)
      if (-not (Test-Path $dst) -or ((Get-Item $dst).Length -ne (Get-Item $src).Length)) { Copy-Item $src $dst -Force }
    }
  }
}

# ---------------------------------------------------------------- entorno del proceso lanzador
function Set-CleanEnv($letter) {
  # lista blanca de variables ESTANDAR (sin secretos). Un bloque de entorno propio en CreateProcess falla (win32=203),
  # asi que se limpia el entorno del propio proceso y el hijo lo hereda.
  $std = 'SystemRoot', 'windir', 'SystemDrive', 'ComSpec', 'PATHEXT', 'OS', 'ProgramData', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432',
  'CommonProgramFiles', 'CommonProgramFiles(x86)', 'CommonProgramW6432', 'ALLUSERSPROFILE', 'PUBLIC', 'USERNAME', 'USERDOMAIN', 'COMPUTERNAME',
  'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'PROCESSOR_LEVEL', 'PROCESSOR_REVISION', 'NUMBER_OF_PROCESSORS', 'DriverData', 'SESSIONNAME'
  $git = Split-Path (Resolve-Tool 'git') -Parent
  $home_ = "${letter}:\home"
  $over = @{
    'TEMP' = "${letter}:\work\.tmp"; 'TMP' = "${letter}:\work\.tmp"
    'PATH' = "${letter}:\tools;$git;$env:SystemRoot\System32"
    'USERPROFILE' = $home_; 'HOME' = $home_; 'APPDATA' = "$home_\AppData\Roaming"; 'LOCALAPPDATA' = "$home_\AppData\Local"
    'XDG_CONFIG_HOME' = "$home_\.config"; 'XDG_DATA_HOME' = "$home_\.local\share"; 'XDG_CACHE_HOME' = "$home_\.cache"; 'XDG_STATE_HOME' = "$home_\.local\state"
    'PYTHONDONTWRITEBYTECODE' = '1'; 'PYTHONIOENCODING' = 'utf-8'
  }
  $pass = @{}; foreach ($p in $PassEnv) { $v = [Environment]::GetEnvironmentVariable($p, 'Process'); if ($v) { $pass[$p] = $v } }
  foreach ($k in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
    if (($std -notcontains $k) -and (-not $over.ContainsKey($k)) -and (-not $pass.ContainsKey($k))) { [Environment]::SetEnvironmentVariable($k, $null, 'Process') }
  }
  foreach ($k in $over.Keys) { [Environment]::SetEnvironmentVariable($k, $over[$k], 'Process') }
  if ($pass.Count -gt 0) { Say ("variables pasadas al hijo (solo nombres): " + ($pass.Keys -join ', ')) }
}

# ---------------------------------------------------------------- canario fail-closed
function Invoke-Canary($letter) {
  # dentro debe leerse; fuera NO. Si falla cualquiera de las dos, el agente no arranca.
  $cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
  $e = ''
  $in = [SbxAc]::Run($ContainerName, $cmd, "/c type ${letter}:\work\CANARY_IN.txt >nul 2>&1", "${letter}:\work", $false, 20000, $false, [ref]$e)
  $out = [SbxAc]::Run($ContainerName, $cmd, "/c type ${letter}:\outside\CANARY_OUT.txt >nul 2>&1", "${letter}:\work", $false, 20000, $false, [ref]$e)
  if ($in -ne 0) { throw "CANARIO: no se puede leer DENTRO del alcance (rc=$in). Alcance mal calculado: no se arranca." }
  if ($out -eq 0) { throw "CANARIO: se pudo leer FUERA del alcance. Barrera rota: no se arranca." }
  Say "canario OK (dentro lee, fuera no)"
}

# ---------------------------------------------------------------- comandos
function Cmd-Up {
  $sid = [SbxAc]::Create($ContainerName)
  foreach ($d in 'work', 'work\.tmp', 'home', 'tools', 'outside') { New-Item -ItemType Directory -Force (Join-Path $Root $d) | Out-Null }
  Set-Content (Join-Path $Root 'work\CANARY_IN.txt') 'dentro-del-alcance' -Encoding ascii
  Set-Content (Join-Path $Root 'outside\CANARY_OUT.txt') 'fuera-del-alcance' -Encoding ascii
  Sync-Tools
  Add-Ace $Root $sid 'ReadAndExecute' 'None'                  # solo esta carpeta: git y node hacen lstat de la raiz
  Add-Ace (Join-Path $Root 'tools') $sid 'ReadAndExecute'
  Add-Ace (Join-Path $Root 'work') $sid 'Modify'
  Add-Ace (Join-Path $Root 'home') $sid 'Modify'
  $l = Mount-Drive
  Say "listo: raiz=$Root unidad=${l}: contenedor=$ContainerName"
  return $l
}
function Cmd-Status {
  Out-Result "raiz: $Root ($(if (Test-Path $Root) { 'existe' } else { 'no existe' }))"
  Out-Result "perfil AppContainer: $(if (Test-Profile) { 'creado' } else { 'no existe' })"
  $l = (& cmd /c subst) | Where-Object { $_ -match [regex]::Escape($Root.TrimEnd('\')) }
  Out-Result "unidad subst: $(if ($l) { $l } else { 'no montada' })"
  $sid = Get-Sid
  Out-Result "SID del contenedor: $sid"
  foreach ($p in $Root, "$Root\tools", "$Root\work", "$Root\home") {
    if (Test-Path $p) { $has = ((icacls $p | Out-String) -match [regex]::Escape(($sid -split '-')[-1])); Out-Result ("ACE del contenedor en {0}: {1}" -f $p, $has) }
  }
}
function Cmd-Run($interactiveShell) {
  if (-not (Test-Profile) -or -not (Test-Path (Join-Path $Root 'tools'))) { $null = Cmd-Up }
  $l = Mount-Drive
  Set-CleanEnv $l
  if (-not $NoCanary) { Invoke-Canary $l }
  if ($interactiveShell) { $exePath = Join-Path $env:SystemRoot 'System32\cmd.exe'; $argLine = '' }
  else {
    if (-not $Exe) { throw '-Exe es obligatorio en run' }
    $exePath = if (Test-Path $Exe) { (Resolve-Path $Exe).Path } else { Join-Path "${l}:\tools" ($(if ($Exe -like '*.exe') { $Exe } else { "$Exe.exe" })) }
    if (($exePath -notlike "${l}:\*") -and ($exePath -notlike "$env:SystemRoot\*") -and ($exePath -notlike "$env:ProgramFiles\*")) { throw "ejecutable fuera del sandbox: $exePath" }
    $argLine = $ExeArgs
  }
  $work = if ($Cwd) { if ([IO.Path]::IsPathRooted($Cwd)) { $Cwd } else { "${l}:\work\$Cwd" } } else { "${l}:\work" }
  $e = ''
  $rc = [SbxAc]::Run($ContainerName, $exePath, $argLine, $work, [bool]$Net, ($TimeoutSec * 1000), [bool]$NullStdin, [ref]$e)
  if ($rc -eq -1) { throw "no se pudo lanzar: $e" }
  exit $rc
}
function Cmd-Verify {
  # Punto de entrada IDE-agnostico: deja el sandbox arriba y ejecuta el canario. rc 0 = barrera efectiva; rc 1 = NO arrancar agentes.
  if (-not (Test-Profile) -or -not (Test-Path (Join-Path $Root 'tools'))) { $null = Cmd-Up }
  $l = Mount-Drive
  try { Invoke-Canary $l; Out-Result 'verify OK'; exit 0 } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
}
function Cmd-Clone {
  if (-not $Source -or -not $Name) { throw 'clone necesita -Source y -Name' }
  $null = Cmd-Up
  $dst = Join-Path $Root "work\$Name"
  if (Test-Path $dst) { throw "ya existe $dst" }
  & git clone --no-hardlinks -q $Source $dst
  if ($LASTEXITCODE -ne 0) { throw 'git clone fallo' }
  Say "clon en $dst (el contenedor ve solo este clon, no el repo original)"
}
function Cmd-Snapshot {
  # exporta los ficheros de un ref SIN .git (sin historial ni remotos). Recomendado para lentes de solo lectura:
  # opencode se cuelga dentro del contenedor al detectar un repo git (medido 2026-10-02), y sin .git funciona.
  if (-not $Source -or -not $Name) { throw 'snapshot necesita -Source y -Name' }
  $null = Cmd-Up
  $dst = Join-Path $Root "work\$Name"
  if (Test-Path $dst) { throw "ya existe $dst" }
  New-Item -ItemType Directory -Force $dst | Out-Null
  & cmd /c "git -C `"$Source`" archive --format=tar $Ref | tar -x -C `"$dst`""
  if ($LASTEXITCODE -ne 0) { throw 'git archive fallo' }
  Say "snapshot de $Ref en $dst (sin .git)"
}
function Cmd-Down {
  $sid = Get-Sid
  if ($sid) { foreach ($p in $Root, "$Root\tools", "$Root\work", "$Root\home") { Clear-Ace $p $sid } }
  [void][SbxAc]::Delete($ContainerName)
  $l = (& cmd /c subst) | Where-Object { $_ -match '^([A-Z]):\\: => ' -and ($_ -match [regex]::Escape($Root.TrimEnd('\'))) }
  foreach ($x in $l) { if ($x -match '^([A-Z]):') { & cmd /c "subst $($Matches[1]): /D" | Out-Null } }
  if ($Purge -and (Test-Path $Root)) { [IO.Directory]::Delete($Root, $true); Say "raiz borrada: $Root" }
  Say "permisos quitados, perfil borrado (perfil en registro: $(Test-Profile)), unidad desmontada"
}

switch ($Command) {
  'status' { Cmd-Status }
  'sid'    { Write-Output (Get-Sid) }
  'verify' { Cmd-Verify }
  'up'     { $null = Cmd-Up }
  'run'    { Cmd-Run $false }
  'shell'  { Cmd-Run $true }
  'clone'  { Cmd-Clone }
  'snapshot' { Cmd-Snapshot }
  'down'   { Cmd-Down }
}
