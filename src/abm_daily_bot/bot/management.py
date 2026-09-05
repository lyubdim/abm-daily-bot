import logging
from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from abm_daily_bot.bot.keyboards import (
    invite_role_keyboard,
    main_menu_keyboard,
    manager_menu_keyboard,
    scheduled_action_keyboard,
)
from abm_daily_bot.config import Settings, get_settings
from abm_daily_bot.db.models import (
    AIAdvice,
    Blocker,
    DailyAnswer,
    DailySummary,
    OdooOutbox,
    OutboxState,
    User,
    UserRole,
    WeeklyPlan,
)
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.domain import BlockerStatus
from abm_daily_bot.services.ai_advice import AIAdviceService
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.telegram_invites import create_telegram_invite
from abm_daily_bot.services.weekly_store import monday_for

router = Router(name="management")
logger = logging.getLogger(__name__)

INVITE_ROLE_ALIASES = {
    "member": UserRole.MEMBER,
    "участник": UserRole.MEMBER,
    "pm": UserRole.PM,
    "пм": UserRole.PM,
    "tech_lead": UserRole.TECH_LEAD,
    "techlead": UserRole.TECH_LEAD,
    "техлид": UserRole.TECH_LEAD,
}
ROLE_LABELS = {
    UserRole.MEMBER: "участник",
    UserRole.PM: "PM",
    UserRole.TECH_LEAD: "техлид",
}


class InviteStates(StatesGroup):
    odoo_user = State()
    role = State()


def parse_telegram_ids(*values: str) -> set[int]:
    result: set[int] = set()
    for value in values:
        for item in value.split(","):
            if item.strip().isdigit():
                result.add(int(item.strip()))
    return result


def manager_ids(settings: Settings) -> set[int]:
    return parse_telegram_ids(settings.pm_telegram_ids, settings.tech_lead_telegram_ids)


async def telegram_user_is_manager(telegram_user_id: int, settings: Settings) -> bool:
    if telegram_user_id in manager_ids(settings):
        return True
    try:
        session_factory = build_session_factory(settings.database_url)
        async with session_scope(session_factory) as session:
            role = await session.scalar(
                select(User.role).where(
                    User.telegram_user_id == telegram_user_id,
                    User.is_active.is_(True),
                )
            )
        return role in {UserRole.PM, UserRole.TECH_LEAD}
    except Exception:
        logger.exception("Failed to check Telegram manager role")
        return False


def command_task_id(text: str | None) -> int | None:
    parts = (text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def digest_is_weekly(text: str | None) -> bool:
    argument = (text or "").partition(" ")[2].strip().lower()
    return argument.startswith(("week", "недел"))


def previous_workday(value: date) -> date:
    result = value - timedelta(days=1)
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def parse_invite_request(text: str | None) -> tuple[str, UserRole] | None:
    parts = (text or "").split()
    if len(parts) < 2:
        return None
    arguments = parts[1:]
    role = INVITE_ROLE_ALIASES.get(arguments[-1].lower(), UserRole.MEMBER)
    if arguments[-1].lower() in INVITE_ROLE_ALIASES:
        arguments.pop()
    query = " ".join(arguments).strip()
    return (query, role) if query else None


def preferred_open_stage(stages: list[dict[str, object]]) -> dict[str, object] | None:
    open_stages = [stage for stage in stages if not bool(stage.get("fold"))]
    preferred_names = {"в работе", "in progress"}
    return next(
        (
            stage
            for stage in open_stages
            if str(stage.get("name", "")).strip().lower() in preferred_names
        ),
        open_stages[0] if open_stages else None,
    )


def is_acceptance_test_task(name: object) -> bool:
    return str(name or "").strip().upper().startswith("[BOT TEST]")


async def require_manager(message: Message, settings: Settings) -> bool:
    if message.from_user and await telegram_user_is_manager(message.from_user.id, settings):
        return True
    await message.answer("Команда доступна только PM и техлиду.")
    return False


def health_report_text(
    *,
    database_ok: bool,
    odoo_ok: bool,
    active_users: int,
    pending_outbox: int,
    failed_outbox: int,
    ai_configured: bool,
    scope: str,
    ai_provider: str | None = None,
) -> str:
    status = lambda value: "✅" if value else "❌"
    queue_ok = failed_outbox == 0
    return (
        "<strong>Состояние ABM Club Daily</strong>\n"
        f"{status(database_ok)} PostgreSQL: доступна\n"
        f"{status(odoo_ok)} Odoo API: авторизация работает\n"
        f"{status(queue_ok)} Очередь Odoo: {pending_outbox} ожидают, "
        f"{failed_outbox} требуют внимания\n"
        f"{'✅' if ai_configured else '⚠️'} AI: "
        f"{f'подключён ({ai_provider})' if ai_configured else 'локальный fallback'}\n"
        f"👥 Подключено пользователей: {active_users}\n"
        f"📁 Область: {escape(scope or 'Odoo')}"
    )


async def build_live_health_report(settings: Settings) -> str:
    database_ok = False
    active_users = pending_outbox = failed_outbox = 0
    try:
        session_factory = build_session_factory(settings.database_url)
        async with session_scope(session_factory) as session:
            active_users = int(
                await session.scalar(
                    select(func.count()).select_from(User).where(User.is_active.is_(True))
                )
                or 0
            )
            pending_outbox = int(
                await session.scalar(
                    select(func.count())
                    .select_from(OdooOutbox)
                    .where(OdooOutbox.state.in_([OutboxState.PENDING, OutboxState.RETRY]))
                )
                or 0
            )
            failed_outbox = int(
                await session.scalar(
                    select(func.count())
                    .select_from(OdooOutbox)
                    .where(OdooOutbox.state == OutboxState.FAILED)
                )
                or 0
            )
        database_ok = True
    except Exception:
        logger.exception("Health check failed for PostgreSQL")

    try:
        await OdooClient(settings).authenticate()
        odoo_ok = True
    except Exception:
        logger.exception("Health check failed for Odoo")
        odoo_ok = False

    return health_report_text(
        database_ok=database_ok,
        odoo_ok=odoo_ok,
        active_users=active_users,
        pending_outbox=pending_outbox,
        failed_outbox=failed_outbox,
        ai_configured=bool(AIAdviceService.configured_provider(settings)),
        scope=settings.odoo_scope_label,
        ai_provider=AIAdviceService.configured_provider(settings),
    )


@router.message(Command("health"))
async def health(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    await message.answer(await build_live_health_report(settings))


async def build_profile_text(
    settings: Settings,
    *,
    telegram_user_id: int,
    telegram_name: str,
) -> str:
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        user = await session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
    if not user:
        return "Telegram пока не связан с Odoo. Нужна персональная ссылка от PM."
    return (
        "<strong>Твой профиль</strong>\n"
        f"Telegram: {escape(telegram_name)}\n"
        f"Odoo user ID: {user.odoo_user_id}\n"
        f"Роль: {ROLE_LABELS[user.role]}\n"
        f"Область: {escape(settings.odoo_scope_label or 'Odoo')}"
    )


@router.message(Command("whoami"))
async def whoami(message: Message) -> None:
    settings = get_settings()
    if not message.from_user:
        return
    try:
        text = await build_profile_text(
            settings,
            telegram_user_id=message.from_user.id,
            telegram_name=message.from_user.full_name,
        )
    except Exception:  # noqa: BLE001
        await message.answer("Не удалось проверить профиль. Попробуй ещё раз через минуту.")
        return
    await message.answer(text)


async def issue_invitation(
    message: Message,
    *,
    query: str,
    role: UserRole,
    issuer_telegram_user_id: int,
) -> None:
    settings = get_settings()
    try:
        matches = await OdooClient(settings).search_users(query)
    except Exception:
        logger.exception("Failed to search Odoo user for invitation")
        await message.answer("Не удалось найти пользователя Odoo. Попробуй через минуту.")
        return
    if not matches:
        await message.answer("Активный пользователь Odoo по запросу не найден.")
        return
    if len(matches) > 1:
        choices = "\n".join(
            f"• ID {item['id']}: {escape(str(item.get('name') or '-'))} "
            f"({escape(str(item.get('login') or '-'))})"
            for item in matches
        )
        await message.answer(
            "Найдено несколько пользователей. Повтори команду с точным ID:\n" + choices
        )
        return

    odoo_user = matches[0]
    try:
        session_factory = build_session_factory(settings.database_url)
        async with session_scope(session_factory) as session:
            issuer = await session.scalar(
                select(User).where(User.telegram_user_id == issuer_telegram_user_id)
            )
            existing = await session.scalar(
                select(User).where(User.odoo_user_id == int(odoo_user["id"]))
            )
            if existing:
                await message.answer(
                    "Этот Odoo-профиль уже подключён к Telegram. Новая ссылка не создана."
                )
                return
            token, invite = await create_telegram_invite(
                session,
                odoo_user_id=int(odoo_user["id"]),
                odoo_display_name=str(odoo_user.get("name") or query),
                role=role,
                created_by_user_id=issuer.id if issuer else None,
            )
        bot_user = await message.bot.get_me()
    except Exception:
        logger.exception("Failed to create Telegram invitation")
        await message.answer("Не удалось создать приглашение. Попробуй ещё раз.")
        return

    link = f"https://t.me/{bot_user.username}?start={token}"
    await message.answer(
        "<strong>Персональная ссылка создана</strong>\n"
        f"Odoo: {escape(invite.odoo_display_name)} (ID {invite.odoo_user_id})\n"
        f"Роль: {ROLE_LABELS[invite.role]}\n"
        "Действует 7 дней и закрепляется за первым Telegram-аккаунтом.\n\n"
        f'<a href="{escape(link, quote=True)}">Подключить Telegram к Odoo</a>\n\n'
        "Перешли это сообщение только указанному сотруднику."
    )


@router.message(Command("invite"))
async def invite_user(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings) or not message.from_user:
        return
    request = parse_invite_request(message.text)
    if not request:
        await message.answer(
            "Формат: <code>/invite сотрудник@company.ru member</code>\n"
            "Роли: <code>member</code>, <code>pm</code>, <code>tech_lead</code>."
        )
        return
    query, role = request
    await issue_invitation(
        message,
        query=query,
        role=role,
        issuer_telegram_user_id=message.from_user.id,
    )


async def build_digest(
    settings: Settings,
    weekly: bool = False,
    report_date: date | None = None,
) -> str:
    local_today = datetime.now(ZoneInfo(settings.timezone)).date()
    period_end = report_date or local_today
    period_start = monday_for(period_end) if weekly else period_end
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        users = list(
            await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
        )
        answers = list(
            await session.scalars(
                select(DailyAnswer).where(
                    DailyAnswer.answer_date >= period_start,
                    DailyAnswer.answer_date <= period_end,
                )
            )
        )
        summaries = list(
            await session.scalars(
                select(DailySummary).where(
                    DailySummary.summary_date >= period_start,
                    DailySummary.summary_date <= period_end,
                )
            )
        )
        blockers = list(
            await session.scalars(
                select(Blocker).where(
                    Blocker.status.in_([BlockerStatus.OPEN, BlockerStatus.ESCALATED])
                )
            )
        )
        advice_rows = list(await session.scalars(select(AIAdvice)))
        weekly_plans = (
            list(
                await session.scalars(
                    select(WeeklyPlan).where(WeeklyPlan.week_start == period_start)
                )
            )
            if weekly
            else []
        )

    answered_user_ids = {summary.user_id for summary in summaries}
    users_by_id = {user.id: user for user in users}
    advice_by_blocker = {
        advice.blocker_id: (
            advice.recommendation or advice.clarification_question or "рекомендация не сформирована"
        )
        for advice in advice_rows
    }
    responded = [user.display_name for user in users if user.id in answered_user_ids]
    missing = [user.display_name for user in users if user.id not in answered_user_ids]
    period_label = (
        f"неделю {period_start.isoformat()} — {period_end.isoformat()}"
        if weekly
        else period_end.isoformat()
    )
    fresh_blockers = [
        blocker for blocker in blockers if (local_today - blocker.created_at.date()).days <= 2
    ]
    stale_blockers = [
        blocker for blocker in blockers if (local_today - blocker.created_at.date()).days > 2
    ]
    lines = [
        f"<strong>Дайджест за {period_label}</strong>",
        f"Ответили: {escape(', '.join(responded) or 'никто')}",
        f"Не ответили: {escape(', '.join(missing) or 'нет')}",
        f"Ответов по задачам: {len(answers)}",
        "",
        "<strong>Дополнительно вне списка</strong>",
    ]
    extras = [summary for summary in summaries if summary.extra_text]
    if not extras:
        lines.append("Нет")
    for summary in extras:
        user = users_by_id.get(summary.user_id)
        lines.append(
            f"{escape(user.display_name if user else 'Неизвестный участник')}: "
            f"{escape(summary.extra_text or '')}"
        )
    if weekly:
        lines.extend(["", "<strong>Фокус недели</strong>"])
        if not weekly_plans:
            lines.append("Не выбран")
        for plan in weekly_plans:
            user = users_by_id.get(plan.user_id)
            task_ids = ", ".join(f"#{task_id}" for task_id in plan.focus_task_ids)
            strategic = plan.strategic_text or "без стратегического пункта"
            lines.append(
                f"{escape(user.display_name if user else 'Неизвестный участник')}: "
                f"{escape(task_ids or 'задачи не выбраны')}\n"
                f"Стратегическое: {escape(strategic)}"
            )
    lines.extend(
        [
            "",
            "<strong>Открытые затруднения</strong>",
        ]
    )
    if not fresh_blockers:
        lines.append("Нет")
    for blocker in fresh_blockers:
        advice = advice_by_blocker.get(blocker.id, "рекомендация не сформирована")
        user = users_by_id.get(blocker.user_id)
        lines.append(
            f"{escape(user.display_name if user else 'Неизвестный участник')} · "
            f"задача #{blocker.odoo_task_id}: {escape(blocker.text)}\n"
            f"Совет: {escape(advice)}"
        )
    lines.extend(["", "<strong>Эскалации: зависли более 2 дней</strong>"])
    if not stale_blockers:
        lines.append("Нет")
    for blocker in stale_blockers:
        advice = advice_by_blocker.get(blocker.id, "рекомендация не сформирована")
        user = users_by_id.get(blocker.user_id)
        age = (local_today - blocker.created_at.date()).days
        lines.append(
            f"{escape(user.display_name if user else 'Неизвестный участник')} · "
            f"задача #{blocker.odoo_task_id} · {age} дн.: {escape(blocker.text)}\n"
            f"Совет: {escape(advice)}"
        )
    return "\n".join(lines)


async def build_person_status(settings: Settings, query: str) -> str | None:
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        user = await session.scalar(
            select(User).where(User.display_name.ilike(f"%{query}%")).limit(1)
        )
        if not user:
            return None
        answers = list(
            await session.scalars(
                select(DailyAnswer)
                .where(DailyAnswer.user_id == user.id)
                .order_by(DailyAnswer.answer_date.desc(), DailyAnswer.updated_at.desc())
                .limit(10)
            )
        )
        blockers = list(
            await session.scalars(
                select(Blocker).where(
                    Blocker.user_id == user.id,
                    Blocker.status.in_([BlockerStatus.OPEN, BlockerStatus.ESCALATED]),
                )
            )
        )

    lines = [
        f"<strong>Статус: {escape(user.display_name)}</strong>",
        f"Открытых затруднений: {len(blockers)}",
    ]
    if not answers:
        lines.append("Ответов по задачам ещё нет.")
    for answer in answers:
        lines.append(
            f"{answer.answer_date.isoformat()} · задача #{answer.odoo_task_id} · "
            f"{escape(answer.selected_state or '-')}: "
            f"{escape(answer.progress_text or 'без изменений')}"
        )
    return "\n".join(lines)


@router.message(Command("digest"))
async def digest(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    weekly = digest_is_weekly(message.text)
    try:
        text = await build_digest(settings, weekly=weekly)
    except Exception:
        logger.exception("Failed to build requested digest")
        await message.answer("Не удалось собрать дайджест. Попробуй через минуту.")
        return
    await message.answer(text)


@router.message(Command("status"))
async def task_status(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        try:
            text = await build_digest(settings)
        except Exception:
            logger.exception("Failed to build team status")
            await message.answer("Не удалось получить статус. Попробуй через минуту.")
            return
        await message.answer(text)
        return
    try:
        person_status = await build_person_status(settings, parts[1])
        if person_status:
            await message.answer(person_status)
            return
        tasks = await OdooClient(settings).search_open_tasks(parts[1])
    except Exception:
        logger.exception("Failed to search status by person or task")
        await message.answer("Не удалось получить статус. Попробуй через минуту.")
        return
    if not tasks:
        await message.answer("Открытых задач по запросу не найдено.")
        return
    lines = ["<strong>Статус задач</strong>"]
    for task in tasks:
        stage = task.get("stage_id")
        stage_name = stage[1] if isinstance(stage, list | tuple) and len(stage) > 1 else "-"
        project = task.get("project_id")
        project_name = project[1] if isinstance(project, list | tuple) and len(project) > 1 else "-"
        lines.append(
            f"#{task['id']} {escape(task['name'])}\n"
            f"Проект: {escape(project_name)} · этап: {escape(stage_name)} · "
            f"дедлайн: {escape(str(task.get('date_deadline') or 'не указан'))}"
        )
    await message.answer("\n".join(lines))


async def build_deadlines_report(settings: Settings) -> str:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    end = today + timedelta(days=6)
    tasks = await OdooClient(settings).search_deadlines(today.isoformat(), end.isoformat())
    if not tasks:
        return "На ближайшие семь дней дедлайнов нет."
    lines = ["<strong>Дедлайны на 7 дней</strong>"]
    for task in tasks:
        lines.append(
            f"{escape(str(task.get('date_deadline') or '-'))}: #{task['id']} {escape(task['name'])}"
        )
    return "\n".join(lines)


@router.message(Command("deadlines"))
async def deadlines(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    try:
        text = await build_deadlines_report(settings)
    except Exception:
        logger.exception("Failed to load deadlines from Odoo")
        await message.answer("Не удалось получить дедлайны. Попробуй через минуту.")
        return
    await message.answer(text)


async def send_daily_reminders(bot: Bot, settings: Settings) -> tuple[int, int]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
        answered = set(
            await session.scalars(
                select(DailySummary.user_id).where(DailySummary.summary_date == today)
            )
        )
    missing = [user for user in users if user.id not in answered]
    sent = 0
    for user in missing:
        try:
            await bot.send_message(
                user.telegram_user_id,
                "Напоминание: сегодня ещё нет ответа по дейли.",
                reply_markup=scheduled_action_keyboard("daily", "Ответить на дейли"),
            )
            sent += 1
        except Exception:
            logger.exception("Failed to send daily reminder to Telegram user %s", user.id)
            continue
    return sent, len(missing)


@router.message(Command("remind"))
async def remind_non_responders(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    sent, total = await send_daily_reminders(message.bot, settings)
    await message.answer(f"Напоминание отправлено: {sent} из {total}.")


async def allow_manager_callback(callback: CallbackQuery, settings: Settings) -> bool:
    if await telegram_user_is_manager(callback.from_user.id, settings):
        await callback.answer()
        return True
    await callback.answer("Доступно только PM и техлиду", show_alert=True)
    return False


@router.callback_query(F.data == "menu:profile")
async def profile_from_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        text = await build_profile_text(
            get_settings(),
            telegram_user_id=callback.from_user.id,
            telegram_name=callback.from_user.full_name,
        )
    except Exception:
        logger.exception("Failed to load profile from menu")
        text = "Не удалось проверить профиль. Попробуй ещё раз через минуту."
    await callback.message.answer(text)


@router.callback_query(F.data == "menu:home")
async def home_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    is_manager = await telegram_user_is_manager(callback.from_user.id, settings)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "<strong>Главное меню</strong>\nВыбери действие:",
            reply_markup=main_menu_keyboard(is_manager=is_manager),
        )


@router.callback_query(F.data == "menu:manager")
async def manager_panel(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "<strong>Панель PM</strong>\nСводка и управление командой:",
            reply_markup=manager_menu_keyboard(),
        )


@router.callback_query(F.data == "menu:status")
async def team_status_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.answer(await build_digest(settings))
    except Exception:
        logger.exception("Failed to build team status from menu")
        await callback.message.answer("Не удалось получить статус. Попробуй через минуту.")


@router.callback_query(F.data == "menu:deadlines")
async def deadlines_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.answer(await build_deadlines_report(settings))
    except Exception:
        logger.exception("Failed to load deadlines from menu")
        await callback.message.answer("Не удалось получить дедлайны. Попробуй через минуту.")


@router.callback_query(F.data.in_({"menu:digest:day", "menu:digest:week"}))
async def digest_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.answer(
            await build_digest(settings, weekly=callback.data == "menu:digest:week")
        )
    except Exception:
        logger.exception("Failed to build digest from menu")
        await callback.message.answer("Не удалось собрать дайджест. Попробуй через минуту.")


@router.callback_query(F.data == "menu:remind")
async def remind_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if not isinstance(callback.message, Message):
        return
    try:
        sent, total = await send_daily_reminders(callback.bot, settings)
    except Exception:
        logger.exception("Failed to send reminders from menu")
        await callback.message.answer("Не удалось отправить напоминания. Попробуй через минуту.")
        return
    await callback.message.answer(f"Напоминание отправлено: {sent} из {total}.")


@router.callback_query(F.data == "menu:health")
async def health_from_menu(callback: CallbackQuery) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if isinstance(callback.message, Message):
        await callback.message.answer(await build_live_health_report(settings))


@router.callback_query(F.data == "menu:invite")
async def invite_help_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        return
    if isinstance(callback.message, Message):
        await state.set_state(InviteStates.odoo_user)
        await callback.message.answer(
            "<strong>Подключение сотрудника</strong>\n"
            "Пришли рабочую почту сотрудника или точный Odoo ID."
        )


@router.message(InviteStates.odoo_user, F.text)
async def invite_user_from_menu(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        await state.clear()
        return
    query = (message.text or "").strip()
    if not query or query.startswith("/"):
        await message.answer("Пришли рабочую почту или числовой Odoo ID.")
        return
    await state.update_data(invite_query=query)
    await state.set_state(InviteStates.role)
    await message.answer("Какую роль выдать?", reply_markup=invite_role_keyboard())


@router.callback_query(InviteStates.role, F.data.startswith("invite:role:"))
async def invite_role_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    if not await allow_manager_callback(callback, settings):
        await state.clear()
        return
    if not isinstance(callback.message, Message) or not callback.data:
        return
    role_value = callback.data.rsplit(":", maxsplit=1)[-1]
    try:
        role = UserRole(role_value)
    except ValueError:
        await callback.message.answer("Неизвестная роль. Начни подключение заново.")
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await issue_invitation(
        callback.message,
        query=str(data["invite_query"]),
        role=role,
        issuer_telegram_user_id=callback.from_user.id,
    )


@router.callback_query(InviteStates.role, F.data == "invite:cancel")
async def cancel_invite_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Подключение отменено")
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "<strong>Панель PM</strong>", reply_markup=manager_menu_keyboard()
        )


@router.message(Command("test_reopen"))
async def test_reopen(message: Message) -> None:
    settings = get_settings()
    if settings.app_env != "local":
        await message.answer("Тестовая команда недоступна в этом окружении.")
        return
    task_id = command_task_id(message.text)
    if task_id is None:
        await message.answer("Формат команды: /test_reopen 4")
        return
    if not message.from_user:
        return
    odoo_user_id = settings.odoo_user_id_for(message.from_user.id)
    if odoo_user_id <= 0:
        await message.answer("Для пользователя не настроена связь с Odoo.")
        return
    try:
        client = OdooClient(settings)
        tasks = await client.call(
            "project.task",
            "read",
            [task_id],
            fields=["name", "project_id", "user_ids", "state"],
        )
        if not tasks:
            await message.answer("Тестовая задача не найдена.")
            return
        task = tasks[0]
        if not is_acceptance_test_task(task.get("name")):
            await message.answer("Эта команда работает только для задач с префиксом [BOT TEST].")
            return
        if odoo_user_id not in task.get("user_ids", []):
            await message.answer("Задача не назначена текущему Odoo-пользователю.")
            return
        project = task.get("project_id")
        project_id = int(project[0]) if isinstance(project, list | tuple) and project else 0
        stage = preferred_open_stage(await client.search_task_stages(project_id))
        values: dict[str, object] = {"state": "01_in_progress"}
        if stage is not None:
            values["stage_id"] = int(stage["id"])
        await client.call("project.task", "write", [task_id], values)
    except Exception:
        logger.exception("Failed to reopen local test task")
        await message.answer("Не удалось открыть тестовую задачу. Проверь локальные логи.")
        return
    stage_name = str(stage["name"]) if stage is not None else "открытый этап"
    await message.answer(
        f"Тестовая задача #{task_id} снова открыта на этапе «{stage_name}». Теперь отправь /daily."
    )

