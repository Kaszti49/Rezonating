# First-time setup of Rezonating Lab on this machine (the launcher runs it when something is missing):
# a Python environment in <repo>\.venv with the ml and lab packages, then the browser UI (needs Node.js + npm).
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $repo
Write-Host 'Rezonating Lab setup (a few minutes the first time)' -ForegroundColor Cyan
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Write-Host '1/3 Python environment (.venv)'
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed: is Python 3.10+ installed and on PATH?' }
    }
    Write-Host '2/3 Packages (ml, lab)'
    & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install --quiet -e ml -e tools/lab
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    Write-Host '3/3 Browser UI (npm ci + build)'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'npm not found: install Node.js, then run this again' }
    & .\.venv\Scripts\python.exe -m rezonating_lab.cli build-ui
    if ($LASTEXITCODE -ne 0) { throw 'build-ui failed' }
    Write-Host 'Done.' -ForegroundColor Green
    Start-Sleep -Seconds 2
} catch {
    Write-Host "Setup failed: $_" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
