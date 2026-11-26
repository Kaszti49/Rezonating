# Rezonating Lab, one click: start the lab server in the background, connect a plugged-in node, open the Lab in its
# own app window (Edge or Chrome, no tabs or address bar). Closing the window stops the server again.
# The desktop shortcut runs this through start-hidden.vbs (no console). Setup on first run: Setup-RezonatingLab.ps1.
# Log: %LOCALAPPDATA%\rzlab\serve.log
param(
    [string]$Page = '',           # page opened first ('' = Home; live, device, record, review, datasets, experiments, bench, locate)
    [int]$Port = 8765,
    [switch]$NoAutoConnect
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$py = Join-Path $repo '.venv\Scripts\python.exe'
$static = Join-Path $repo 'tools\lab\src\rezonating_lab\static\index.html'
$state = Join-Path $env:LOCALAPPDATA 'rzlab'
$log = Join-Path $state 'serve.log'
$pidFile = Join-Path $state 'server.pid'
$base = "http://127.0.0.1:$Port"
New-Item -ItemType Directory -Force $state | Out-Null
Add-Type -AssemblyName PresentationFramework

function Show-Message([string]$text, [string]$icon = 'Information') {
    [System.Windows.MessageBox]::Show($text, 'Rezonating Lab', 'OK', $icon) | Out-Null
}

function Test-Server {
    try { (Invoke-RestMethod "$base/api/health" -TimeoutSec 1).ok -eq $true } catch { $false }
}

# Browser processes of the Lab's own app-window profile. A new window with this profile is handed to a process that
# already runs it, and the one we started exits at once (2026-11-26: that stopped the server right after it started).
$profileDir = Join-Path $state 'app-window'
function Get-AppWindow {
    $needle = "--user-data-dir=`"$profileDir`""
    @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) })
}

# 1. First run on this machine: Python environment and the built UI
if (-not (Test-Path $py) -or -not (Test-Path $static)) {
    $setup = Join-Path $PSScriptRoot 'Setup-RezonatingLab.ps1'
    $p = Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$setup`"" -Wait -PassThru
    if ($p.ExitCode -ne 0 -or -not (Test-Path $py) -or -not (Test-Path $static)) {
        Show-Message "Setup did not finish (exit code $($p.ExitCode)). Run tools\lab\launcher\Setup-RezonatingLab.ps1 in PowerShell to see why." 'Error'
        exit 1
    }
}

# 2. The server: reuse one that is already running, otherwise start it hidden. Without a server, a left-over app window
# shows nothing: close it first, so the new window opens on the new server.
$ownServer = $null
if (-not (Test-Server)) {
    Get-AppWindow | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    "---- $(Get-Date -Format s) start" | Out-File -Append -Encoding utf8 $log
    $ownServer = Start-Process $py -ArgumentList '-m', 'rezonating_lab.cli', 'serve', '--port', "$Port", '--sim-room' `
        -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $state 'serve.out.log') -RedirectStandardError $log
    $ownServer.Id | Out-File -Encoding ascii $pidFile
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-Server)) {
        if ($ownServer.HasExited -or (Get-Date) -gt $deadline) {
            Show-Message "The lab server did not start. See $log" 'Error'
            exit 1
        }
        Start-Sleep -Milliseconds 300
    }
}

# 3. Connect a plugged-in node (the ESP32-S3's own USB port first); with none, the Device page offers the Simulator
if (-not $NoAutoConnect) {
    try {
        $st = Invoke-RestMethod "$base/api/state" -TimeoutSec 3
        if ($st.connection.state -ne 'connected') {
            $node = (Invoke-RestMethod "$base/api/ports" -TimeoutSec 5).ports | Where-Object { $_.is_node } | Select-Object -First 1
            if ($node) {
                $body = @{ kind = 'serial'; url = $node.device; start = $true } | ConvertTo-Json
                Invoke-RestMethod "$base/api/connect" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 15 | Out-Null
            }
        }
    } catch {
        "auto-connect: $($_.Exception.Message)" | Out-File -Append -Encoding utf8 $log  # the Device page shows the state
    }
}

# 4. The app window. Its own browser profile makes it a separate process, so we can wait for it to close.
$appPath = { param($exe) (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe" -ErrorAction SilentlyContinue).'(default)' }
$browser = @(
    (& $appPath 'msedge.exe'),
    (& $appPath 'chrome.exe'),
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$url = "$base/$Page"
if (-not $browser) {
    Start-Process $url
    Show-Message "Opened the Lab in your browser. The server keeps running; stop it with the 'Stop Rezonating Lab' shortcut."
    exit 0
}
$win = Start-Process $browser -ArgumentList "--app=$url", "--user-data-dir=`"$profileDir`"", '--window-size=1500,950', '--no-first-run' -PassThru
$win.WaitForExit()
# the window may live in another process of the same profile: wait until none is left
Start-Sleep -Seconds 3
while ((Get-AppWindow).Count -gt 0) { Start-Sleep -Seconds 2 }

# 5. Window closed: stop the server we started (politely: disconnect first). Never while a recording runs.
if ($ownServer) {
    try {
        Invoke-RestMethod "$base/api/disconnect" -Method Post -TimeoutSec 10 | Out-Null
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
            Show-Message "A recording or rig check is still running, so the lab server keeps running. Open the Lab again to finish it, or use 'Stop Rezonating Lab'."
            exit 0
        }
    }
    Stop-Process -Id $ownServer.Id -ErrorAction SilentlyContinue
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
