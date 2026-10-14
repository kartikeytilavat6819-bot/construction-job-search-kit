@echo off
rem Starts the read-only PDF helper the career-ops Autofill Chrome extension uses (127.0.0.1:3001).
rem It also starts by itself at logon, so you only need this if it isn't running.
start "" pythonw "%~dp0docs_server.py"
