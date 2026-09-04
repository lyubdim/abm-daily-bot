from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import DailyAnswer, User
from abm_daily_bot.domain import DailyAnswerStatus
from abm_daily_bot.services.outbox import OdooOutboxService


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    odoo_user_id: int,
    display_name: str,
) -> User:
    user = await session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    if user:
        user.odoo_user_id = odoo_user_id
        user.display_name = display_name
        return user

    user = User(
        telegram_user_id=telegram_user_id,
        odoo_user_id=odoo_user_id,
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    return user


async def upsert_daily_answer(
    session: AsyncSession,
    *,
    user: User,
    task_id: int,
    answer_date: date,
    progress: str | None,
    task_state: str,
    result_url: str | None,
) -> DailyAnswer:
    answer = await session.scalar(
        select(DailyAnswer).where(
            DailyAnswer.user_id == user.id,
            DailyAnswer.odoo_task_id == task_id,
            DailyAnswer.answer_date == answer_date,
        )
    )
    answer_status = (
        DailyAnswerStatus.NO_CHANGES
        if (progress or "").strip().lower() == "без изменений"
        else DailyAnswerStatus.PROGRESS
    )
    if not answer:
        answer = DailyAnswer(
            user_id=user.id,
            odoo_task_id=task_id,
            answer_date=answer_date,
            status=answer_status,
        )
        session.add(answer)

    answer.status = answer_status
    answer.progress_text = progress
    answer.selected_state = task_state
    answer.result_url = result_url
    await session.flush()
    return answer


async def queue_daily_odoo_sync(
    session: AsyncSession,
    outbox: OdooOutboxService,
    *,
    telegram_user_id: int,
    task_id: int,
    answer_date: date,
    task_state: str,
    comment: str,
) -> None:
    key_prefix = f"daily:{telegram_user_id}:{task_id}:{answer_date.isoformat()}"
    await outbox.enqueue(
        session,
        idempotency_key=f"{key_prefix}:state",
        model="project.task",
        method="write",
        arguments=[[task_id], {"state": task_state}],
    )
    await outbox.enqueue(
        session,
        idempotency_key=f"{key_prefix}:comment",
        model="project.task",
        method="message_post",
        arguments=[[task_id]],
        keyword_arguments={
            "body": comment,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_comment",
        },
    )

