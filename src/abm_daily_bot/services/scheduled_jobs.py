import logging
from datetime import UTC, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select

from abm_daily_bot.bot.management import build_digest, manager_ids
from abm_daily_bot.config import Settings
from abm_daily_bot.db.models import AIAdvice, Blocker, DailyAnswer, User
from abm_daily_bot.db.session import build_session_factory, session_scope
from abm_daily_bot.domain import BlockerStatus

logger = logging.getLogger(__name__)


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

    async def daily_cycle(self) -> None:
        users = await self._active_users()
        await self._send_to_users(
            "Время дейли. Отправь /daily, чтобы пройти задачи по очереди.", users
        )

    async def weekly_planning(self) -> None:
        users = await self._active_users()
        await self._send_to_users(
            "Пора выбрать фокус недели. Отправь /weekly.", users
        )

    async def remind_non_responders(self) -> None:
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        async with session_scope(self.session_factory) as session:
            users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
            answered = set(
                await session.scalars(
                    select(DailyAnswer.user_id).where(DailyAnswer.answer_date == today)
                )
            )
        missing = [user for user in users if user.id not in answered]
        await self._send_to_users(
            "Напоминание: сегодня ещё нет ответа по дейли. Отправь /daily.", missing
        )

    async def pm_digest(self) -> None:
        recipients = manager_ids(self.settings)
        if not recipients:
            return
        digest = await build_digest(self.settings)
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

        recipients = manager_ids(self.settings)
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
                    logger.exception(
                        "Blocker escalation failed for Telegram ID %s", telegram_id
                    )

