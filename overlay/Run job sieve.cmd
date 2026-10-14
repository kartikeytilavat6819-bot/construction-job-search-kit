@echo off
rem Runs the job sieve (free filter over every scanned job) in the background. Watch it with "Watch sieve progress.cmd".
start "career-ops sieve" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0local\sieve-run.ps1"