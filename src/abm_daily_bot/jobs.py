from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


def _noop() -> None:
    return None


def build_scheduler(
    timezone_name: str = "Asia/Yekaterinburg",
    callbacks: Mapping[str, Callable[[], Any]] | None = None,
) -> AsyncIOScheduler:
    timezone = ZoneInfo(timezone_name)
    scheduler = AsyncIOScheduler(timezone=timezone)
    job_callbacks = callbacks or {}

    scheduler.add_job(
        func=job_callbacks.get("daily_cycle", _noop),
        trigger=CronTrigger(day_of_week="mon-fri", hour=12, minute=0, timezone=timezone),
        id="daily_cycle",
        name="Daily task-status cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        func=job_callbacks.get("weekly_planning", _noop),
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=timezone),
        id="weekly_planning",
        name="Weekly planning",
        replace_existing=True,
    )
    scheduler.add_job(
        func=job_callbacks.get("remind_non_responders", _noop),
        trigger=CronTrigger(day_of_week="mon-fri", hour=14, minute=0, timezone=timezone),
        id="remind_non_responders",
        name="Remind non-responders",
        replace_existing=True,
    )
    scheduler.add_job(
        func=job_callbacks.get("pm_digest", _noop),
        trigger=CronTrigger(day_of_week="mon-fri", hour=10, minute=0, timezone=timezone),
        id="pm_digest",
        name="PM daily digest",
        replace_existing=True,
    )
    scheduler.add_job(
        func=job_callbacks.get("blocker_escalations", _noop),
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone=timezone),
        id="blocker_escalations",
        name="Blocker escalation check",
        replace_existing=True,
    )
    scheduler.add_job(
        func=job_callbacks.get("assignment_poll", _noop),
        trigger=IntervalTrigger(minutes=1, timezone=timezone),
        id="assignment_poll",
        name="Odoo task-assignment polling fallback",
        replace_existing=True,
    )
    return scheduler
