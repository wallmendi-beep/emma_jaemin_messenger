@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Emma - Jaemin Private Messenger
python -m messenger.launcher
if errorlevel 1 (
  echo.
  echo Messenger stopped with an error.
  pause
)
