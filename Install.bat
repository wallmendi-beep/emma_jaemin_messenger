@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is required. Install Python and run this file again.
  pause
  exit /b 1
)
if not exist data mkdir data
python -m unittest discover -s tests -v
if errorlevel 1 (
  echo Tests failed. Installation stopped.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Create Shortcut.ps1" -ProjectRoot "%~dp0"
if errorlevel 1 (
  echo Desktop shortcut creation failed.
  pause
  exit /b 1
)
echo Installation complete.
pause
