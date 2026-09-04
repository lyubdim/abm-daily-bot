from unittest.mock import AsyncMock

import pytest

from abm_daily_bot.config import Settings
from abm_daily_bot.services.odoo_client import OdooClient, html_to_text


def test_html_to_text_extracts_odoo_chatter_content() -> None:
    assert html_to_text("<p>Готово: <strong>проверил API</strong></p>") == (
        "Готово: проверил API"
    )


@pytest.mark.asyncio
async def test_project_stages_exclude_unrelated_global_stages() -> None:
    client = OdooClient(Settings())
    client.call = AsyncMock(return_value=[{"id": 22, "name": "К выполнению"}])

    stages = await client.search_task_stages(1)

    assert stages == [{"id": 22, "name": "К выполнению"}]
    assert client.call.await_args.args[2] == [["project_ids", "in", [1]]]

