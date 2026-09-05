@echo off
setlocal
cd /d "%~dp0.."

if not exist ".env" (
  echo ERROR: .env with the Telegram token was not found.
  pause
  exit /b 1
)
if not exist ".env.prod.local" (
  echo ERROR: .env.prod.local with production Odoo access was not found.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Engine is not ready.
  echo Open Docker Desktop and launch this file again.
  pause
  exit /b 1
)

echo Starting ABM Daily Bot against production Odoo portfolio PORTF-008...
docker compose --env-file .env --env-file .env.prod.local -f docker-compose.yml -f docker-compose.prod-preview.yml up -d --build postgres bot
if errorlevel 1 (
  echo ERROR: services failed to start.
  docker compose -f docker-compose.yml -f docker-compose.prod-preview.yml logs --tail 80 bot
  pause
  exit /b 1
)

timeout /t 8 /nobreak >nul
echo.
docker compose -f docker-compose.yml -f docker-compose.prod-preview.yml ps
echo.
docker compose -f docker-compose.yml -f docker-compose.prod-preview.yml logs --tail 30 bot
echo.
echo Production preview is running. Open Telegram and send /daily.
echo Expected task: [BOT TEST] ABM Daily Bot production E2E, Odoo task 597.
pause

