@echo off
rem Opens a live progress window for the job sieve.
start "career-ops sieve progress" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local\sieve-progress.ps1"