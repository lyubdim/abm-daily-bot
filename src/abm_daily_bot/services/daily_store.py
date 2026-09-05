from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import DailyAnswer, DailySummary, OdooOutbox, User, UserRole
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

    user = await session.scalar(
        select(User).where(User.odoo_user_id == odoo_user_id)
    )
    if user:
        user.telegram_user_id = telegram_user_id
        user.display_name = display_name
        await session.flush()
        return user

    user = User(
        telegram_user_id=telegram_user_id,
        odoo_user_id=odoo_user_id,
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    return user


async def claim_invited_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    odoo_user_id: int,
    display_name: str,
    role: UserRole,
    legacy_bot_user_id: int | None = None,
    allow_rebind: bool = False,
) -> User:
    telegram_user = await session.scalar(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    odoo_user = await session.scalar(select(User).where(User.odoo_user_id == odoo_user_id))
    if telegram_user and telegram_user.odoo_user_id != odoo_user_id:
        raise ValueError("Telegram-профиль уже связан с другим пользователем Odoo")
    if odoo_user and odoo_user.telegram_user_id != telegram_user_id:
        if odoo_user.telegram_user_id == legacy_bot_user_id or allow_rebind:
            odoo_user.telegram_user_id = telegram_user_id
        else:
            raise ValueError("Эта персональная ссылка уже использована")

    user = telegram_user or odoo_user
    if not user:
        user = User(
            telegram_user_id=telegram_user_id,
            odoo_user_id=odoo_user_id,
            display_name=display_name,
        )
        session.add(user)
    user.display_name = display_name
    user.role = role
    user.is_active = True
    await session.flush()
    return user


async def active_user_bindings(session: AsyncSession) -> dict[int, int]:
    users = await session.scalars(select(User).where(User.is_active.is_(True)))
    return {user.telegram_user_id: user.odoo_user_id for user in users}


async def upsert_daily_answer(
    session: AsyncSession,
    *,
    user: User,
    task_id: int,
    answer_date: date,
    progress: str | None,
    task_state: str,
    stage_id: int,
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
    answer.selected_stage_id = stage_id
    answer.result_url = result_url
    await session.flush()
    return answer


async def queue_daily_odoo_sync(
    session: AsyncSession,
    outbox: OdooOutboxService,
    *,
    odoo_user_id: int,
    task_id: int,
    answer_date: date,
    task_state: str,
    stage_id: int,
    comment: str,
) -> None:
    key_prefix = f"daily:odoo:{odoo_user_id}:{task_id}:{answer_date.isoformat()}"
    legacy_prefix = f"daily:%:{task_id}:{answer_date.isoformat()}"
    await _adopt_legacy_outbox_item(
        session,
        stable_key=f"{key_prefix}:state",
        legacy_pattern=f"{legacy_prefix}:state",
    )
    await outbox.enqueue(
        session,
        idempotency_key=f"{key_prefix}:state",
        model="project.task",
        method="write",
        arguments=[[task_id], {"stage_id": stage_id, "state": task_state}],
    )
    await _adopt_legacy_outbox_item(
        session,
        stable_key=f"{key_prefix}:comment",
        legacy_pattern=f"{legacy_prefix}:comment",
    )
    await outbox.enqueue(
        session,
        idempotency_key=f"{key_prefix}:comment",
        model="mail.message",
        method="create",
        arguments=[
            {
                "model": "project.task",
                "res_id": task_id,
                "body": comment,
                "message_type": "comment",
            }
        ],
    )


async def _adopt_legacy_outbox_item(
    session: AsyncSession,
    *,
    stable_key: str,
    legacy_pattern: str,
) -> None:
    existing = await session.scalar(
        select(OdooOutbox).where(OdooOutbox.idempotency_key == stable_key)
    )
    if existing:
        return
    legacy = await session.scalar(
        select(OdooOutbox)
        .where(OdooOutbox.idempotency_key.like(legacy_pattern))
        .order_by(OdooOutbox.updated_at.desc(), OdooOutbox.id.desc())
    )
    if legacy:
        legacy.idempotency_key = stable_key
        await session.flush()


async def upsert_daily_summary(
    session: AsyncSession,
    *,
    user: User,
    summary_date: date,
    extra_text: str | None,
) -> DailySummary:
    summary = await session.scalar(
        select(DailySummary).where(
            DailySummary.user_id == user.id,
            DailySummary.summary_date == summary_date,
        )
    )
    if not summary:
        summary = DailySummary(user_id=user.id, summary_date=summary_date)
        session.add(summary)
    summary.extra_text = extra_text
    await session.flush()
    return summary
