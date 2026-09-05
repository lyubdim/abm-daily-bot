from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def telegram_button_text(value: str, max_bytes: int = 56) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "…"
    allowed = max_bytes - len(suffix.encode("utf-8"))
    result = bytearray()
    for character in value:
        part = character.encode("utf-8")
        if len(result) + len(part) > allowed:
            break
        result.extend(part)
    return result.decode("utf-8") + suffix


def scheduled_action_keyboard(action: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"scheduled:{action}")]
        ]
    )


def task_status_keyboard(task_id: int, stages: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for stage_id, label in stages:
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"task:{task_id}:stage:{stage_id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Есть затруднение",
                callback_data=f"task:{task_id}:blocker",
            ),
            InlineKeyboardButton(
                text="Пропустить",
                callback_data=f"task:{task_id}:skip",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def daily_control_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить остальные задачи",
                    callback_data="daily:skip_rest",
                )
            ]
        ]
    )
