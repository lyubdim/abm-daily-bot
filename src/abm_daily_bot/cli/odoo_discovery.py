import asyncio
import json
from typing import Any

from abm_daily_bot.config import get_settings
from abm_daily_bot.services.odoo_client import OdooClient


INTERESTING_TASK_FIELDS = (
    "name",
    "project_id",
    "user_ids",
    "stage_id",
    "date_deadline",
    "date_last_stage_update",
    "access_url",
    "is_closed",
    "active",
)


async def discover() -> dict[str, Any]:
    settings = get_settings()
    client = OdooClient(settings)
    version = await client.version()
    uid = await client.authenticate()

    all_fields = await client.call(
        "project.task",
        "fields_get",
        [],
        attributes=["string", "type", "relation", "required", "readonly"],
    )
    task_fields = {
        name: all_fields[name]
        for name in INTERESTING_TASK_FIELDS
        if name in all_fields
    }

    stages = await client.call(
        "project.task.type",
        "search_read",
        [],
        fields=["name", "sequence", "fold"],
        limit=100,
        order="sequence,id",
    )

    sample_fields = [name for name in INTERESTING_TASK_FIELDS if name in all_fields]
    domain: list[list[Any]] = []
    if "user_ids" in all_fields:
        domain.append(["user_ids", "in", [uid]])
    tasks = await client.call(
        "project.task",
        "search_read",
        domain,
        fields=sample_fields,
        limit=5,
        order="write_date desc",
    )

    return {
        "base_url": client.base_url,
        "database": settings.odoo_database,
        "version": version,
        "authenticated_user_id": uid,
        "task_fields": task_fields,
        "stages": stages,
        "sample_tasks": tasks,
    }


def main() -> None:
    try:
        result = asyncio.run(discover())
    except Exception as exc:
        raise SystemExit(f"Odoo discovery failed: {type(exc).__name__}: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

