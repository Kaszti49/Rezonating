@echo off
rem Re-fits the fall-score weights from the recordings and session logs in data\raw\hackathon (repo root), then rebuilds the tools.
rem Labels come from firmware\data\labels.tsv (rows: file seconds label) and from L, lines inside the session logs.
setlocal enabledelayedexpansion
cd /d %~dp0
call build.bat || exit /b 1
set FILES=
for %%f in (..\..\..\data\raw\hackathon\geophone_2026-11-12T10-50-07.csv ..\..\..\data\raw\hackathon\geophone_2026-11-12T11-01-32.csv ..\..\..\data\raw\hackathon\geophone_2026-11-12T11-35-59.csv ..\..\..\data\raw\hackathon\*.log) do set FILES=!FILES! "%%f"
replay.exe --quiet --labels ..\data\labels.tsv --events ..\data\events.tsv %FILES%
fit.exe ..\data\events.tsv || exit /b 1
call build.bat
echo.
echo New weights are in rezon\src\core\rezon_weights.h. Flash the firmware again to use them on the device.
