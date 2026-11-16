@echo off
setlocal
cd /d "%~dp0"
rem Bypass applies only to this PowerShell process; it does not change system policy.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %errorlevel%
