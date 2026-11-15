@echo off
rem Builds the laptop tools (needs g++ on the PATH). Double-click or run from firmware	ools.
cd /d %~dp0
g++ -std=c++17 -O2 -Wall -Wextra -o replay.exe replay.cpp ..ezon\src\coreezon_core.cpp || exit /b 1
g++ -std=c++17 -O2 -Wall -Wextra -o fit.exe fit.cpp ..ezon\src\coreezon_core.cpp || exit /b 1
echo built replay.exe fit.exe
