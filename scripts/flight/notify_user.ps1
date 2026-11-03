param([Parameter(Mandatory=$true)][string]$Title, [Parameter(Mandatory=$true)][string]$Message, [switch]$SimulateToastFailure, [switch]$NoFlash)
# Aviso a Windows: toast (sonido) + parpadeo de la ventana de T3 en la barra (FlashWindowEx, sin robar foco) + pitido de respaldo.
# -SimulateToastFailure: SOLO PARA PRUEBAS. Suprime el toast y sale con exit 3; un llamador que lo pasara dejaria al usuario sin aviso.
# -NoFlash: omite el parpadeo y el pitido (nunca el toast).
$out = @()
$toastFail = $false
try {
  if ($SimulateToastFailure) { throw 'fallo simulado (prueba)' }
  [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
  $e = { param($s) [System.Security.SecurityElement]::Escape($s) }
  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
  $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$(& $e $Title)</text><text>$(& $e $Message)</text></binding></visual><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
  $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show((New-Object Windows.UI.Notifications.ToastNotification $xml))
  $out += 'toast=ok'
} catch { $toastFail = $true; $out += "toast=FALLO($($_.Exception.Message))" }
if (-not $NoFlash) { try {
  Add-Type -ErrorAction Stop -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Flash { [StructLayout(LayoutKind.Sequential)] public struct FLASHWINFO { public uint cbSize; public IntPtr hwnd; public uint dwFlags; public uint uCount; public uint dwTimeout; }
[DllImport("user32.dll")] public static extern bool FlashWindowEx(ref FLASHWINFO p);
public static bool Go(IntPtr h){ var f=new FLASHWINFO(); f.cbSize=(uint)Marshal.SizeOf(typeof(FLASHWINFO)); f.hwnd=h; f.dwFlags=0x2|0xC; f.uCount=uint.MaxValue; f.dwTimeout=0; return FlashWindowEx(ref f);} }
"@
  $n = 0
  Get-Process | Where-Object { $_.ProcessName -like 'T3 Code*' -and $_.MainWindowHandle -ne 0 } | ForEach-Object { [void][Flash]::Go($_.MainWindowHandle); $n++ }
  $out += "flash_ventanas=$n"
} catch { $out += "flash=FALLO($($_.Exception.Message))" } }
if (-not $NoFlash) { [console]::beep(880,250); [console]::beep(660,250) }
$out -join ' '
if ($toastFail) { exit 3 }
