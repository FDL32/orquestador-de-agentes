[CmdletBinding()]
param(
    [string]$MotorRoot,
    [string]$PythonExe,
    [string]$OpsDir,
    [string]$FlightDir,
    [string]$TaskName = "orquestador-flight-stall",
    [string]$XmlPath,
    [switch]$Register,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$TriggerInterval = "PT10M"

function Fail([string]$Message) {
    throw "REGISTER_STALL_REJECTED: $Message"
}

function Resolve-Existing([string]$Path, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        Fail "$Label is required"
    }
    try {
        return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        Fail "$Label does not resolve: $Path"
    }
}

function Resolve-AbsoluteDirectory([string]$Path, [string]$Label) {
    $resolved = Resolve-Existing $Path $Label
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        Fail "$Label is not a directory: $resolved"
    }
    return $resolved.TrimEnd('\')
}

function Is-Under([string]$Child, [string]$Parent) {
    $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    return $childFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $childFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Invoke-Git([string[]]$Arguments) {
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "git.exe"
    $quoted = foreach ($arg in $Arguments) {
        '"' + ($arg -replace '"', '\\"') + '"'
    }
    $psi.Arguments = $quoted -join " "
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    if (-not $process.Start()) { Fail "cannot start git" }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        Fail ("git failed: " + ($stderr.Trim() -replace "\r?\n", " "))
    }
    return $stdout.Trim()
}

function Get-CurrentSid {
    try {
        return [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    } catch {
        Fail "cannot resolve current user SID"
    }
}

function New-ExpectedArguments([string]$ScriptPath, [string]$Ops, [string]$Flight) {
    return '"' + $ScriptPath + '" --heartbeat-check --ops-dir "' + $Ops + '" --flight-dir "' + $Flight + '"'
}

function Read-Node([System.Xml.XmlNode]$Node, [string]$Name) {
    $matches = @($Node.ChildNodes | Where-Object { $_.NodeType -eq "Element" -and $_.LocalName -eq $Name })
    if ($matches.Count -ne 1) { Fail "expected exactly one $Name under $($Node.LocalName)" }
    return [string]$matches[0].InnerText
}

function Get-ElementChildren([System.Xml.XmlNode]$Node) {
    return @($Node.ChildNodes | Where-Object { $_.NodeType -eq "Element" })
}

function Assert-TaskXml(
    [xml]$Document,
    [string]$Motor,
    [string]$Python,
    [string]$Ops,
    [string]$Flight,
    [string]$Script
) {
    $currentSid = Get-CurrentSid
    $rootChildren = Get-ElementChildren $Document.DocumentElement
    $principals = @($rootChildren | Where-Object { $_.LocalName -eq "Principals" })
    $triggers = @($rootChildren | Where-Object { $_.LocalName -eq "Triggers" })
    $actions = @($rootChildren | Where-Object { $_.LocalName -eq "Actions" })
    if ($principals.Count -ne 1) { Fail "expected exactly one Principals element" }
    if ($triggers.Count -ne 1) { Fail "expected exactly one Triggers element" }
    if ($actions.Count -ne 1) { Fail "expected exactly one Actions element" }

    $principalNodes = @(Get-ElementChildren $principals[0])
    if ($principalNodes.Count -ne 1 -or $principalNodes[0].LocalName -cne "Principal") {
        Fail "expected exactly one Principal element"
    }
    $principal = $principalNodes[0]
    $principalNames = @(Get-ElementChildren $principal | ForEach-Object { $_.LocalName })
    if ($principalNames.Count -ne 3) {
        Fail "Principal contains unexpected children"
    }
    foreach ($required in @("UserId", "LogonType", "RunLevel")) {
        if ($required -notin $principalNames) { Fail "Principal contains unexpected children" }
    }
    $userId = Read-Node $principal "UserId"
    if ($userId -notmatch '^S-1-[0-9-]+$') { Fail "UserId must be a literal SID" }
    if ($userId.ToUpperInvariant() -eq "S-1-5-18") { Fail "SYSTEM/S-1-5-18 is forbidden" }
    if ($userId.ToUpperInvariant() -ne $currentSid.ToUpperInvariant()) {
        Fail "UserId is not the current user's SID"
    }

    $logon = Read-Node $principal "LogonType"
    if ($logon -cne "InteractiveToken") { Fail "LogonType must equal InteractiveToken" }
    $runLevel = Read-Node $principal "RunLevel"
    if ($runLevel -cne "LeastPrivilege") { Fail "RunLevel must equal LeastPrivilege" }
    $settings = @($rootChildren | Where-Object { $_.LocalName -eq "Settings" })
    if ($settings.Count -ne 1) { Fail "expected exactly one Settings element" }
    $instances = Read-Node $settings[0] "MultipleInstancesPolicy"
    if ($instances -cne "IgnoreNew") { Fail "MultipleInstancesPolicy must equal IgnoreNew" }

    $triggerNodes = @(Get-ElementChildren $triggers[0])
    if ($triggerNodes.Count -ne 1 -or $triggerNodes[0].LocalName -cne "TimeTrigger") {
        Fail "expected exactly one TimeTrigger"
    }
    $trigger = $triggerNodes[0]
    $triggerNames = @(Get-ElementChildren $trigger | ForEach-Object { $_.LocalName })
    if ($triggerNames.Count -ne 3) {
        Fail "TimeTrigger contains unexpected children"
    }
    foreach ($required in @("StartBoundary", "Enabled", "Repetition")) {
        if ($required -notin $triggerNames) { Fail "TimeTrigger contains unexpected children" }
    }
    if ((Read-Node $trigger "Enabled") -cne "true") {
        Fail "trigger Enabled must equal true"
    }
    $startBoundary = Read-Node $trigger "StartBoundary"
    [string[]]$formats = @(
        "yyyy-MM-dd'T'HH:mm:ss'Z'",
        "yyyy-MM-dd'T'HH:mm:ss.FFFFFFF'Z'",
        "yyyy-MM-dd'T'HH:mm:sszzz",
        "yyyy-MM-dd'T'HH:mm:ss.FFFFFFFzzz"
    )
    $parsedBoundary = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParseExact(
        [string]$startBoundary,
        $formats,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedBoundary
    )) {
        Fail "StartBoundary must be valid ISO 8601"
    }
    $repetition = @(Get-ElementChildren $trigger | Where-Object { $_.LocalName -eq "Repetition" })[0]
    $repetitionNames = @(Get-ElementChildren $repetition | ForEach-Object { $_.LocalName })
    if ($repetitionNames.Count -ne 2) {
        Fail "Repetition contains unexpected children"
    }
    foreach ($required in @("Interval", "StopAtDurationEnd")) {
        if ($required -notin $repetitionNames) { Fail "Repetition contains unexpected children" }
    }
    if ((Read-Node $repetition "Interval") -cne $TriggerInterval) {
        Fail "trigger interval must equal $TriggerInterval"
    }

    $actionNodes = @(Get-ElementChildren $actions[0])
    if ($actionNodes.Count -ne 1 -or $actionNodes[0].LocalName -cne "Exec") {
        Fail "expected exactly one Exec element"
    }
    $exec = $actionNodes[0]
    $execNames = @(Get-ElementChildren $exec | ForEach-Object { $_.LocalName })
    if ($execNames.Count -ne 3) {
        Fail "Exec contains unexpected children"
    }
    foreach ($required in @("Command", "Arguments", "WorkingDirectory")) {
        if ($required -notin $execNames) { Fail "Exec contains unexpected children" }
    }
    $command = Read-Node $exec "Command"
    if (-not ([IO.Path]::IsPathRooted($command) -and $command -match '^[A-Za-z]:[\\/]|^\\\\')) {
        Fail "Python command must be absolute"
    }
    $pythonResolved = Resolve-Existing $command "PythonExe in XML"
    if (-not (Is-Under $pythonResolved $Motor)) { Fail "PythonExe is outside motor-root" }
    if ([IO.Path]::GetFileName($pythonResolved) -ine "python.exe") {
        Fail "PythonExe leaf must be python.exe"
    }
    if ($pythonResolved -cne $Python) { Fail "PythonExe differs from the fixed interpreter" }

    $working = Read-Node $exec "WorkingDirectory"
    if ($working -cne $Motor) { Fail "WorkingDirectory must equal motor-root" }
    $arguments = Read-Node $exec "Arguments"
    if ($arguments -match '(?i)(cmd\.exe|[<>|]|-Command|-EncodedCommand|-c\b|ExecutionPolicy|Bypass)') {
        Fail "forbidden command or redirection in Arguments"
    }
    if ($arguments -notmatch '--heartbeat-check') { Fail "Arguments must include --heartbeat-check" }
    if ($arguments -match '(?i)--(?!heartbeat-check\b|ops-dir\b|flight-dir\b)') {
        Fail "extra flag in Arguments"
    }
    $expected = New-ExpectedArguments $Script $Ops $Flight
    if ($arguments -cne $expected) { Fail "Arguments are not exact" }
    return $true
}

function New-TaskXml([string]$Sid, [string]$Motor, [string]$Python, [string]$Ops, [string]$Flight, [string]$Script) {
    $doc = [Xml.XmlDocument]::new()
    $decl = $doc.CreateXmlDeclaration("1.0", "UTF-8", $null)
    [void]$doc.AppendChild($decl)
    $task = $doc.CreateElement("Task", "http://schemas.microsoft.com/windows/2004/02/mit/task")
    $task.SetAttribute("version", "1.4")
    [void]$doc.AppendChild($task)
    $principals = $doc.CreateElement("Principals", $task.NamespaceURI)
    $principal = $doc.CreateElement("Principal", $task.NamespaceURI)
    $principal.SetAttribute("id", "Author")
    foreach ($item in @(@("UserId", $Sid), @("LogonType", "InteractiveToken"), @("RunLevel", "LeastPrivilege"))) {
        $node = $doc.CreateElement($item[0], $task.NamespaceURI)
        $node.InnerText = $item[1]
        [void]$principal.AppendChild($node)
    }
    [void]$principals.AppendChild($principal)
    [void]$task.AppendChild($principals)
    $settings = $doc.CreateElement("Settings", $task.NamespaceURI)
    $multi = $doc.CreateElement("MultipleInstancesPolicy", $task.NamespaceURI)
    $multi.InnerText = "IgnoreNew"
    [void]$settings.AppendChild($multi)
    [void]$task.AppendChild($settings)
    $triggers = $doc.CreateElement("Triggers", $task.NamespaceURI)
    $time = $doc.CreateElement("TimeTrigger", $task.NamespaceURI)
    $start = $doc.CreateElement("StartBoundary", $task.NamespaceURI)
    $start.InnerText = [DateTime]::UtcNow.ToString("s") + "Z"
    [void]$time.AppendChild($start)
    $enabled = $doc.CreateElement("Enabled", $task.NamespaceURI)
    $enabled.InnerText = "true"
    [void]$time.AppendChild($enabled)
    $repetition = $doc.CreateElement("Repetition", $task.NamespaceURI)
    $interval = $doc.CreateElement("Interval", $task.NamespaceURI)
    $interval.InnerText = $TriggerInterval
    [void]$repetition.AppendChild($interval)
    $stop = $doc.CreateElement("StopAtDurationEnd", $task.NamespaceURI)
    $stop.InnerText = "false"
    [void]$repetition.AppendChild($stop)
    [void]$time.AppendChild($repetition)
    [void]$triggers.AppendChild($time)
    [void]$task.AppendChild($triggers)
    $actions = $doc.CreateElement("Actions", $task.NamespaceURI)
    $actions.SetAttribute("Context", "Author")
    $exec = $doc.CreateElement("Exec", $task.NamespaceURI)
    foreach ($item in @(@("Command", $Python), @("Arguments", (New-ExpectedArguments $Script $Ops $Flight)), @("WorkingDirectory", $Motor))) {
        $node = $doc.CreateElement($item[0], $task.NamespaceURI)
        $node.InnerText = $item[1]
        [void]$exec.AppendChild($node)
    }
    [void]$actions.AppendChild($exec)
    [void]$task.AppendChild($actions)
    return $doc
}

try {
    if ($Register -and $WhatIf) { Fail "-Register and -WhatIf cannot be combined" }
    if (-not $Register) { $WhatIf = $true }
    if ([string]::IsNullOrWhiteSpace($MotorRoot)) { $MotorRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
    $motor = Resolve-AbsoluteDirectory $MotorRoot "MotorRoot"
    $script = Resolve-Existing (Join-Path $motor "scripts\flight\flight_stall_check.py") "flight_stall_check.py"
    if (-not (Is-Under $script $motor)) { Fail "task script is outside motor-root" }
    $relative = "scripts/flight/flight_stall_check.py"
    [void](Invoke-Git @("-C", $motor, "ls-files", "-z", "--error-unmatch", "--", $relative))
    $workHash = Invoke-Git @("-C", $motor, "hash-object", "--", $script)
    $headHash = Invoke-Git @("-C", $motor, "rev-parse", ("HEAD:" + $relative))
    if ($workHash -ne $headHash) { Fail "flight_stall_check.py differs from HEAD" }
    if ([string]::IsNullOrWhiteSpace($PythonExe)) { $PythonExe = Join-Path $motor ".venv\Scripts\python.exe" }
    $python = Resolve-Existing $PythonExe "PythonExe"
    if (-not (Is-Under $python $motor)) { Fail "PythonExe is outside motor-root" }
    if ([IO.Path]::GetFileName($python) -ine "python.exe") {
        Fail "PythonExe leaf must be python.exe (input)"
    }
    $ops = Resolve-AbsoluteDirectory $OpsDir "OpsDir"
    $flight = Resolve-AbsoluteDirectory $FlightDir "FlightDir"
    $sid = Get-CurrentSid
    if ($sid -eq "S-1-5-18") { Fail "current user is SYSTEM/S-1-5-18" }
    if ([string]::IsNullOrWhiteSpace($XmlPath)) {
        $document = New-TaskXml $sid $motor $python $ops $flight $script
        $source = "generated"
    } else {
        $xmlFile = Resolve-Existing $XmlPath "XmlPath"
        try { $document = [Xml.XmlDocument]::new(); $document.Load($xmlFile) } catch { Fail "invalid XML: $xmlFile" }
        $source = "input"
    }
    [void](Assert-TaskXml $document $motor $python $ops $flight $script)
    $xmlText = $document.OuterXml
    if ($WhatIf) {
        Write-Output "REGISTER_STALL_WHATIF: XML $source validated; no task registered"
        Write-Output $xmlText
        exit 0
    }
    Register-ScheduledTask -TaskName $TaskName -Xml $xmlText -User $sid -Force | Out-Null
    $marker = Join-Path $ops "task_registered.json"
    $payload = [ordered]@{ task_name = $TaskName; motor_root = $motor; script = $script; registered_by = $sid }
    [IO.File]::WriteAllText($marker, ($payload | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
    Write-Output "REGISTER_STALL_REGISTERED: $TaskName"
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
