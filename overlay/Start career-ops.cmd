@echo off
rem Starts the career-ops website on this computer only (http://127.0.0.1:3000) and opens it in Chrome.
rem Normally it already runs by itself after you log in; use this if the page doesn't load.
title career-ops (close this window to stop the site)
cd /d "%~dp0web"
set NEXT_TELEMETRY_DISABLED=1
start "" cmd /c "timeout /t 6 >nul & start "" chrome http://127.0.0.1:3000"
node server.mjs start