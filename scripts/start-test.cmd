@echo off
setlocal
cd /d "%~dp0.."

if not exist ".env" (
  echo ERROR: .env was not found in %CD%
  echo Create it from .env.example and add local test secrets.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Engine is not ready.
  echo Open Docker Desktop, wait for Engine running, and launch this file again.
  pause
  exit /b 1
)

docker rm -f abm-daily-bot >nul 2>&1
docker compose up -d --build postgres bot
if errorlevel 1 (
  echo ERROR: services failed to start.
  docker compose logs --tail 80 bot
  pause
  exit /b 1
)

echo.
echo ABM Daily Bot test services are running:
docker compose ps
echo.
echo Open Telegram and send /start to @abm_club_daily_bot
pause

