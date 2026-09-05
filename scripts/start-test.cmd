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

docker compose -p abm-daily-bot -f docker-compose.yml down --remove-orphans >nul 2>&1
docker compose -p abm-daily-bot -f docker-compose.yml up -d --build postgres bot
if errorlevel 1 (
  echo ERROR: services failed to start.
  docker compose -p abm-daily-bot -f docker-compose.yml logs --tail 80 bot
  pause
  exit /b 1
)

echo Waiting for the bot startup check...
timeout /t 8 /nobreak >nul

echo.
echo ABM Daily Bot test services are running:
docker compose -p abm-daily-bot -f docker-compose.yml ps
echo.
echo Recent bot logs:
docker compose -p abm-daily-bot -f docker-compose.yml logs --tail 40 bot
echo.
set "BOT_RUNNING="
for /f %%I in ('docker compose -p abm-daily-bot -f docker-compose.yml ps --status running --quiet bot') do set "BOT_RUNNING=1"
if not defined BOT_RUNNING (
  echo ERROR: the bot stopped after startup. Send a screenshot of this window.
  pause
  exit /b 1
)

echo Open Telegram and send /start to @abm_club_daily_bot
pause

