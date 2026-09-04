from datetime import date

from abm_daily_bot.bot.weekly import focus_keyboard
from abm_daily_bot.services.weekly_store import monday_for


def test_monday_for_returns_current_week_start() -> None:
    assert monday_for(date(2026, 9, 4)) == date(2026, 8, 31)
    assert monday_for(date(2026, 8, 31)) == date(2026, 8, 31)


def test_focus_keyboard_marks_selected_tasks() -> None:
    keyboard = focus_keyboard(
        [{"id": 4, "name": "Интеграция"}, {"id": 5, "name": "Документация"}],
        {5},
    )

    assert keyboard.inline_keyboard[0][0].text == "[ ] Интеграция"
    assert keyboard.inline_keyboard[1][0].text == "[x] Документация"
    assert keyboard.inline_keyboard[-1][0].callback_data == "weekly:done"

