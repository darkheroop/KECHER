@echo off
rem Stop the running bot process (only bot.main, not other Python programs).
cd /d "%~dp0"
echo Stopping the bot...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*-m bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Done.
timeout /t 2 >nul
