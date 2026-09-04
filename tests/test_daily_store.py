from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from abm_daily_bot.db.models import OdooOutbox, User
from abm_daily_bot.services.daily_store import get_or_create_user, queue_daily_odoo_sync


@pytest.mark.asyncio
async def test_existing_odoo_user_is_rebound_to_current_telegram() -> None:
    existing = User(
        telegram_user_id=111,
        odoo_user_id=94,
        display_name="Previous test user",
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, existing])
    session.flush = AsyncMock()

    result = await get_or_create_user(
        session,
        telegram_user_id=222,
        odoo_user_id=94,
        display_name="Current test user",
    )

    assert result is existing
    assert result.telegram_user_id == 222
    assert result.display_name == "Current test user"
    session.add.assert_not_called()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_outbox_adopts_latest_legacy_keys_for_odoo_user() -> None:
    legacy_state = OdooOutbox(idempotency_key="daily:111:4:2026-09-05:state")
    legacy_comment = OdooOutbox(idempotency_key="daily:111:4:2026-09-05:comment")
    session = MagicMock()
    session.scalar = AsyncMock(
        side_effect=[None, legacy_state, None, legacy_comment]
    )
    session.flush = AsyncMock()
    outbox = MagicMock()
    outbox.enqueue = AsyncMock()

    await queue_daily_odoo_sync(
        session,
        outbox,
        odoo_user_id=94,
        task_id=4,
        answer_date=date(2026, 9, 5),
        task_state="01_in_progress",
        comment="test",
    )

    assert legacy_state.idempotency_key == "daily:odoo:94:4:2026-09-05:state"
    assert legacy_comment.idempotency_key == "daily:odoo:94:4:2026-09-05:comment"
    assert [call.kwargs["idempotency_key"] for call in outbox.enqueue.await_args_list] == [
        "daily:odoo:94:4:2026-09-05:state",
        "daily:odoo:94:4:2026-09-05:comment",
    ]
    assert outbox.enqueue.await_args_list[1].kwargs["keyword_arguments"]["body_is_html"] is True

