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
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"scheduled:{action}")]]
    )


def main_menu_keyboard(*, is_manager: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Начать дейли", callback_data="scheduled:daily"),
            InlineKeyboardButton(text="Фокус недели", callback_data="scheduled:weekly"),
        ],
        [
            InlineKeyboardButton(text="Мои затруднения", callback_data="menu:blockers"),
            InlineKeyboardButton(text="Мой профиль", callback_data="menu:profile"),
        ],
    ]
    if is_manager:
        rows.append(
            [InlineKeyboardButton(text="Панель PM", callback_data="menu:manager")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manager_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус команды", callback_data="menu:status"),
                InlineKeyboardButton(text="Дедлайны", callback_data="menu:deadlines"),
            ],
            [
                InlineKeyboardButton(text="Дайджест за день", callback_data="menu:digest:day"),
                InlineKeyboardButton(text="Дайджест за неделю", callback_data="menu:digest:week"),
            ],
            [
                InlineKeyboardButton(text="Напомнить", callback_data="menu:remind"),
                InlineKeyboardButton(text="Проверить систему", callback_data="menu:health"),
            ],
            [
                InlineKeyboardButton(
                    text="Подключить сотрудника", callback_data="menu:invite"
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data="menu:home")],
        ]
    )


def invite_role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Участник", callback_data="invite:role:member"),
                InlineKeyboardButton(text="PM", callback_data="invite:role:pm"),
                InlineKeyboardButton(
                    text="Техлид", callback_data="invite:role:tech_lead"
                ),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="invite:cancel")],
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

