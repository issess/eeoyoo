@echo off
REM EOU Windows Installer (CMD wrapper)
REM Double-click or run: scripts\install.bat

powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
