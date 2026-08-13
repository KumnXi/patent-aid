@echo off
setlocal
cd /d "%~dp0"
title Patent Writing Assistant - One-Click Start
where powershell >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PowerShell not found on this system.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_patent.ps1"
pause
