from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from abm_daily_bot.bot.daily import DEMO_TASKS, normalize_odoo_task
from abm_daily_bot.config import get_settings
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.services.daily_store import get_or_create_user
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.weekly_store import monday_for, upsert_weekly_plan

router = Router(name="weekly")


class WeeklyStates(StatesGroup):
    focus = State()
    strategic = State()


def focus_keyboard(
    tasks: list[dict[str, Any]], selected_task_ids: set[int]
) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        task_id = int(task["id"])
        marker = "[x]" if task_id in selected_task_ids else "[ ]"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {task['name']}",
                    callback_data=f"weekly:toggle:{task_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Подтвердить", callback_data="weekly:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def load_tasks(telegram_user_id: int) -> list[dict[str, Any]]:
    settings = get_settings()
    if settings.demo_mode:
        return DEMO_TASKS
    odoo_user_id = settings.odoo_user_id_for(telegram_user_id)
    if odoo_user_id <= 0:
        raise RuntimeError("Для пользователя не настроена связь с Odoo")
    raw_tasks = await OdooClient(settings).search_open_tasks_for_user(odoo_user_id)
    return [
        normalize_odoo_task(task, str(settings.odoo_base_url)) for task in raw_tasks
    ]


@router.message(Command("weekly"))
async def begin_weekly(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    try:
        tasks = await load_tasks(message.from_user.id)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось получить задачи: {escape(str(exc))}")
        return
    if not tasks:
        await message.answer("Нет открытых задач для недельного фокуса.")
        return

    await state.update_data(weekly_tasks=tasks, focus_task_ids=[])
    await state.set_state(WeeklyStates.focus)
    await message.answer(
        "На каких задачах фокус на этой неделе? Выбери одну или несколько:",
        reply_markup=focus_keyboard(tasks, set()),
    )


@router.callback_query(WeeklyStates.focus, F.data.startswith("weekly:toggle:"))
async def toggle_focus(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        return
    task_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    data = await state.get_data()
    selected = set(data.get("focus_task_ids", []))
    if task_id in selected:
        selected.remove(task_id)
    else:
        selected.add(task_id)
    await state.update_data(focus_task_ids=sorted(selected))
    await callback.answer("Фокус обновлён")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=focus_keyboard(data["weekly_tasks"], selected)
        )


@router.callback_query(WeeklyStates.focus, F.data == "weekly:done")
async def confirm_focus(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("focus_task_ids"):
        await callback.answer("Выбери хотя бы одну задачу", show_alert=True)
        return
    await callback.answer()
    await state.set_state(WeeklyStates.strategic)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Что-то стратегическое на неделю вне текущих задач? Напиши текст или /skip."
        )


@router.message(WeeklyStates.strategic, F.text)
async def save_weekly(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = [int(task_id) for task_id in data["focus_task_ids"]]
    strategic_text = None if message.text == "/skip" else message.text
    settings = get_settings()

    if not settings.demo_mode:
        if not message.from_user:
            await message.answer("Не удалось определить Telegram-пользователя.")
            return
        try:
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                user = await get_or_create_user(
                    session,
                    telegram_user_id=message.from_user.id,
                    odoo_user_id=settings.odoo_user_id_for(message.from_user.id),
                    display_name=message.from_user.full_name,
                )
                local_date = datetime.now(ZoneInfo(settings.timezone)).date()
                await upsert_weekly_plan(
                    session,
                    user=user,
                    week_start=monday_for(local_date),
                    focus_task_ids=selected,
                    strategic_text=strategic_text,
                )
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"Не удалось сохранить недельный план: {escape(str(exc))}")
            return

    await state.clear()
    await message.answer(
        f"Недельный фокус сохранён. Выбрано задач: {len(selected)}.\n"
        f"Стратегическое: {strategic_text or 'нет'}."
    )

