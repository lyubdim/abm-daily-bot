@echo off
setlocal
cd /d "%~dp0.."

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Engine is not ready.
  echo Open Docker Desktop and launch this file again.
  pause
  exit /b 1
)

echo ABM Daily Bot containers:
docker compose ps
echo.

echo Latest daily answers:
docker compose exec -T postgres psql -U abm_bot -d abm_bot -P pager=off -c "SELECT id, odoo_task_id, answer_date, selected_state, left(coalesce(progress_text, ''), 55) AS progress, left(coalesce(result_url, ''), 55) AS result_url FROM daily_answers ORDER BY updated_at DESC LIMIT 5;"
echo.

echo Latest completed daily summaries:
docker compose exec -T postgres psql -U abm_bot -d abm_bot -P pager=off -c "SELECT id, summary_date, left(coalesce(extra_text, ''), 70) AS extra FROM daily_summaries ORDER BY updated_at DESC LIMIT 5;"
echo.

echo Odoo delivery queue:
docker compose exec -T postgres psql -U abm_bot -d abm_bot -P pager=off -c "SELECT id, regexp_replace(idempotency_key, '^daily:[^:]+:', 'daily:TG:') AS operation_key, model, method, state, attempt_count, remote_record_id, left(coalesce(last_error, ''), 70) AS error FROM odoo_outbox ORDER BY updated_at DESC LIMIT 10;"
echo.

echo SENT means Odoo accepted the operation. RETRY will be delivered automatically.
pause

