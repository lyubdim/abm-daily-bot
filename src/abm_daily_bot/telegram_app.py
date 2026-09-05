import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from abm_daily_bot.bot.daily import router
from abm_daily_bot.bot.management import router as management_router
from abm_daily_bot.bot.weekly import router as weekly_router
from abm_daily_bot.config import get_settings
from abm_daily_bot.db.session import build_session_factory, initialize_database, session_scope
from abm_daily_bot.jobs import build_scheduler
from abm_daily_bot.services.daily_store import active_user_bindings
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.outbox import OdooOutboxService
from abm_daily_bot.services.scheduled_jobs import ScheduledJobs

logger = logging.getLogger(__name__)


async def run_outbox_worker() -> None:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    outbox = OdooOutboxService(OdooClient(settings))
    while True:
        try:
            async with session_scope(session_factory) as session:
                await outbox.process_due(session)
        except Exception:
            logger.exception("Odoo outbox worker iteration failed")
        await asyncio.sleep(15)


async def run_polling() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    await initialize_database(settings)
    session_factory = build_session_factory(settings.database_url)
    async with session_scope(session_factory) as session:
        persisted_bindings = await active_user_bindings(session)
    settings.telegram_odoo_user_map = {
        **persisted_bindings,
        **settings.telegram_odoo_user_map,
    }
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands(
        [
            BotCommand(command="daily", description="Пройти дейли по задачам"),
            BotCommand(command="weekly", description="Выбрать фокус недели"),
            BotCommand(command="blockers", description="Открытые затруднения"),
            BotCommand(command="status", description="Статус команды или задачи"),
            BotCommand(command="deadlines", description="Дедлайны на 7 дней"),
            BotCommand(command="digest", description="Дайджест для PM"),
            BotCommand(command="cancel", description="Остановить текущий опрос"),
        ]
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    dispatcher.include_router(weekly_router)
    dispatcher.include_router(management_router)
    jobs = ScheduledJobs(bot, settings)
    scheduler = build_scheduler(
        settings.timezone,
        callbacks={
            "daily_cycle": jobs.daily_cycle,
            "weekly_planning": jobs.weekly_planning,
            "remind_non_responders": jobs.remind_non_responders,
            "pm_digest": jobs.pm_digest,
            "blocker_escalations": jobs.blocker_escalations,
            "assignment_poll": jobs.assignment_poll,
        },
    )
    scheduler.start()
    outbox_worker = asyncio.create_task(run_outbox_worker())
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        outbox_worker.cancel()
        with suppress(asyncio.CancelledError):
            await outbox_worker


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()

