import logging
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from abm_daily_bot.config import Settings, get_settings
from abm_daily_bot.db.models import AIAdvice, Blocker, DailyAnswer, User
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.domain import BlockerStatus
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.weekly_store import monday_for

router = Router(name="management")
logger = logging.getLogger(__name__)


def parse_telegram_ids(*values: str) -> set[int]:
    result: set[int] = set()
    for value in values:
        for item in value.split(","):
            if item.strip().isdigit():
                result.add(int(item.strip()))
    return result


def manager_ids(settings: Settings) -> set[int]:
    return parse_telegram_ids(settings.pm_telegram_ids, settings.tech_lead_telegram_ids)


async def require_manager(message: Message, settings: Settings) -> bool:
    if message.from_user and message.from_user.id in manager_ids(settings):
        return True
    await message.answer("Команда доступна только PM и техлиду.")
    return False


async def build_digest(settings: Settings, weekly: bool = False) -> str:
    local_today = datetime.now(ZoneInfo(settings.timezone)).date()
    period_start = monday_for(local_today) if weekly else local_today
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        users = list(
            await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
        )
        answers = list(
            await session.scalars(
                select(DailyAnswer).where(DailyAnswer.answer_date >= period_start)
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

    answered_user_ids = {answer.user_id for answer in answers}
    advice_by_blocker = {advice.blocker_id: advice.recommendation for advice in advice_rows}
    responded = [user.display_name for user in users if user.id in answered_user_ids]
    missing = [user.display_name for user in users if user.id not in answered_user_ids]
    period_label = "неделю" if weekly else "день"
    lines = [
        f"<strong>Дайджест за {period_label}</strong>",
        f"Ответили: {escape(', '.join(responded) or 'никто')}",
        f"Не ответили: {escape(', '.join(missing) or 'нет')}",
        f"Ответов по задачам: {len(answers)}",
        "",
        "<strong>Открытые затруднения</strong>",
    ]
    if not blockers:
        lines.append("Нет")
    for blocker in blockers:
        advice = advice_by_blocker.get(blocker.id, "рекомендация не сформирована")
        age = (local_today - blocker.created_at.date()).days
        marker = " [более 2 дней]" if age > 2 else ""
        lines.append(
            f"Задача #{blocker.odoo_task_id}{marker}: {escape(blocker.text)}\n"
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
    weekly = len((message.text or "").split()) > 1 and "week" in (message.text or "").lower()
    try:
        text = await build_digest(settings, weekly=weekly)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось собрать дайджест: {escape(str(exc))}")
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
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"Не удалось получить статус: {escape(str(exc))}")
            return
        await message.answer(text)
        return
    try:
        person_status = await build_person_status(settings, parts[1])
        if person_status:
            await message.answer(person_status)
            return
        tasks = await OdooClient(settings).search_open_tasks(parts[1])
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось получить статус: {escape(str(exc))}")
        return
    if not tasks:
        await message.answer("Открытых задач по запросу не найдено.")
        return
    lines = ["<strong>Статус задач</strong>"]
    for task in tasks:
        stage = task.get("stage_id")
        stage_name = stage[1] if isinstance(stage, list | tuple) and len(stage) > 1 else "-"
        lines.append(f"#{task['id']} {escape(task['name'])}: {escape(stage_name)}")
    await message.answer("\n".join(lines))


@router.message(Command("deadlines"))
async def deadlines(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    end = today + timedelta(days=6)
    try:
        tasks = await OdooClient(settings).search_deadlines(
            today.isoformat(), end.isoformat()
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось получить дедлайны: {escape(str(exc))}")
        return
    if not tasks:
        await message.answer("На ближайшие семь дней дедлайнов нет.")
        return
    lines = ["<strong>Дедлайны на 7 дней</strong>"]
    for task in tasks:
        lines.append(
            f"{escape(str(task.get('date_deadline') or '-'))}: "
            f"#{task['id']} {escape(task['name'])}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("remind"))
async def remind_non_responders(message: Message) -> None:
    settings = get_settings()
    if not await require_manager(message, settings):
        return
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
        answered = set(
            await session.scalars(
                select(DailyAnswer.user_id).where(DailyAnswer.answer_date == today)
            )
        )
    missing = [user for user in users if user.id not in answered]
    sent = 0
    for user in missing:
        try:
            await message.bot.send_message(
                user.telegram_user_id,
                "Напоминание: сегодня ещё нет ответа по дейли. Отправь /daily.",
            )
            sent += 1
        except Exception:
            logger.exception("Failed to send daily reminder to Telegram user %s", user.id)
            continue
    await message.answer(f"Напоминание отправлено: {sent} из {len(missing)}.")

