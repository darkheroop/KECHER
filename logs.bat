@echo off
rem Show a live tail of the bot log (Ctrl+C to stop watching).
cd /d "%~dp0"
if exist "var\logs\bot.log" (
  powershell -NoProfile -Command "Get-Content -Path 'var\logs\bot.log' -Tail 40 -Wait"
) else (
  echo No log file yet at var\logs\bot.log
  echo Start the bot with run.bat or start-bg.bat first.
  pause
)
