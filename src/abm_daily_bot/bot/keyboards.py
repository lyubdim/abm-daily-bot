from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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
            [InlineKeyboardButton(text="Пропустить остальные задачи", callback_data="daily:skip_rest")]
        ]
    )

