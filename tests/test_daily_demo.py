from datetime import UTC, datetime

from abm_daily_bot.bot.daily import (
    DEMO_TASKS,
    demo_advice,
    format_blocker_comment,
    format_odoo_comment,
    normalize_odoo_task,
    status_keyboard,
    task_advice_context,
)


def test_demo_contains_multiple_tasks() -> None:
    assert len(DEMO_TASKS) >= 2


def test_status_keyboard_contains_required_actions() -> None:
    callbacks = {
        button.callback_data
        for row in status_keyboard().inline_keyboard
        for button in row
    }

    assert "daily:state:1_done" in callbacks
    assert "daily:state:04_waiting_normal" in callbacks
    assert "daily:blocker" in callbacks
    assert "daily:skip" in callbacks
    assert "daily:skip_rest" in callbacks


def test_demo_advice_mentions_the_task() -> None:
    advice = demo_advice("Проверить API", "Нет доступа")

    assert "Проверить API" in advice
    assert "Нет доступа" in advice


def test_normalize_odoo_task_builds_project_and_url() -> None:
    task = normalize_odoo_task(
        {
            "id": 4,
            "name": "Интеграция",
            "project_id": [1, "ABM Daily Bot Test"],
            "date_deadline": "2026-09-11 12:00:00",
            "state": "01_in_progress",
            "access_url": "/my/tasks/4",
        },
        "http://odoo.test",
    )

    assert task["project"] == "ABM Daily Bot Test"
    assert task["url"] == "http://odoo.test/odoo/project.task/4"


def test_odoo_comment_escapes_user_content() -> None:
    comment = format_odoo_comment(
        progress="Исправил <ошибку>",
        task_state="1_done",
        blocker=None,
        advice=None,
        result_url="https://example.com/?a=1&b=2",
    )

    assert "Исправил &lt;ошибку&gt;" in comment
    assert "Готово" in comment
    assert "a=1&amp;b=2" in comment


def test_task_advice_context_calculates_days_in_stage() -> None:
    context = task_advice_context(
        {
            "id": 4,
            "name": "Интеграция",
            "project": "ABM Daily Bot Test",
            "stage": "В работе",
            "deadline": "2026-09-11",
            "date_last_stage_update": "2026-09-01 09:00:00",
            "url": "http://odoo.test/my/tasks/4",
        },
        "Не проходит авторизация",
        ["Проверил API key"],
        now=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
    )

    assert context.task.stage_name == "В работе"
    assert context.task.deadline.isoformat() == "2026-09-11"
    assert context.days_in_current_stage == 3
    assert context.recent_updates == ("Проверил API key",)


def test_blocker_comment_escapes_content_and_includes_resolution() -> None:
    comment = format_blocker_comment(
        blocker_text="Нет <доступа>",
        advice="Запросить роль & повторить",
        resolved=True,
        resolution_url="https://example.com/?a=1&b=2",
    )

    assert "Решено" in comment
    assert "Нет &lt;доступа&gt;" in comment
    assert "роль &amp; повторить" in comment
    assert "a=1&amp;b=2" in comment

