#!/bin/sh
# Builds the laptop tools (needs g++). Run from firmware/tools.
set -e
g++ -std=c++17 -O2 -Wall -Wextra -o replay.exe replay.cpp ../rezon/src/core/rezon_core.cpp
g++ -std=c++17 -O2 -Wall -Wextra -o fit.exe fit.cpp ../rezon/src/core/rezon_core.cpp
echo built replay.exe fit.exe
