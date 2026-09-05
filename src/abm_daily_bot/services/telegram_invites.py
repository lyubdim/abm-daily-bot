from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from abm_daily_bot.db.models import TelegramInvite, User, UserRole
from abm_daily_bot.services.daily_store import claim_invited_user

DEFAULT_INVITE_TTL = timedelta(days=7)


def invite_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


async def create_telegram_invite(
    session: AsyncSession,
    *,
    odoo_user_id: int,
    odoo_display_name: str,
    role: UserRole,
    created_by_user_id: int | None,
    now: datetime | None = None,
    token: str | None = None,
) -> tuple[str, TelegramInvite]:
    issued_at = now or datetime.now(UTC)
    raw_token = token or token_urlsafe(24)
    invite = TelegramInvite(
        token_hash=invite_token_hash(raw_token),
        odoo_user_id=odoo_user_id,
        odoo_display_name=odoo_display_name,
        role=role,
        expires_at=issued_at + DEFAULT_INVITE_TTL,
        created_by_user_id=created_by_user_id,
    )
    session.add(invite)
    await session.flush()
    return raw_token, invite


async def claim_telegram_invite(
    session: AsyncSession,
    *,
    token: str,
    telegram_user_id: int,
    telegram_display_name: str,
    legacy_bot_user_id: int | None = None,
    now: datetime | None = None,
) -> tuple[User, TelegramInvite]:
    current_time = now or datetime.now(UTC)
    invite = await session.scalar(
        select(TelegramInvite)
        .where(TelegramInvite.token_hash == invite_token_hash(token))
        .with_for_update()
    )
    if not invite:
        raise ValueError("Ссылка приглашения недействительна или устарела")

    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= current_time:
        raise ValueError("Срок действия приглашения истёк")

    if invite.used_by_telegram_user_id is not None:
        if invite.used_by_telegram_user_id != telegram_user_id:
            raise ValueError("Эта персональная ссылка уже использована")
        user = await session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        if not user:
            raise ValueError("Привязка приглашения повреждена; запроси новую ссылку")
        return user, invite

    user = await claim_invited_user(
        session,
        telegram_user_id=telegram_user_id,
        odoo_user_id=invite.odoo_user_id,
        display_name=telegram_display_name,
        role=invite.role,
        legacy_bot_user_id=legacy_bot_user_id,
    )
    invite.used_by_telegram_user_id = telegram_user_id
    invite.used_at = current_time
    await session.flush()
    return user, invite
