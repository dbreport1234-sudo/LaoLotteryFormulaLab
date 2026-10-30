@echo off
cd /d "%~dp0"
py -m pip install --upgrade requests beautifulsoup4
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check Python and internet connection.
  pause
  exit /b 1
)
echo.
echo Dependencies installed.
pause
