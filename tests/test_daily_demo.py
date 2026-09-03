from abm_daily_bot.bot.daily import DEMO_TASKS, demo_advice, status_keyboard


def test_demo_contains_multiple_tasks() -> None:
    assert len(DEMO_TASKS) >= 2


def test_status_keyboard_contains_required_actions() -> None:
    callbacks = {
        button.callback_data
        for row in status_keyboard().inline_keyboard
        for button in row
    }

    assert "daily:stage:done" in callbacks
    assert "daily:blocker" in callbacks
    assert "daily:skip" in callbacks
    assert "daily:skip_rest" in callbacks


def test_demo_advice_mentions_the_task() -> None:
    advice = demo_advice("Проверить API", "Нет доступа")

    assert "Проверить API" in advice
    assert "Нет доступа" in advice

