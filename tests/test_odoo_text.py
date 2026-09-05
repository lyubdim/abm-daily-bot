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


@pytest.mark.asyncio
async def test_daily_tasks_are_limited_to_configured_portfolio_projects() -> None:
    client = OdooClient(Settings(odoo_project_ids=[1329, 1330, 1335, 1336]))
    client.call = AsyncMock(return_value=[])

    await client.search_open_tasks_for_user(1382)

    assert ["project_id", "in", [1329, 1330, 1335, 1336]] in (
        client.call.await_args.args[2]
    )

