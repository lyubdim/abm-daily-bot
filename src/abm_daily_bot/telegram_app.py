import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from abm_daily_bot.bot.daily import router
from abm_daily_bot.bot.management import router as management_router
from abm_daily_bot.bot.weekly import router as weekly_router
from abm_daily_bot.config import get_settings
from abm_daily_bot.db.session import build_session_factory, initialize_database, session_scope
from abm_daily_bot.services.odoo_client import OdooClient
from abm_daily_bot.services.outbox import OdooOutboxService

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
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    dispatcher.include_router(weekly_router)
    dispatcher.include_router(management_router)
    outbox_worker = asyncio.create_task(run_outbox_worker())
    try:
        await dispatcher.start_polling(bot)
    finally:
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

