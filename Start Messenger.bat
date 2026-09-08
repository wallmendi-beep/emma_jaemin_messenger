@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Emma - Jaemin Private Messenger
curl.exe -sS --max-time 2 "http://127.0.0.1:8765/api/health" >nul 2>nul
if not errorlevel 1 (
  start "" "http://127.0.0.1:8765"
  exit /b 0
)
python -m messenger.launcher
if errorlevel 1 (
  echo.
  echo Messenger stopped with an error.
  pause
)
