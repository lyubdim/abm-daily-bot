from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(timezone_name: str = "Asia/Yekaterinburg") -> AsyncIOScheduler:
    timezone = ZoneInfo(timezone_name)
    scheduler = AsyncIOScheduler(timezone=timezone)

    scheduler.add_job(
        func=lambda: None,
        trigger=CronTrigger(day_of_week="mon-fri", hour=12, minute=0, timezone=timezone),
        id="daily_cycle",
        name="Daily task-status cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: None,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=timezone),
        id="weekly_planning",
        name="Weekly planning",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: None,
        trigger=CronTrigger(hour=14, minute=0, timezone=timezone),
        id="remind_non_responders",
        name="Remind non-responders",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: None,
        trigger=CronTrigger(hour=10, minute=0, timezone=timezone),
        id="pm_digest",
        name="PM daily digest",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: None,
        trigger=CronTrigger(hour=18, minute=0, timezone=timezone),
        id="blocker_escalations",
        name="Blocker escalation check",
        replace_existing=True,
    )
    return scheduler


