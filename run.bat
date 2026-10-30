@echo off
setlocal
cd /d "%~dp0"
title Lao Lottery Formula Lab

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating Python environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Python 3 not found. Install Python 3.11 or newer.
        pause
        exit /b 1
    )
)

echo [2/3] Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

if not exist "data\lao_lottery_full.csv" (
    echo draw_date,number6,number3_top,number2_top,number2_bottom,source>"data\lao_lottery_full.csv"
)

echo [3/3] Starting web dashboard...
echo Open http://127.0.0.1:5000
start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
pause