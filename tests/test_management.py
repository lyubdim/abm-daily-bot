from abm_daily_bot.bot.management import (
    command_task_id,
    parse_telegram_ids,
    preferred_open_stage,
)


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

