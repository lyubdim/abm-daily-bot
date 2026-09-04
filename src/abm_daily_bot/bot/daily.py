from datetime import UTC, date, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from abm_daily_bot.config import get_settings
from abm_daily_bot.db.models import User
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.domain import OdooTask, TaskContextForAdvice
from abm_daily_bot.services.ai_advice import AIAdviceService
from abm_daily_bot.services.blocker_store import (
    open_blockers_for_user,
    queue_blocker_odoo_sync,
    resolve_blocker,
    upsert_ai_advice,
    upsert_open_blocker,
)
from abm_daily_bot.services.daily_store import (
    get_or_create_user,
    queue_daily_odoo_sync,
    upsert_daily_answer,
    upsert_daily_summary,
)
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.outbox import OdooOutboxService

router = Router(name="daily")

DEMO_TASKS = [
    {
        "id": 101,
        "name": "Подготовить структуру дейли-бота",
        "project": "ABM Club",
        "deadline": "2026-09-08",
    },
    {
        "id": 102,
        "name": "Проверить интеграцию с Odoo",
        "project": "ABM Club",
        "deadline": "2026-09-10",
    },
]

ODOO_TASK_STATES = [
    ("В процессе", "01_in_progress"),
    ("Нужны изменения", "02_changes_requested"),
    ("Одобрено", "03_approved"),
    ("Ожидание", "04_waiting_normal"),
    ("Готово", "1_done"),
]
STATE_LABELS = {value: label for label, value in ODOO_TASK_STATES}


class DailyStates(StatesGroup):
    progress = State()
    status = State()
    blocker = State()
    result_url = State()
    resolution_url = State()
    extra = State()


def status_keyboard() -> InlineKeyboardMarkup:
    status_rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"daily:state:{value}",
            )
            for label, value in ODOO_TASK_STATES[index : index + 2]
        ]
        for index in range(0, len(ODOO_TASK_STATES), 2)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=status_rows
        + [
            [
                InlineKeyboardButton(
                    text="Есть затруднение",
                    callback_data="daily:blocker",
                ),
                InlineKeyboardButton(text="Пропустить", callback_data="daily:skip"),
            ],
            [
                InlineKeyboardButton(
                    text="Пропустить остальные",
                    callback_data="daily:skip_rest",
                )
            ],
        ]
    )


def normalize_odoo_task(task: dict[str, Any], base_url: str) -> dict[str, Any]:
    project = task.get("project_id")
    project_name = project[1] if isinstance(project, list | tuple) and len(project) > 1 else "-"
    task_url = f"/odoo/project.task/{task['id']}"
    if str(task_url).startswith("/"):
        task_url = f"{base_url.rstrip('/')}{task_url}"
    return {
        "id": task["id"],
        "name": task["name"],
        "project": project_name,
        "deadline": task.get("date_deadline") or "не указан",
        "state": task.get("state"),
        "stage": (
            task["stage_id"][1]
            if isinstance(task.get("stage_id"), list | tuple)
            and len(task["stage_id"]) > 1
            else None
        ),
        "date_last_stage_update": task.get("date_last_stage_update"),
        "url": str(task_url),
    }


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def task_advice_context(
    task: dict[str, Any],
    blocker_text: str,
    recent_updates: list[str],
    *,
    now: datetime | None = None,
) -> TaskContextForAdvice:
    last_stage_update = _parse_datetime(task.get("date_last_stage_update"))
    current_time = now or datetime.now(UTC)
    days_in_stage = None
    if last_stage_update:
        days_in_stage = max(0, (current_time - last_stage_update).days)
    return TaskContextForAdvice(
        task=OdooTask(
            id=int(task["id"]),
            name=str(task["name"]),
            project_name=str(task.get("project") or "") or None,
            stage_name=str(task.get("stage") or "") or None,
            deadline=_parse_date(task.get("deadline")),
            url=str(task.get("url") or "") or None,
            assignee_odoo_ids=(),
            date_last_stage_update=last_stage_update,
        ),
        blocker_text=blocker_text,
        recent_updates=tuple(recent_updates),
        days_in_current_stage=days_in_stage,
    )


def format_odoo_comment(
    *,
    progress: str | None,
    task_state: str,
    blocker: str | None,
    advice: str | None,
    result_url: str | None,
) -> str:
    rows = [
        "<p><strong>[ABM Daily Bot]</strong></p>",
        f"<p><strong>Прогресс:</strong> {escape(progress or 'без изменений')}</p>",
        f"<p><strong>Статус:</strong> {escape(STATE_LABELS.get(task_state, task_state))}</p>",
    ]
    if blocker:
        rows.append(f"<p><strong>Затруднение:</strong> {escape(blocker)}</p>")
    if advice:
        rows.append(f"<p><strong>AI-рекомендация:</strong> {escape(advice)}</p>")
    if result_url:
        safe_url = escape(result_url, quote=True)
        rows.append(f'<p><strong>Результат:</strong> <a href="{safe_url}">{safe_url}</a></p>')
    return "".join(rows)


def format_blocker_comment(
    *,
    blocker_text: str,
    advice: str,
    resolved: bool = False,
    resolution_url: str | None = None,
) -> str:
    status = "Решено" if resolved else "Открыто"
    rows = [
        "<p><strong>[ABM Daily Bot: затруднение]</strong></p>",
        f"<p><strong>Статус:</strong> {status}</p>",
        f"<p><strong>Описание:</strong> {escape(blocker_text)}</p>",
        f"<p><strong>AI-рекомендация:</strong> {escape(advice)}</p>",
    ]
    if resolution_url:
        safe_url = escape(resolution_url, quote=True)
        rows.append(f'<p><strong>Решение:</strong> <a href="{safe_url}">{safe_url}</a></p>')
    return "".join(rows)


def resolve_blocker_keyboard(blocker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Затруднение решено",
                    callback_data=f"blocker:resolve:{blocker_id}",
                )
            ]
        ]
    )


async def ask_current_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task_index = data.get("task_index", 0)
    tasks = data.get("tasks", DEMO_TASKS)
    if task_index >= len(tasks):
        await state.set_state(DailyStates.extra)
        await message.answer("Делал что-то ещё, не из списка? Напиши текст или /skip.")
        return

    task = tasks[task_index]
    task_url = task.get("url")
    task_link = ""
    if task_url:
        task_link = (
            f'<a href="{escape(str(task_url), quote=True)}">Открыть в Odoo</a>\n'
        )
    await state.set_state(DailyStates.progress)
    await message.answer(
        f"Задача {task_index + 1}/{len(tasks)}\n"
        f"{escape(str(task['name']))}\n"
        f"Проект: {escape(str(task['project']))}\n"
        f"Дедлайн: {escape(str(task['deadline']))}\n"
        f"Этап Odoo: {escape(str(task.get('stage') or 'не указан'))}\n"
        f"Состояние Odoo: {escape(STATE_LABELS.get(task.get('state'), 'не указано'))}\n"
        f"{task_link}\n"
        "Что сделал / какой прогресс? Можно написать «без изменений»."
    )


async def move_to_next_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(task_index=data.get("task_index", 0) + 1, progress=None)
    await ask_current_task(message, state)


def demo_advice(task_name: str, blocker_text: str) -> str:
    return (
        f"Следующий шаг по задаче «{task_name}»: выпиши один проверяемый результат, "
        f"которого не хватает из-за проблемы «{blocker_text}», и запроси его у "
        "конкретного ответственного сегодня."
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    odoo_user_id = (
        settings.odoo_user_id_for(message.from_user.id) if message.from_user else 0
    )
    if (
        not settings.demo_mode
        and odoo_user_id > 0
        and message.from_user
    ):
        try:
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                await get_or_create_user(
                    session,
                    telegram_user_id=message.from_user.id,
                    odoo_user_id=odoo_user_id,
                    display_name=message.from_user.full_name,
                )
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"Не удалось зарегистрировать пользователя: {escape(str(exc))}")
            return
    await message.answer(
        "Привет! Я собираю статусы по задачам ABM Club.\n\n"
        "Команды:\n"
        "/daily — пройти дейли\n"
        "/weekly — выбрать фокус недели\n"
        "/blockers — открытые затруднения\n"
        "/cancel — остановить текущий опрос"
    )


@router.message(Command("daily"))
async def begin_daily(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    if settings.demo_mode:
        tasks = DEMO_TASKS
        mode_message = "Начинаем дейли в demo-режиме. Данные в Odoo не изменяются."
    else:
        odoo_user_id = (
            settings.odoo_user_id_for(message.from_user.id) if message.from_user else 0
        )
        if odoo_user_id <= 0:
            await message.answer("Для пользователя не настроена связь с Odoo.")
            return
        try:
            raw_tasks = await OdooClient(settings).search_open_tasks_for_user(odoo_user_id)
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"Не удалось получить задачи из Odoo: {escape(str(exc))}")
            return
        tasks = [
            normalize_odoo_task(task, str(settings.odoo_base_url))
            for task in raw_tasks
        ]
        mode_message = "Начинаем дейли по задачам из тестового Odoo."

    if not tasks:
        await message.answer("Открытых задач, назначенных на тебя, не найдено.")
        return
    await state.update_data(tasks=tasks, task_index=0, answers=[])
    await message.answer(mode_message)
    await ask_current_task(message, state)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Опрос остановлен. Чтобы начать заново, отправь /daily.")


@router.message(DailyStates.progress, F.text)
async def receive_progress(message: Message, state: FSMContext) -> None:
    await state.update_data(progress=message.text)
    await state.set_state(DailyStates.status)
    await message.answer("Выбери состояние задачи:", reply_markup=status_keyboard())


@router.callback_query(DailyStates.status, F.data == "daily:blocker")
async def request_blocker(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DailyStates.blocker)
    if isinstance(callback.message, Message):
        await callback.message.answer("Опиши затруднение одним сообщением.")


@router.message(DailyStates.blocker, F.text)
async def receive_blocker(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    settings = get_settings()
    advice = demo_advice(task["name"], message.text)
    advice_prefix = "Тестовая рекомендация"
    if settings.openai_api_key:
        try:
            recent_updates: list[str] = []
            if not settings.demo_mode:
                recent_updates = await OdooClient(settings).recent_task_updates(task["id"])
            context = task_advice_context(task, message.text, recent_updates)
            result = await AIAdviceService(
                model=settings.ai_model,
                api_key=settings.openai_api_key,
            ).make_advice(context)
            advice = result.recommendation
            advice_prefix = "AI-совет"
        except Exception:  # noqa: BLE001
            advice_prefix = "AI временно недоступен. Локальная рекомендация"

    blocker_id: int | None = None
    if not settings.demo_mode:
        if not message.from_user:
            await message.answer("Не удалось определить Telegram-пользователя.")
            return
        try:
            session_factory = build_session_factory(settings.database_url)
            outbox = OdooOutboxService(OdooClient(settings))
            async with session_scope(session_factory) as session:
                user = await get_or_create_user(
                    session,
                    telegram_user_id=message.from_user.id,
                    odoo_user_id=settings.odoo_user_id_for(message.from_user.id),
                    display_name=message.from_user.full_name,
                )
                blocker = await upsert_open_blocker(
                    session,
                    user=user,
                    task_id=task["id"],
                    text=message.text,
                )
                await upsert_ai_advice(
                    session,
                    blocker=blocker,
                    recommendation=advice,
                    model=settings.ai_model if settings.openai_api_key else "local-fallback",
                )
                await queue_blocker_odoo_sync(
                    session,
                    outbox,
                    blocker=blocker,
                    comment=format_blocker_comment(
                        blocker_text=message.text,
                        advice=advice,
                    ),
                )
                blocker_id = blocker.id
            async with session_scope(session_factory) as session:
                await outbox.process_due(session)
        except Exception as exc:  # noqa: BLE001
            await message.answer(
                "Не удалось сохранить затруднение. Попробуй отправить его ещё раз. "
                f"Ошибка: {escape(str(exc))}"
            )
            return

    await state.update_data(blocker=message.text, advice=advice, blocker_id=blocker_id)
    await state.set_state(DailyStates.status)
    await message.answer(
        f"{advice_prefix}:\n{escape(advice)}",
        reply_markup=resolve_blocker_keyboard(blocker_id) if blocker_id else None,
    )
    await message.answer("Теперь выбери статус задачи:", reply_markup=status_keyboard())


@router.message(Command("blockers"))
async def list_blockers(message: Message) -> None:
    settings = get_settings()
    if settings.demo_mode:
        await message.answer("В demo-режиме затруднения не сохраняются.")
        return
    if not message.from_user:
        return
    try:
        session_factory = build_session_factory(settings.database_url)
        async with session_scope(session_factory) as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == message.from_user.id)
            )
            blockers = await open_blockers_for_user(session, user.id) if user else []
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось получить затруднения: {escape(str(exc))}")
        return
    if not blockers:
        await message.answer("Открытых затруднений нет.")
        return
    for blocker in blockers:
        await message.answer(
            f"Задача Odoo #{blocker.odoo_task_id}\n{escape(blocker.text)}",
            reply_markup=resolve_blocker_keyboard(blocker.id),
        )


@router.callback_query(F.data.startswith("blocker:resolve:"))
async def request_blocker_resolution(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        return
    blocker_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    return_state = await state.get_state()
    await callback.answer()
    await state.update_data(
        resolving_blocker_id=blocker_id,
        resolution_return_state=return_state,
    )
    await state.set_state(DailyStates.resolution_url)
    if isinstance(callback.message, Message):
        await callback.message.answer("Пришли ссылку на решение или отправь /skip.")


@router.message(DailyStates.resolution_url, F.text)
async def save_blocker_resolution(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    data = await state.get_data()
    resolution_url = None if message.text == "/skip" else message.text
    if not message.from_user:
        return
    try:
        session_factory = build_session_factory(settings.database_url)
        outbox = OdooOutboxService(OdooClient(settings))
        async with session_scope(session_factory) as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == message.from_user.id)
            )
            if not user:
                raise LookupError("Пользователь не найден")
            blocker, advice = await resolve_blocker(
                session,
                blocker_id=int(data["resolving_blocker_id"]),
                user_id=user.id,
                resolution_url=resolution_url,
            )
            await queue_blocker_odoo_sync(
                session,
                outbox,
                blocker=blocker,
                comment=format_blocker_comment(
                    blocker_text=blocker.text,
                    advice=advice.recommendation if advice else "не сформирована",
                    resolved=True,
                    resolution_url=resolution_url,
                ),
            )
        async with session_scope(session_factory) as session:
            await outbox.process_due(session)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось снять затруднение: {escape(str(exc))}")
        return
    if data.get("resolution_return_state") == DailyStates.status.state:
        await state.set_state(DailyStates.status)
    else:
        await state.clear()
    await message.answer("Затруднение отмечено решённым, Odoo обновлена или стоит в очереди.")
    if data.get("resolution_return_state") == DailyStates.status.state:
        await message.answer("Продолжим дейли: выбери статус задачи.", reply_markup=status_keyboard())


@router.callback_query(DailyStates.status, F.data == "daily:skip_rest")
async def skip_rest(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DailyStates.extra)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Оставшиеся задачи пропущены. Делал что-то ещё, не из списка? "
            "Напиши текст или /skip."
        )


@router.callback_query(DailyStates.status, F.data == "daily:skip")
async def skip_task(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Задача пропущена")
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    answers = list(data.get("answers", []))
    task = data["tasks"][data["task_index"]]
    answers.append({"task_id": task["id"], "status": "skipped"})
    await state.update_data(answers=answers)
    await move_to_next_task(callback.message, state)


@router.callback_query(DailyStates.status, F.data.startswith("daily:state:"))
async def choose_state(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Состояние принято")
    if not isinstance(callback.message, Message) or not callback.data:
        return
    task_state = callback.data.rsplit(":", maxsplit=1)[-1]
    await state.update_data(selected_state=task_state)
    if task_state == "1_done":
        await state.set_state(DailyStates.result_url)
        await callback.message.answer("Пришли ссылку на результат или отправь /skip.")
        return
    await save_answer_and_continue(callback.message, state)


async def save_answer_and_continue(
    message: Message,
    state: FSMContext,
    result_url: str | None = None,
) -> None:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    task_state = data["selected_state"]
    settings = get_settings()
    if not settings.demo_mode:
        client = OdooClient(settings)
        outbox = OdooOutboxService(client)
        comment = format_odoo_comment(
            progress=data.get("progress"),
            task_state=task_state,
            blocker=data.get("blocker"),
            advice=data.get("advice"),
            result_url=result_url,
        )
        try:
            if not message.from_user:
                raise RuntimeError("Telegram user is unavailable")
            answer_date = datetime.now(ZoneInfo(settings.timezone)).date()
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                user = await get_or_create_user(
                    session,
                    telegram_user_id=message.from_user.id,
                    odoo_user_id=settings.odoo_user_id_for(message.from_user.id),
                    display_name=message.from_user.full_name,
                )
                await upsert_daily_answer(
                    session,
                    user=user,
                    task_id=task["id"],
                    answer_date=answer_date,
                    progress=data.get("progress"),
                    task_state=task_state,
                    result_url=result_url,
                )
                await queue_daily_odoo_sync(
                    session,
                    outbox,
                    odoo_user_id=user.odoo_user_id,
                    task_id=task["id"],
                    answer_date=answer_date,
                    task_state=task_state,
                    comment=comment,
                )
            async with session_scope(session_factory) as session:
                await outbox.process_due(session)
        except Exception as exc:  # noqa: BLE001
            await message.answer(
                "Не удалось сохранить ответ в локальную очередь. Ответ остаётся в "
                f"текущем опросе, попробуй ещё раз. Ошибка: {escape(str(exc))}"
            )
            await state.set_state(DailyStates.status)
            return

    answers: list[dict[str, Any]] = list(data.get("answers", []))
    answers.append(
        {
            "task_id": task["id"],
            "progress": data.get("progress"),
            "state": task_state,
            "blocker": data.get("blocker"),
            "result_url": result_url,
        }
    )
    await state.update_data(answers=answers, blocker=None, advice=None)
    if settings.demo_mode:
        await message.answer("Ответ сохранён локально для demo.")
    else:
        await message.answer(
            "Ответ сохранён. Запись в Odoo выполнена или поставлена в очередь повтора."
        )
    await move_to_next_task(message, state)


@router.message(DailyStates.result_url, F.text)
async def receive_result_url(message: Message, state: FSMContext) -> None:
    result_url = None if message.text == "/skip" else message.text
    await save_answer_and_continue(message, state, result_url=result_url)


@router.message(DailyStates.extra, F.text)
async def receive_extra(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    answers = data.get("answers", [])
    extra = None if message.text == "/skip" else message.text
    settings = get_settings()
    if not settings.demo_mode:
        if not message.from_user:
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
                await upsert_daily_summary(
                    session,
                    user=user,
                    summary_date=datetime.now(ZoneInfo(settings.timezone)).date(),
                    extra_text=extra,
                )
        except Exception as exc:  # noqa: BLE001
            await message.answer(
                f"Не удалось завершить и сохранить дейли: {escape(str(exc))}"
            )
            return
    await state.clear()
    await message.answer(
        "Дейли завершён.\n"
        f"Ответов по задачам: {len(answers)}.\n"
        f"Дополнительно: {extra or 'нет'}."
    )

