@echo off
rem One-time: connects Gmail (and Google Calendar) to career-ops. Google sign-in opens in your browser.
rem First download the "Desktop app" OAuth client JSON from Google Cloud into Downloads (see local\README-local.md).
title Connect Gmail to career-ops
cd /d "%~dp0"
python local\gmail_connect.py
if errorlevel 1 goto end
echo.
echo Testing the connection (set gmail: enabled: true in config\plugins.yml first)...
node plugins.mjs run gmail
:end
echo.
pause
