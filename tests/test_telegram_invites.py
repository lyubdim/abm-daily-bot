from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from abm_daily_bot.db.models import TelegramInvite, User, UserRole
from abm_daily_bot.services.telegram_invites import (
    claim_telegram_invite,
    create_telegram_invite,
    invite_token_hash,
)


@pytest.mark.asyncio
async def test_created_invite_stores_hash_instead_of_raw_token() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)

    token, invite = await create_telegram_invite(
        session,
        odoo_user_id=105,
        odoo_display_name="Team Member",
        role=UserRole.MEMBER,
        created_by_user_id=1,
        now=now,
        token="one-time-secret",
    )

    assert token == "one-time-secret"
    assert invite.token_hash == invite_token_hash(token)
    assert token not in invite.token_hash
    assert invite.expires_at == now + timedelta(days=7)
    session.add.assert_called_once_with(invite)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_claim_creates_persistent_user_binding() -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    invite = TelegramInvite(
        token_hash=invite_token_hash("valid-token"),
        odoo_user_id=105,
        odoo_display_name="Team Member",
        role=UserRole.MEMBER,
        expires_at=now + timedelta(days=1),
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[invite, None, None])
    session.flush = AsyncMock()

    user, claimed = await claim_telegram_invite(
        session,
        token="valid-token",
        telegram_user_id=700,
        telegram_display_name="Telegram Name",
        now=now,
    )

    assert claimed is invite
    assert user.telegram_user_id == 700
    assert user.odoo_user_id == 105
    assert invite.used_by_telegram_user_id == 700
    assert invite.used_at == now


@pytest.mark.asyncio
async def test_used_invite_rejects_another_telegram_account() -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    invite = TelegramInvite(
        token_hash=invite_token_hash("used-token"),
        odoo_user_id=105,
        odoo_display_name="Team Member",
        role=UserRole.MEMBER,
        expires_at=now + timedelta(days=1),
        used_by_telegram_user_id=700,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=invite)

    with pytest.raises(ValueError, match="уже использована"):
        await claim_telegram_invite(
            session,
            token="used-token",
            telegram_user_id=701,
            telegram_display_name="Another Account",
            now=now,
        )


@pytest.mark.asyncio
async def test_expired_invite_is_rejected() -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    invite = TelegramInvite(
        token_hash=invite_token_hash("expired-token"),
        odoo_user_id=105,
        odoo_display_name="Team Member",
        role=UserRole.MEMBER,
        expires_at=now - timedelta(seconds=1),
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=invite)

    with pytest.raises(ValueError, match="истёк"):
        await claim_telegram_invite(
            session,
            token="expired-token",
            telegram_user_id=700,
            telegram_display_name="Telegram Name",
            now=now,
        )


@pytest.mark.asyncio
async def test_reopening_same_invite_is_idempotent_for_owner() -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    invite = TelegramInvite(
        token_hash=invite_token_hash("same-owner-token"),
        odoo_user_id=105,
        odoo_display_name="Team Member",
        role=UserRole.MEMBER,
        expires_at=now + timedelta(days=1),
        used_by_telegram_user_id=700,
    )
    user = User(telegram_user_id=700, odoo_user_id=105, display_name="Owner")
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[invite, user])

    result, _ = await claim_telegram_invite(
        session,
        token="same-owner-token",
        telegram_user_id=700,
        telegram_display_name="Owner",
        now=now,
    )

    assert result is user
