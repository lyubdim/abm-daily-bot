from abm_daily_bot.bot.daily import progress_keyboard, start_keyboard, status_keyboard
from abm_daily_bot.bot.keyboards import (
    invite_role_keyboard,
    manager_menu_keyboard,
    scheduled_action_keyboard,
    telegram_button_text,
)


def test_progress_keyboard_offers_no_changes_and_odoo_link() -> None:
    keyboard = progress_keyboard("https://abmapex.ru/odoo/project.task/597")

    assert keyboard.inline_keyboard[0][0].callback_data == "daily:no_changes"
    assert keyboard.inline_keyboard[1][0].url == ("https://abmapex.ru/odoo/project.task/597")


def test_scheduled_keyboard_starts_requested_flow() -> None:
    keyboard = scheduled_action_keyboard("daily", "Начать дейли")

    assert keyboard.inline_keyboard[0][0].callback_data == "scheduled:daily"


def test_start_keyboard_exposes_main_user_flows() -> None:
    keyboard = start_keyboard()

    callbacks = [button.callback_data for button in keyboard.inline_keyboard[0]]
    assert callbacks == ["scheduled:daily", "scheduled:weekly"]
    assert [button.callback_data for button in keyboard.inline_keyboard[1]] == [
        "menu:blockers",
        "menu:profile",
    ]


def test_manager_start_keyboard_exposes_pm_panel() -> None:
    keyboard = start_keyboard(is_manager=True)

    assert keyboard.inline_keyboard[-1][0].callback_data == "menu:manager"


def test_manager_panel_exposes_all_acceptance_actions() -> None:
    keyboard = manager_menu_keyboard()
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }
    assert callbacks == {
        "menu:status",
        "menu:deadlines",
        "menu:digest:day",
        "menu:digest:week",
        "menu:remind",
        "menu:health",
        "menu:invite",
        "menu:home",
    }


def test_invite_role_keyboard_has_explicit_roles_and_cancel() -> None:
    keyboard = invite_role_keyboard()
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        "invite:role:member",
        "invite:role:pm",
        "invite:role:tech_lead",
        "invite:cancel",
    ]

def test_button_text_is_truncated_on_utf8_boundary() -> None:
    result = telegram_button_text("Очень длинное название задачи " * 5, max_bytes=40)

    assert result.endswith("…")
    assert len(result.encode("utf-8")) <= 40


def test_long_odoo_stage_name_fits_telegram_button_limit() -> None:
    keyboard = status_keyboard(
        [{"id": 999, "name": "Очень длинное название этапа " * 5, "fold": False}]
    )

    label = keyboard.inline_keyboard[0][0].text
    assert len(label.encode("utf-8")) <= 56

