@echo off
REM Double-click this to start the local browser studio. It does not install a program.
cd /d "%~dp0"
where powershell >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1"
