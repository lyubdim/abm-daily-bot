import logging
from datetime import UTC, date, datetime
from html import escape
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from abm_daily_bot.bot.keyboards import telegram_button_text
from abm_daily_bot.config import get_settings
from abm_daily_bot.db.models import User, UserRole
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
    claim_invited_user,
    get_or_create_user,
    queue_daily_odoo_sync,
    upsert_daily_answer,
    upsert_daily_summary,
)
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.outbox import OdooOutboxService
from abm_daily_bot.services.telegram_invites import claim_telegram_invite

router = Router(name="daily")
logger = logging.getLogger(__name__)

DEMO_STAGES = [
    {"id": 1, "name": "К выполнению", "fold": False},
    {"id": 2, "name": "В работе", "fold": False},
    {"id": 3, "name": "Готово", "fold": True},
]

DEMO_TASKS = [
    {
        "id": 101,
        "name": "Подготовить структуру дейли-бота",
        "project": "ABM Club",
        "deadline": "2026-09-08",
        "stage": "К выполнению",
        "available_stages": DEMO_STAGES,
    },
    {
        "id": 102,
        "name": "Проверить интеграцию с Odoo",
        "project": "ABM Club",
        "deadline": "2026-09-10",
        "stage": "В работе",
        "available_stages": DEMO_STAGES,
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


def optional_http_url(text: str | None) -> str | None:
    value = (text or "").strip()
    if value == "/skip":
        return None
    parsed = urlsplit(value)
    if (
        len(value) > 1000
        or any(character.isspace() for character in value)
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
    ):
        raise ValueError("Expected a complete HTTP(S) URL")
    return value


class DailyStates(StatesGroup):
    progress = State()
    status = State()
    blocker = State()
    blocker_clarification = State()
    result_url = State()
    resolution_url = State()
    extra = State()


def status_keyboard(stages: list[dict[str, Any]] | None = None) -> InlineKeyboardMarkup:
    available_stages = stages or DEMO_STAGES
    status_rows = [
        [
            InlineKeyboardButton(
                text=telegram_button_text(stage_button_label(str(stage["name"]))),
                callback_data=f"daily:stage:{stage['id']}",
            )
            for stage in available_stages[index : index + 2]
        ]
        for index in range(0, len(available_stages), 2)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=status_rows
        + [
            [
                InlineKeyboardButton(
                    text="🚧 Есть затруднение",
                    callback_data="daily:blocker",
                ),
                InlineKeyboardButton(text="Пропустить →", callback_data="daily:skip"),
            ],
            [
                InlineKeyboardButton(
                    text="Пропустить остальные →",
                    callback_data="daily:skip_rest",
                )
            ],
        ]
    )


def stage_button_label(name: str) -> str:
    normalized = name.strip().lower()
    labels = {
        "к выполнению": "📥 К выполнению",
        "to do": "📥 К выполнению",
        "todo": "📥 К выполнению",
        "backlog": "📥 В очереди",
        "planing": "📝 Планирование",
        "planning": "📝 Планирование",
        "asap": "⚡ Срочно",
        "в работе": "🔵 В работе",
        "in progress": "🔵 В работе",
        "doing": "🔵 В работе",
        "oing": "🔵 В работе",
        "test": "🧪 Тестирование",
        "готово": "✅ Готово",
        "done": "✅ Готово",
        "закрыто": "✅ Готово",
        "closed": "✅ Готово",
    }
    return labels.get(normalized, name)


def normalize_odoo_task(task: dict[str, Any], base_url: str) -> dict[str, Any]:
    project = task.get("project_id")
    project_name = project[1] if isinstance(project, list | tuple) and len(project) > 1 else "-"
    task_url = f"/odoo/project.task/{task['id']}"
    if str(task_url).startswith("/"):
        task_url = f"{base_url.rstrip('/')}{task_url}"
    return {
        "id": task["id"],
        "name": task["name"],
        "project_id": project[0] if isinstance(project, list | tuple) and project else None,
        "project": project_name,
        "deadline": task.get("date_deadline") or "не указан",
        "state": task.get("state"),
        "stage": (
            task["stage_id"][1]
            if isinstance(task.get("stage_id"), list | tuple) and len(task["stage_id"]) > 1
            else None
        ),
        "stage_id": (
            task["stage_id"][0]
            if isinstance(task.get("stage_id"), list | tuple) and task["stage_id"]
            else None
        ),
        "available_stages": [],
        "date_last_stage_update": task.get("date_last_stage_update"),
        "url": str(task_url),
    }


def stage_is_done(stage: dict[str, Any]) -> bool:
    name = str(stage.get("name") or "").strip().lower()
    return bool(stage.get("fold")) or name in {"готово", "done", "закрыто", "closed"}


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
    clarification_question: str | None = None,
    include_description: bool = True,
    resolved: bool = False,
    resolution_url: str | None = None,
) -> str:
    status = "Решено" if resolved else "Открыто"
    rows = [
        "<p><strong>[ABM Daily Bot: затруднение]</strong></p>",
        f"<p><strong>Статус:</strong> {status}</p>",
    ]
    if include_description:
        rows.append(f"<p><strong>Описание:</strong> {escape(blocker_text)}</p>")
    if advice:
        rows.append(f"<p><strong>AI-рекомендация:</strong> {escape(advice)}</p>")
    if clarification_question:
        rows.append(f"<p><strong>Уточняющий вопрос:</strong> {escape(clarification_question)}</p>")
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


def progress_keyboard(task_url: str | None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Без изменений", callback_data="daily:no_changes")]]
    if task_url:
        rows.append([InlineKeyboardButton(text="Открыть в Odoo ↗", url=task_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать дейли",
                    callback_data="scheduled:daily",
                ),
                InlineKeyboardButton(
                    text="Фокус недели",
                    callback_data="scheduled:weekly",
                ),
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
    await state.set_state(DailyStates.progress)
    await message.answer(
        f"<b>Задача {task_index + 1} из {len(tasks)}</b>\n"
        f"<b>{escape(str(task['name']))}</b>\n\n"
        f"📁 {escape(str(task['project']))}\n"
        f"📅 Дедлайн: {escape(str(task['deadline']))}\n"
        f"🏷 Этап: {escape(str(task.get('stage') or 'не указан'))}\n\n"
        "Что сделал или какой прогресс? Можно написать «без изменений».",
        reply_markup=progress_keyboard(str(task_url) if task_url else None),
    )


async def move_to_next_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(
        task_index=data.get("task_index", 0) + 1,
        progress=None,
        selected_stage_id=None,
        selected_stage_name=None,
        selected_state=None,
        blocker=None,
        blocker_original=None,
        advice=None,
        blocker_id=None,
        clarification_question=None,
    )
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
    payload = (message.text or "").partition(" ")[2].strip()
    invite = settings.telegram_invite_codes.get(payload) if payload else None
    dynamic_invite_claimed = False
    if payload and not invite and message.from_user:
        try:
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                user, persistent_invite = await claim_telegram_invite(
                    session,
                    token=payload,
                    telegram_user_id=message.from_user.id,
                    telegram_display_name=message.from_user.full_name,
                    legacy_bot_user_id=message.bot.id,
                )
            odoo_user_id = user.odoo_user_id
            settings.telegram_odoo_user_map[message.from_user.id] = odoo_user_id
            dynamic_invite_claimed = True
            await message.answer(
                "Готово: Telegram подключён к профилю Odoo "
                f"«{escape(persistent_invite.odoo_display_name)}»."
            )
        except (KeyError, TypeError, ValueError) as exc:
            await message.answer(f"Не удалось применить приглашение: {escape(str(exc))}")
            return
        except Exception:  # noqa: BLE001
            await message.answer("Не удалось проверить приглашение. Попробуй ещё раз через минуту.")
            return
    if invite and message.from_user:
        try:
            odoo_user_id = int(invite["odoo_user_id"])
            role = UserRole(str(invite.get("role", UserRole.MEMBER.value)))
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                await claim_invited_user(
                    session,
                    telegram_user_id=message.from_user.id,
                    odoo_user_id=odoo_user_id,
                    display_name=message.from_user.full_name,
                    role=role,
                    legacy_bot_user_id=message.bot.id,
                    allow_rebind=bool(invite.get("allow_rebind", False)),
                )
        except (KeyError, TypeError, ValueError) as exc:
            await message.answer(f"Не удалось применить приглашение: {escape(str(exc))}")
            return
        settings.telegram_odoo_user_map[message.from_user.id] = odoo_user_id
        await message.answer("Готово: Telegram подключён к твоему профилю Odoo.")
    elif not dynamic_invite_claimed:
        odoo_user_id = settings.odoo_user_id_for(message.from_user.id) if message.from_user else 0
    if (
        not settings.demo_mode
        and odoo_user_id > 0
        and message.from_user
        and not invite
        and not dynamic_invite_claimed
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
        except Exception:
            logger.exception("Failed to register Telegram user")
            await message.answer("Не удалось зарегистрировать профиль. Попробуй через минуту.")
            return
    if not settings.demo_mode and odoo_user_id <= 0:
        await message.answer(
            "Профиль пока не подключён к Odoo. Открой персональную ссылку-приглашение "
            "от PM, затем вернись в это меню."
        )
        return
    test_command = (
        "\n/test_reopen 4 — снова открыть тестовую задачу" if settings.app_env == "local" else ""
    )
    await message.answer(
        "<strong>ABM Club Daily</strong>\n"
        "Статусы по задачам из Odoo прямо в Telegram.\n\n"
        "Команды:\n"
        "/daily — пройти дейли\n"
        "/weekly — выбрать фокус недели\n"
        "/blockers — открытые затруднения\n"
        "/whoami — проверить связь с Odoo\n"
        "/cancel — остановить текущий опрос"
        f"{test_command}",
        reply_markup=start_keyboard(),
    )


async def begin_daily_for_user(
    message: Message,
    state: FSMContext,
    telegram_user_id: int,
) -> None:
    await state.clear()
    settings = get_settings()
    if settings.demo_mode:
        tasks = DEMO_TASKS
        mode_message = "Начинаем дейли в demo-режиме. Данные в Odoo не изменяются."
    else:
        odoo_user_id = settings.odoo_user_id_for(telegram_user_id)
        if odoo_user_id <= 0:
            await message.answer("Для пользователя не настроена связь с Odoo.")
            return
        try:
            client = OdooClient(settings)
            raw_tasks = await client.search_open_tasks_for_user(odoo_user_id)
            stages_by_project: dict[int, list[dict[str, Any]]] = {}
            for raw_task in raw_tasks:
                project = raw_task.get("project_id")
                project_id = int(project[0]) if isinstance(project, list | tuple) and project else 0
                if project_id and project_id not in stages_by_project:
                    stages_by_project[project_id] = await client.search_task_stages(project_id)
        except Exception:
            logger.exception("Failed to load daily tasks from Odoo")
            await message.answer("Odoo временно недоступна. Попробуй запустить дейли позже.")
            return
        tasks = []
        for raw_task in raw_tasks:
            task = normalize_odoo_task(raw_task, str(settings.odoo_base_url))
            task["available_stages"] = stages_by_project.get(task["project_id"], [])
            tasks.append(task)
        scope = settings.odoo_scope_label or "Odoo"
        mode_message = f"Начинаем дейли · {escape(scope)}"

    if not tasks:
        await message.answer("Открытых задач, назначенных на тебя, не найдено.")
        return
    await state.update_data(tasks=tasks, task_index=0, answers=[])
    await message.answer(mode_message)
    await ask_current_task(message, state)


@router.message(Command("daily"))
async def begin_daily(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await begin_daily_for_user(message, state, message.from_user.id)


@router.callback_query(F.data == "scheduled:daily")
async def begin_scheduled_daily(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await begin_daily_for_user(callback.message, state, callback.from_user.id)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Опрос остановлен. Чтобы начать заново, отправь /daily.")


@router.message(DailyStates.progress, F.text)
async def receive_progress(message: Message, state: FSMContext) -> None:
    await state.update_data(progress=message.text)
    await state.set_state(DailyStates.status)
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    await message.answer(
        "Выбери этап задачи:",
        reply_markup=status_keyboard(task.get("available_stages")),
    )


@router.callback_query(DailyStates.progress, F.data == "daily:no_changes")
async def receive_no_changes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отмечено: без изменений")
    if not isinstance(callback.message, Message):
        return
    await state.update_data(progress="без изменений")
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    await state.set_state(DailyStates.status)
    await callback.message.answer(
        "Выбери этап задачи:",
        reply_markup=status_keyboard(task.get("available_stages")),
    )


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
    blocker_text = message.text
    advice = demo_advice(task["name"], blocker_text)
    clarification_question: str | None = None
    advice_prefix = (
        "Тестовая рекомендация"
        if settings.demo_mode
        else "Локальная рекомендация (AI API не настроен)"
    )
    if settings.openai_api_key:
        try:
            recent_updates: list[str] = []
            if not settings.demo_mode:
                recent_updates = await OdooClient(settings).recent_task_updates(task["id"])
            context = task_advice_context(task, blocker_text, recent_updates)
            result = await AIAdviceService(
                model=settings.ai_model,
                api_key=settings.openai_api_key,
            ).make_advice(context)
            advice = result.recommendation
            clarification_question = result.clarification_question
            advice_prefix = "AI-совет"
        except Exception:  # noqa: BLE001
            advice_prefix = "AI временно недоступен. Локальная рекомендация"

    try:
        blocker_id = await persist_blocker_response(
            message,
            task=task,
            blocker_text=blocker_text,
            advice=advice,
            clarification_question=clarification_question,
        )
    except Exception:
        logger.exception("Failed to persist blocker")
        await message.answer("Не удалось сохранить затруднение. Попробуй отправить его ещё раз.")
        return

    await state.update_data(
        blocker=blocker_text,
        blocker_original=blocker_text,
        advice=advice or None,
        blocker_id=blocker_id,
        clarification_question=clarification_question,
    )
    if clarification_question:
        await state.set_state(DailyStates.blocker_clarification)
        await message.answer(
            "Чтобы дать конкретный следующий шаг, нужна одна деталь:\n"
            f"{escape(clarification_question)}"
        )
        return

    await finish_blocker_advice(
        message,
        state,
        task=task,
        advice=advice,
        advice_prefix=advice_prefix,
        blocker_id=blocker_id,
    )


async def persist_blocker_response(
    message: Message,
    *,
    task: dict[str, Any],
    blocker_text: str,
    advice: str,
    clarification_question: str | None,
) -> int | None:
    settings = get_settings()
    if not settings.demo_mode:
        if not message.from_user:
            raise RuntimeError("Не удалось определить Telegram-пользователя")
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
                text=blocker_text,
            )
            await upsert_ai_advice(
                session,
                blocker=blocker,
                recommendation=advice,
                clarification_question=clarification_question,
                model=settings.ai_model if settings.openai_api_key else "local-fallback",
            )
            await queue_blocker_odoo_sync(
                session,
                outbox,
                blocker=blocker,
                comment=format_blocker_comment(
                    blocker_text=blocker_text,
                    advice=advice,
                    clarification_question=clarification_question,
                    include_description=settings.odoo_include_blocker_text,
                ),
            )
            blocker_id = blocker.id
        async with session_scope(session_factory) as session:
            await outbox.process_due(session)
        return blocker_id
    return None


async def finish_blocker_advice(
    message: Message,
    state: FSMContext,
    *,
    task: dict[str, Any],
    advice: str,
    advice_prefix: str,
    blocker_id: int | None,
) -> None:
    await state.set_state(DailyStates.status)
    await message.answer(
        f"{advice_prefix}:\n{escape(advice)}",
        reply_markup=resolve_blocker_keyboard(blocker_id) if blocker_id else None,
    )
    await message.answer(
        "Теперь выбери этап задачи:",
        reply_markup=status_keyboard(task.get("available_stages")),
    )


@router.message(DailyStates.blocker_clarification, F.text)
async def receive_blocker_clarification(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    original = str(data.get("blocker_original") or data.get("blocker") or "")
    blocker_text = f"{original}\nУточнение участника: {message.text}"
    settings = get_settings()
    advice = demo_advice(task["name"], blocker_text)
    advice_prefix = "AI временно недоступен. Локальная рекомендация"
    if settings.openai_api_key:
        try:
            recent_updates: list[str] = []
            if not settings.demo_mode:
                recent_updates = await OdooClient(settings).recent_task_updates(task["id"])
            result = await AIAdviceService(
                model=settings.ai_model,
                api_key=settings.openai_api_key,
            ).make_advice(task_advice_context(task, blocker_text, recent_updates))
            if result.needs_clarification:
                raise RuntimeError("AI requested more than one clarification")
            advice = result.recommendation
            advice_prefix = "AI-совет"
        except Exception:  # noqa: BLE001
            advice = demo_advice(task["name"], blocker_text)
            advice_prefix = "AI временно недоступен. Локальная рекомендация"
    try:
        blocker_id = await persist_blocker_response(
            message,
            task=task,
            blocker_text=blocker_text,
            advice=advice,
            clarification_question=None,
        )
    except Exception:
        logger.exception("Failed to persist blocker clarification")
        await message.answer("Не удалось сохранить ответ на уточнение. Попробуй ещё раз.")
        return
    await state.update_data(
        blocker=blocker_text,
        advice=advice,
        blocker_id=blocker_id,
        clarification_question=None,
    )
    await finish_blocker_advice(
        message,
        state,
        task=task,
        advice=advice,
        advice_prefix=advice_prefix,
        blocker_id=blocker_id,
    )


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
    except Exception:
        logger.exception("Failed to load blockers")
        await message.answer("Не удалось получить затруднения. Попробуй через минуту.")
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
    try:
        resolution_url = optional_http_url(message.text)
    except ValueError:
        await message.answer(
            "Нужна полная ссылка, начинающаяся с http:// или https://, либо /skip."
        )
        return
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
                    clarification_question=(advice.clarification_question if advice else None),
                    include_description=settings.odoo_include_blocker_text,
                    resolved=True,
                    resolution_url=resolution_url,
                ),
            )
        async with session_scope(session_factory) as session:
            await outbox.process_due(session)
    except Exception:
        logger.exception("Failed to resolve blocker")
        await message.answer("Не удалось снять затруднение. Попробуй ещё раз.")
        return
    return_state = data.get("resolution_return_state")
    if return_state:
        await state.set_state(return_state)
    else:
        await state.clear()
    await message.answer("Затруднение отмечено решённым, Odoo обновлена или стоит в очереди.")
    if return_state == DailyStates.status.state:
        task = data["tasks"][data["task_index"]]
        await message.answer(
            "Продолжим дейли: выбери этап задачи.",
            reply_markup=status_keyboard(task.get("available_stages")),
        )


@router.callback_query(DailyStates.status, F.data == "daily:skip_rest")
async def skip_rest(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DailyStates.extra)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Оставшиеся задачи пропущены. Делал что-то ещё, не из списка? Напиши текст или /skip."
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


@router.callback_query(DailyStates.status, F.data.startswith("daily:stage:"))
async def choose_stage(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Этап принят")
    if not isinstance(callback.message, Message) or not callback.data:
        return
    stage_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    selected_stage = next(
        (stage for stage in task.get("available_stages", []) if int(stage["id"]) == stage_id),
        None,
    )
    if selected_stage is None:
        await callback.message.answer("Этап больше недоступен. Запусти /daily заново.")
        return
    task_state = "1_done" if stage_is_done(selected_stage) else "01_in_progress"
    await state.update_data(
        selected_stage_id=stage_id,
        selected_stage_name=str(selected_stage["name"]),
        selected_state=task_state,
    )
    if stage_is_done(selected_stage):
        saved = await save_answer_and_continue(
            callback.message,
            state,
            telegram_user_id=callback.from_user.id,
            telegram_full_name=callback.from_user.full_name,
            advance=False,
        )
        if not saved:
            return
        await state.set_state(DailyStates.result_url)
        await callback.message.answer("Пришли ссылку на результат или отправь /skip.")
        return
    await save_answer_and_continue(
        callback.message,
        state,
        telegram_user_id=callback.from_user.id,
        telegram_full_name=callback.from_user.full_name,
    )


async def save_answer_and_continue(
    message: Message,
    state: FSMContext,
    result_url: str | None = None,
    telegram_user_id: int | None = None,
    telegram_full_name: str | None = None,
    advance: bool = True,
) -> bool:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    task_state = data["selected_state"]
    stage_id = int(data["selected_stage_id"])
    stage_name = str(data["selected_stage_name"])
    settings = get_settings()
    if not settings.demo_mode:
        client = OdooClient(settings)
        outbox = OdooOutboxService(client)
        comment = format_odoo_comment(
            progress=data.get("progress"),
            task_state=stage_name,
            blocker=(data.get("blocker") if settings.odoo_include_blocker_text else None),
            advice=data.get("advice"),
            result_url=result_url,
        )
        try:
            actor_id = telegram_user_id or (message.from_user.id if message.from_user else None)
            actor_name = telegram_full_name or (
                message.from_user.full_name if message.from_user else None
            )
            if actor_id is None or actor_name is None:
                raise RuntimeError("Telegram user is unavailable")
            answer_date = datetime.now(ZoneInfo(settings.timezone)).date()
            session_factory = build_session_factory(settings.database_url)
            async with session_scope(session_factory) as session:
                user = await get_or_create_user(
                    session,
                    telegram_user_id=actor_id,
                    odoo_user_id=settings.odoo_user_id_for(actor_id),
                    display_name=actor_name,
                )
                await upsert_daily_answer(
                    session,
                    user=user,
                    task_id=task["id"],
                    answer_date=answer_date,
                    progress=data.get("progress"),
                    task_state=task_state,
                    stage_id=stage_id,
                    result_url=result_url,
                )
                await queue_daily_odoo_sync(
                    session,
                    outbox,
                    odoo_user_id=user.odoo_user_id,
                    task_id=task["id"],
                    answer_date=answer_date,
                    task_state=task_state,
                    stage_id=stage_id,
                    comment=comment,
                )
            async with session_scope(session_factory) as session:
                await outbox.process_due(session)
        except Exception:
            logger.exception("Failed to persist daily answer")
            await message.answer(
                "Не удалось сохранить ответ в локальную очередь. Ответ остаётся в "
                "текущем опросе, попробуй ещё раз."
            )
            await state.set_state(DailyStates.status)
            return False

    if not advance:
        await message.answer(
            "Этап «Готово» уже сохранён в Odoo или поставлен в очередь. "
            "Теперь можно добавить ссылку на результат."
        )
        return True

    answers: list[dict[str, Any]] = list(data.get("answers", []))
    answers.append(
        {
            "task_id": task["id"],
            "progress": data.get("progress"),
            "state": task_state,
            "stage_id": stage_id,
            "stage": stage_name,
            "blocker": data.get("blocker"),
            "result_url": result_url,
        }
    )
    await state.update_data(
        answers=answers,
        blocker=None,
        blocker_original=None,
        advice=None,
        blocker_id=None,
        clarification_question=None,
    )
    if settings.demo_mode:
        await message.answer("Ответ сохранён локально для demo.")
    else:
        await message.answer(
            "Ответ сохранён. Запись в Odoo выполнена или поставлена в очередь повтора."
        )
    await move_to_next_task(message, state)
    return True


@router.message(DailyStates.result_url, F.text)
async def receive_result_url(message: Message, state: FSMContext) -> None:
    try:
        result_url = optional_http_url(message.text)
    except ValueError:
        await message.answer(
            "Нужна полная ссылка, начинающаяся с http:// или https://, либо /skip."
        )
        return
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
        except Exception:
            logger.exception("Failed to persist daily summary")
            await message.answer("Не удалось завершить дейли. Попробуй ещё раз.")
            return
    await state.clear()
    await message.answer(
        f"Дейли завершён.\nОтветов по задачам: {len(answers)}.\nДополнительно: {extra or 'нет'}."
    )
