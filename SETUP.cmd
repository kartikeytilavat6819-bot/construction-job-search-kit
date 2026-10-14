@echo off
rem Double-click me. Installs and sets up career-ops (about 15-25 minutes the first time).
title career-ops setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause