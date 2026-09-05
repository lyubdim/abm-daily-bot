import logging
from datetime import UTC, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from abm_daily_bot.bot.keyboards import scheduled_action_keyboard
from abm_daily_bot.bot.management import build_digest, manager_ids, previous_workday
from abm_daily_bot.config import Settings
from abm_daily_bot.db.models import (
    AIAdvice,
    Blocker,
    DailySummary,
    TaskCache,
    User,
    UserRole,
)
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.domain import BlockerStatus
from abm_daily_bot.services.odoo_client import OdooClient

logger = logging.getLogger(__name__)


def new_assignee_ids(previous: list[int], current: list[int]) -> set[int]:
    return set(current) - set(previous)


class ScheduledJobs:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = build_session_factory(settings.database_url)

    async def _active_users(self) -> list[User]:
        async with session_scope(self.session_factory) as session:
            rows = await session.scalars(select(User).where(User.is_active.is_(True)))
            return list(rows)

    async def _send_to_users(self, text: str, users: list[User]) -> int:
        sent = 0
        for user in users:
            try:
                await self.bot.send_message(user.telegram_user_id, text)
                sent += 1
            except Exception:
                logger.exception("Scheduled Telegram message failed for user %s", user.id)
        return sent

    async def _manager_telegram_ids(self) -> set[int]:
        async with session_scope(self.session_factory) as session:
            persisted = await session.scalars(
                select(User.telegram_user_id).where(
                    User.is_active.is_(True),
                    User.role.in_([UserRole.PM, UserRole.TECH_LEAD]),
                )
            )
            return manager_ids(self.settings) | set(persisted)

    async def daily_cycle(self) -> None:
        users = await self._active_users()
        for user in users:
            try:
                await self.bot.send_message(
                    user.telegram_user_id,
                    "Время дейли. Пройди открытые задачи по очереди.",
                    reply_markup=scheduled_action_keyboard("daily", "Начать дейли"),
                )
            except Exception:
                logger.exception("Daily start failed for Telegram user %s", user.id)

    async def weekly_planning(self) -> None:
        users = await self._active_users()
        for user in users:
            try:
                await self.bot.send_message(
                    user.telegram_user_id,
                    "Пора выбрать фокус недели из открытых задач.",
                    reply_markup=scheduled_action_keyboard("weekly", "Выбрать фокус недели"),
                )
            except Exception:
                logger.exception("Weekly start failed for Telegram user %s", user.id)

    async def remind_non_responders(self) -> None:
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        async with session_scope(self.session_factory) as session:
            users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
            answered = set(
                await session.scalars(
                    select(DailySummary.user_id).where(DailySummary.summary_date == today)
                )
            )
        missing = [user for user in users if user.id not in answered]
        await self._send_to_users(
            "Напоминание: сегодня ещё нет ответа по дейли. Отправь /daily.", missing
        )

    async def pm_digest(self) -> None:
        recipients = await self._manager_telegram_ids()
        if not recipients:
            return
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        digest = await build_digest(self.settings, report_date=previous_workday(today))
        for telegram_id in recipients:
            try:
                await self.bot.send_message(telegram_id, digest)
            except Exception:
                logger.exception("Scheduled PM digest failed for Telegram ID %s", telegram_id)

    async def blocker_escalations(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=2)
        async with session_scope(self.session_factory) as session:
            blockers = list(
                await session.scalars(
                    select(Blocker).where(
                        Blocker.status == BlockerStatus.OPEN,
                        Blocker.created_at < cutoff,
                    )
                )
            )
            user_ids = {blocker.user_id for blocker in blockers}
            users = {
                user.id: user
                for user in await session.scalars(select(User).where(User.id.in_(user_ids)))
            }
            blocker_ids = {blocker.id for blocker in blockers}
            advice_by_blocker = {
                advice.blocker_id: advice.recommendation
                for advice in await session.scalars(
                    select(AIAdvice).where(AIAdvice.blocker_id.in_(blocker_ids))
                )
            }
            for blocker in blockers:
                blocker.status = BlockerStatus.ESCALATED
                blocker.escalated_at = datetime.now(UTC)

        recipients = await self._manager_telegram_ids()
        for blocker in blockers:
            user_name = users.get(blocker.user_id)
            advice = advice_by_blocker.get(blocker.id, "рекомендация не сформирована")
            text = (
                "<strong>Эскалация: затруднение более 2 дней</strong>\n"
                f"Участник: {escape(user_name.display_name if user_name else 'неизвестен')}\n"
                f"Задача Odoo #{blocker.odoo_task_id}\n"
                f"Проблема: {escape(blocker.text)}\n"
                f"AI-совет: {escape(advice)}"
            )
            for telegram_id in recipients:
                try:
                    await self.bot.send_message(telegram_id, text)
                except Exception:
                    logger.exception("Blocker escalation failed for Telegram ID %s", telegram_id)

    async def assignment_poll(self) -> None:
        tasks = await OdooClient(self.settings).search_open_tasks()
        notifications: list[tuple[int, str, str]] = []
        async with session_scope(self.session_factory) as session:
            has_baseline = await session.scalar(select(TaskCache.id).limit(1)) is not None
            users = {
                user.odoo_user_id: user
                for user in await session.scalars(select(User).where(User.is_active.is_(True)))
            }
            for task in tasks:
                cache = await session.scalar(
                    select(TaskCache).where(TaskCache.odoo_task_id == task["id"])
                )
                current_assignees = [int(item) for item in task.get("user_ids") or []]
                previous_assignees = cache.assignee_odoo_ids if cache else []
                added_assignees = (
                    new_assignee_ids(previous_assignees, current_assignees)
                    if has_baseline
                    else set()
                )
                project = task.get("project_id")
                stage = task.get("stage_id")
                project_name = (
                    project[1] if isinstance(project, list | tuple) and len(project) > 1 else None
                )
                stage_name = (
                    stage[1] if isinstance(stage, list | tuple) and len(stage) > 1 else None
                )
                task_url = f"/odoo/project.task/{task['id']}"
                if str(task_url).startswith("/"):
                    task_url = f"{str(self.settings.odoo_base_url).rstrip('/')}{task_url}"
                if not cache:
                    cache = TaskCache(odoo_task_id=task["id"], name=task["name"])
                    session.add(cache)
                cache.name = task["name"]
                cache.project_name = project_name
                cache.stage_name = stage_name
                cache.task_url = str(task_url)
                cache.assignee_odoo_ids = current_assignees
                cache.raw_payload = task
                deadline = task.get("date_deadline")
                cache.deadline = datetime.fromisoformat(str(deadline)).date() if deadline else None

                text = (
                    "<strong>Тебе назначена задача</strong>\n"
                    f"{escape(task['name'])}\n"
                    f"Проект: {escape(project_name or '-')}\n"
                    f"Дедлайн: {escape(str(deadline or 'не указан'))}"
                )
                for odoo_user_id in added_assignees:
                    user = users.get(odoo_user_id)
                    if user:
                        notifications.append((user.telegram_user_id, text, str(task_url)))

        for telegram_id, text, task_url in notifications:
            try:
                await self.bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="Открыть в Odoo ↗", url=task_url)]
                        ]
                    ),
                )
            except Exception:
                logger.exception(
                    "Task assignment notification failed for Telegram ID %s", telegram_id
                )
