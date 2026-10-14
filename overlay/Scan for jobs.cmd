@echo off
rem Runs the same job scan that runs by itself at 7 AM and 5 PM (company job boards, no AI usage),
rem then shows the end of its log. New roles appear on the website.
title career-ops scan
cd /d "%~dp0"
echo Scanning company job boards... (this takes a few minutes)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local\daily-scan.ps1"
for /f "delims=" %%f in ('dir /b /od "data\logs\daily-scan-*.log"') do set LAST=%%f
echo.
powershell -NoProfile -Command "Get-Content 'data\logs\%LAST%' -Tail 25"
echo.
echo Done. Open http://127.0.0.1:3000 to see the new roles.
pause