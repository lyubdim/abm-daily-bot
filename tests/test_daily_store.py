from unittest.mock import AsyncMock, MagicMock

import pytest

from abm_daily_bot.db.models import User
from abm_daily_bot.services.daily_store import get_or_create_user


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

