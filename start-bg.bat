@echo off
rem Start the bot in the background (hidden window) with logs.
rem Run run.bat once first to set up .venv and your token.
cd /d "%~dp0"
if not exist logs mkdir logs
if not exist .venv\Scripts\python.exe (
  echo Please run run.bat first to set up the environment.
  pause
  exit /b 1
)
echo Starting bot in the background...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -WindowStyle Hidden -WorkingDirectory '%cd%' -FilePath '.venv\Scripts\python.exe' -ArgumentList '-m','bot.main' -RedirectStandardOutput 'logs\out.log' -RedirectStandardError 'logs\err.log'"
timeout /t 3 >nul
echo Bot started. Open logs.bat to watch it, or stop.bat to stop it.
pause
