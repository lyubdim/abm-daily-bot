from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import User, WeeklyPlan


def monday_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


async def upsert_weekly_plan(
    session: AsyncSession,
    *,
    user: User,
    week_start: date,
    focus_task_ids: list[int],
    strategic_text: str | None,
) -> WeeklyPlan:
    plan = await session.scalar(
        select(WeeklyPlan).where(
            WeeklyPlan.user_id == user.id,
            WeeklyPlan.week_start == week_start,
        )
    )
    if not plan:
        plan = WeeklyPlan(user_id=user.id, week_start=week_start)
        session.add(plan)

    plan.focus_task_ids = focus_task_ids
    plan.strategic_text = strategic_text
    await session.flush()
    return plan

