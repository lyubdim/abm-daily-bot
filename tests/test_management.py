from abm_daily_bot.bot.management import (
    command_task_id,
    health_report_text,
    parse_invite_request,
    parse_telegram_ids,
    preferred_open_stage,
)
from abm_daily_bot.db.models import UserRole


def test_parse_telegram_ids_combines_roles_and_ignores_invalid_values() -> None:
    assert parse_telegram_ids("100, 200", "200,abc,300") == {100, 200, 300}


def test_command_task_id() -> None:
    assert command_task_id("/test_reopen 4") == 4
    assert command_task_id("/test_reopen") is None
    assert command_task_id("/test_reopen task") is None


def test_preferred_open_stage_uses_in_progress_stage() -> None:
    stages = [
        {"id": 23, "name": "К выполнению", "fold": False},
        {"id": 24, "name": "Готово", "fold": True},
        {"id": 25, "name": "В работе", "fold": False},
    ]

    assert preferred_open_stage(stages) == stages[2]


def test_parse_invite_request_defaults_to_member() -> None:
    assert parse_invite_request("/invite person@example.com") == (
        "person@example.com",
        UserRole.MEMBER,
    )


def test_parse_invite_request_accepts_name_and_role() -> None:
    assert parse_invite_request("/invite Антон Кошелев pm") == (
        "Антон Кошелев",
        UserRole.PM,
    )


def test_parse_invite_request_requires_employee_query() -> None:
    assert parse_invite_request("/invite") is None
    assert parse_invite_request("/invite pm") is None


def test_health_report_exposes_integration_state_without_secrets() -> None:
    report = health_report_text(
        database_ok=True,
        odoo_ok=True,
        active_users=3,
        pending_outbox=1,
        failed_outbox=0,
        ai_configured=False,
        scope="PORTF-008 · Управление клубами",
    )

    assert "PostgreSQL: доступна" in report
    assert "Odoo API: авторизация работает" in report
    assert "1 ожидают" in report
    assert "локальный fallback" in report
    assert "Подключено пользователей: 3" in report
    assert "PORTF-008" in report
