@echo off
rem Opens the Resume Editor (edit your master resume, build one-page PDFs per track) in Chrome.
cd /d "%~dp0"
start "" /B pythonw.exe "%~dp0local\resume-builder\editor_server.py"
timeout /t 2 /nobreak >nul
start "" chrome "http://127.0.0.1:3002"