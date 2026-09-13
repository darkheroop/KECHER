@echo off
rem Double-click helper: runs run.ps1 with the execution policy bypassed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
pause
