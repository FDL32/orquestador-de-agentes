param(
  [Parameter(Mandatory=$true)][string]$Title,
  [Parameter(Mandatory=$true)][string]$Message,
  [string]$Tag = 'flight-notification',
  [string]$Group = 'flight',
  [string]$OpenUri,
  [string]$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe',
  [switch]$Urgent,
  [switch]$XmlOnly,
  [switch]$Remove,
  [switch]$ClearGroup,
  [string]$SimulateNotifierSetting,
  [switch]$SimulateToastFailure,
  [switch]$NoFlash
)
$DismissExplanation = 'Entendido solo cierra el aviso; no es reconocer la causa. URGENTE vuelve a avisar a 30/60/120/240 min.'
$out = @(); $toastFail = $false
function Escape([string]$Value) { [System.Security.SecurityElement]::Escape($Value) }
function EffectiveTag([string]$Value) {
  if ($Value.Length -le 64) { return $Value }
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))).Replace('-', '').ToLowerInvariant()) }
  finally { $sha.Dispose() }
}
function WriteMetaComment([object]$Xml, [string]$Text) { [void]$Xml.DocumentElement.AppendChild($Xml.CreateComment(($Text -replace '--', '-~'))) }
try {
  if ($SimulateToastFailure) { throw 'fallo simulado (prueba)' }
  if ($SimulateNotifierSetting -and $SimulateNotifierSetting -ne 'Enabled') { throw "notifier Setting=$SimulateNotifierSetting" }
  if ($OpenUri -and $OpenUri -notmatch '^t3code://threads/[^\s]+$') { [Console]::Error.WriteLine('OpenUri invalido: solo t3code://threads/...'); exit 2 }
  [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
  $tagEffective = EffectiveTag $Tag
  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
  $titleEsc = Escape $Title; $messageEsc = Escape $Message
  $third = if ($Urgent) { '<text>' + (Escape $DismissExplanation) + '</text>' } else { '' }
  $action = '<action content="Entendido" activationType="system" arguments="dismiss"/>'
  if ($OpenUri) { $action += '<action content="Abrir sesion" activationType="protocol" arguments="' + (Escape $OpenUri) + '"/>' }
  $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$titleEsc</text><text>$messageEsc</text>$third</binding></visual><actions>$action</actions><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
  WriteMetaComment $xml ('effective-tag=' + $tagEffective); WriteMetaComment $xml ('effective-app-id=' + $AppId)
  if ($XmlOnly) { $xml.GetXml(); exit 0 }
  $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
  if ($notifier.Setting -ne 'Enabled') { throw "notifier Setting=$($notifier.Setting)" }
  if ($Remove) {
    [Windows.UI.Notifications.ToastNotificationManager]::History.Remove($tagEffective, $Group, $AppId); $out += 'toast=removed'
  } elseif ($ClearGroup) {
    [Windows.UI.Notifications.ToastNotificationManager]::History.RemoveGroup($Group, $AppId); $out += 'toast=group-cleared'
  } else {
    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml; $toast.Tag = $tagEffective; $toast.Group = $Group; $notifier.Show($toast); $out += 'toast=ok'
  }
} catch { $toastFail = $true; $out += "toast=FALLO($($_.Exception.Message))" }
if (-not $XmlOnly -and -not $NoFlash) { try {
  Add-Type -ErrorAction Stop -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Flash { [StructLayout(LayoutKind.Sequential)] public struct FLASHWINFO { public uint cbSize; public IntPtr hwnd; public uint dwFlags; public uint uCount; public uint dwTimeout; }
[DllImport("user32.dll")] public static extern bool FlashWindowEx(ref FLASHWINFO p);
public static bool Go(IntPtr h){ var f=new FLASHWINFO(); f.cbSize=(uint)Marshal.SizeOf(typeof(FLASHWINFO)); f.hwnd=h; f.dwFlags=0x2|0xC; f.uCount=uint.MaxValue; f.dwTimeout=0; return FlashWindowEx(ref f);} }
"@
  $n = 0; Get-Process | Where-Object { $_.ProcessName -like 'T3 Code*' -and $_.MainWindowHandle -ne 0 } | ForEach-Object { [void][Flash]::Go($_.MainWindowHandle); $n++ }; $out += "flash_ventanas=$n"
} catch { $out += "flash=FALLO($($_.Exception.Message))" } }
if (-not $XmlOnly -and -not $NoFlash) { [console]::beep(880,250); [console]::beep(660,250) }
if (-not $XmlOnly) { $out -join ' ' }
if ($toastFail) { exit 3 }
