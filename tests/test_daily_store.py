from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from abm_daily_bot.db.models import OdooOutbox, User, UserRole
from abm_daily_bot.services.daily_store import (
    active_user_bindings,
    claim_invited_user,
    get_or_create_user,
    queue_daily_odoo_sync,
)


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
async def test_personal_invite_cannot_take_over_existing_odoo_binding() -> None:
    existing = User(
        telegram_user_id=111,
        odoo_user_id=584,
        display_name="Already linked",
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, existing])
    session.flush = AsyncMock()

    with pytest.raises(ValueError, match="уже использована"):
        await claim_invited_user(
            session,
            telegram_user_id=222,
            odoo_user_id=584,
            display_name="Another user",
            role=UserRole.PM,
        )

    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_invite_repairs_legacy_bot_callback_binding() -> None:
    existing = User(
        telegram_user_id=9000,
        odoo_user_id=1382,
        display_name="Bot account",
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, existing])
    session.flush = AsyncMock()

    result = await claim_invited_user(
        session,
        telegram_user_id=111,
        odoo_user_id=1382,
        display_name="Participant",
        role=UserRole.MEMBER,
        legacy_bot_user_id=9000,
    )

    assert result.telegram_user_id == 111
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_recovery_can_rebind_stale_odoo_owner() -> None:
    existing = User(
        telegram_user_id=333,
        odoo_user_id=1382,
        display_name="Stale local binding",
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, existing])
    session.flush = AsyncMock()

    result = await claim_invited_user(
        session,
        telegram_user_id=111,
        odoo_user_id=1382,
        display_name="Current administrator",
        role=UserRole.PM,
        allow_rebind=True,
    )

    assert result is existing
    assert result.telegram_user_id == 111
    assert result.role == UserRole.PM
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_user_bindings_restore_invites_after_restart() -> None:
    active = User(telegram_user_id=111, odoo_user_id=584, display_name="PM")
    inactive = User(telegram_user_id=222, odoo_user_id=999, display_name="Former")
    inactive.is_active = False
    session = MagicMock()
    session.scalars = AsyncMock(return_value=[active])

    assert await active_user_bindings(session) == {111: 584}


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
        stage_id=22,
        comment="test",
    )

    assert legacy_state.idempotency_key == "daily:odoo:94:4:2026-09-05:state"
    assert legacy_comment.idempotency_key == "daily:odoo:94:4:2026-09-05:comment"
    assert [call.kwargs["idempotency_key"] for call in outbox.enqueue.await_args_list] == [
        "daily:odoo:94:4:2026-09-05:state",
        "daily:odoo:94:4:2026-09-05:comment",
    ]
    comment_call = outbox.enqueue.await_args_list[1].kwargs
    assert comment_call["model"] == "mail.message"
    assert comment_call["method"] == "create"
    assert comment_call["arguments"] == [
        {
            "model": "project.task",
            "res_id": 4,
            "body": "test",
            "message_type": "comment",
        }
    ]
    assert outbox.enqueue.await_args_list[0].kwargs["arguments"] == [
        [4],
        {"stage_id": 22, "state": "01_in_progress"},
    ]
