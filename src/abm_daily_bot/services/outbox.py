from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import OdooOutbox, OutboxState
from abm_daily_bot.services.odoo_client import OdooClient, OdooUnavailableError


def retry_delay(attempt_count: int) -> timedelta:
    seconds = min(15 * (2 ** max(attempt_count - 1, 0)), 3600)
    return timedelta(seconds=seconds)


class OdooOutboxService:
    def __init__(self, odoo: OdooClient) -> None:
        self.odoo = odoo

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        idempotency_key: str,
        model: str,
        method: str,
        arguments: list[Any] | None = None,
        keyword_arguments: dict[str, Any] | None = None,
    ) -> OdooOutbox:
        existing = await session.scalar(
            select(OdooOutbox).where(OdooOutbox.idempotency_key == idempotency_key)
        )
        if existing:
            if method == "message_post" and existing.remote_record_id:
                existing.model = "mail.message"
                existing.method = "write"
                existing.arguments = [
                    [existing.remote_record_id],
                    {"body": (keyword_arguments or {}).get("body", "")},
                ]
                existing.keyword_arguments = {}
            else:
                existing.model = model
                existing.method = method
                existing.arguments = arguments or []
                existing.keyword_arguments = keyword_arguments or {}
            existing.state = OutboxState.PENDING
            existing.next_attempt_at = None
            existing.last_error = None
            existing.sent_at = None
            return existing

        item = OdooOutbox(
            idempotency_key=idempotency_key,
            model=model,
            method=method,
            arguments=arguments or [],
            keyword_arguments=keyword_arguments or {},
        )
        session.add(item)
        await session.flush()
        return item

    async def process_due(self, session: AsyncSession, limit: int = 50) -> int:
        now = datetime.now(UTC)
        rows = await session.scalars(
            select(OdooOutbox)
            .where(
                OdooOutbox.state.in_([OutboxState.PENDING, OutboxState.RETRY]),
                or_(OdooOutbox.next_attempt_at.is_(None), OdooOutbox.next_attempt_at <= now),
            )
            .order_by(OdooOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        processed = 0
        for item in rows:
            await self._deliver(item, now)
            processed += 1
        await session.commit()
        return processed

    async def _deliver(self, item: OdooOutbox, now: datetime) -> None:
        item.attempt_count += 1
        try:
            result = await self.odoo.call(
                item.model,
                item.method,
                *item.arguments,
                **item.keyword_arguments,
            )
        except (OdooUnavailableError, TimeoutError, OSError) as exc:
            item.state = OutboxState.RETRY
            item.next_attempt_at = now + retry_delay(item.attempt_count)
            item.last_error = str(exc)[:4000]
        # A malformed operation must be isolated instead of stopping the worker loop.
        except Exception as exc:  # noqa: BLE001
            item.state = OutboxState.FAILED
            item.last_error = str(exc)[:4000]
        else:
            if item.method == "message_post" and isinstance(result, int):
                item.remote_record_id = result
            item.state = OutboxState.SENT
            item.sent_at = now
            item.next_attempt_at = None
            item.last_error = None

