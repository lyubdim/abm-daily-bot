from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import AIAdvice, Blocker, User
from abm_daily_bot.domain import BlockerStatus
from abm_daily_bot.services.outbox import OdooOutboxService


async def upsert_open_blocker(
    session: AsyncSession,
    *,
    user: User,
    task_id: int,
    text: str,
) -> Blocker:
    blocker = await session.scalar(
        select(Blocker)
        .where(
            Blocker.user_id == user.id,
            Blocker.odoo_task_id == task_id,
            Blocker.status == BlockerStatus.OPEN,
        )
        .order_by(Blocker.created_at.desc())
    )
    if not blocker:
        blocker = Blocker(user_id=user.id, odoo_task_id=task_id, text=text)
        session.add(blocker)
    else:
        blocker.text = text
    await session.flush()
    return blocker


async def upsert_ai_advice(
    session: AsyncSession,
    *,
    blocker: Blocker,
    recommendation: str,
    model: str,
) -> AIAdvice:
    advice = await session.scalar(
        select(AIAdvice).where(AIAdvice.blocker_id == blocker.id).order_by(AIAdvice.id.desc())
    )
    if not advice:
        advice = AIAdvice(blocker_id=blocker.id, model=model)
        session.add(advice)
    advice.recommendation = recommendation
    advice.model = model
    await session.flush()
    return advice


async def open_blockers_for_user(session: AsyncSession, user_id: int) -> list[Blocker]:
    rows = await session.scalars(
        select(Blocker)
        .where(
            Blocker.user_id == user_id,
            Blocker.status.in_([BlockerStatus.OPEN, BlockerStatus.ESCALATED]),
        )
        .order_by(Blocker.created_at.desc())
    )
    return list(rows)


async def resolve_blocker(
    session: AsyncSession,
    *,
    blocker_id: int,
    user_id: int,
    resolution_url: str | None,
) -> tuple[Blocker, AIAdvice | None]:
    blocker = await session.scalar(
        select(Blocker).where(Blocker.id == blocker_id, Blocker.user_id == user_id)
    )
    if not blocker:
        raise LookupError("Затруднение не найдено")
    blocker.status = BlockerStatus.RESOLVED
    blocker.resolved_at = datetime.now(UTC)
    blocker.resolution_url = resolution_url
    advice = await session.scalar(
        select(AIAdvice).where(AIAdvice.blocker_id == blocker.id).order_by(AIAdvice.id.desc())
    )
    await session.flush()
    return blocker, advice


async def queue_blocker_odoo_sync(
    session: AsyncSession,
    outbox: OdooOutboxService,
    *,
    blocker: Blocker,
    comment: str,
) -> None:
    await outbox.enqueue(
        session,
        idempotency_key=f"blocker:{blocker.id}:comment",
        model="project.task",
        method="message_post",
        arguments=[[blocker.odoo_task_id]],
        keyword_arguments={
            "body": comment,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_comment",
        },
    )

