# Stop the lab server that Start-RezonatingLab.ps1 started (disconnects the node politely first).
param([int]$Port = 8765)
$base = "http://127.0.0.1:$Port"
$pidFile = Join-Path $env:LOCALAPPDATA 'rzlab\server.pid'
Add-Type -AssemblyName PresentationFramework
try {
    Invoke-RestMethod "$base/api/disconnect" -Method Post -TimeoutSec 10 | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        [System.Windows.MessageBox]::Show('A recording or rig check is running. Stop it in the Lab first.', 'Rezonating Lab') | Out-Null
        exit 1
    }
}
if (Test-Path $pidFile) {
    $id = [int](Get-Content $pidFile -Raw)
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $id }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
