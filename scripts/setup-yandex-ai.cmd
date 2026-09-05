@echo off
setlocal
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-yandex-ai.ps1"
if errorlevel 1 (
  echo ERROR: Yandex AI settings were not saved.
  pause
  exit /b 1
)

echo.
echo Yandex AI settings are ready. Restarting the bot...
call "%~dp0start-prod-preview.cmd"
