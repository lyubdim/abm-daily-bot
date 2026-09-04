import asyncio
import ssl
import xmlrpc.client
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from abm_daily_bot.config import Settings


class OdooUnavailableError(RuntimeError):
    """Raised when Odoo cannot be reached or returns a temporary failure."""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    return " ".join(parser.parts)


class OdooClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = str(settings.odoo_base_url).rstrip("/")

    async def version(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=15,
            verify=self.settings.odoo_verify_ssl,
        ) as client:
            response = await client.post(
                f"{self.base_url}/web/webclient/version_info",
                json={"jsonrpc": "2.0", "method": "call", "params": {}},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result", data)

    async def call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.settings.odoo_api_style == "json2":
            return await self.json2_call(model, method, kwargs)
        return await self.xmlrpc_call(model, method, *args, **kwargs)

    async def json2_call(self, model: str, method: str, payload: dict[str, Any]) -> Any:
        if not self.settings.odoo_api_key:
            raise ValueError("ODOO_API_KEY is required for JSON-2 API calls")

        headers = {
            "Authorization": f"bearer {self.settings.odoo_api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "abm-daily-bot",
        }
        if self.settings.odoo_database:
            headers["X-Odoo-Database"] = self.settings.odoo_database

        async with httpx.AsyncClient(
            timeout=30,
            verify=self.settings.odoo_verify_ssl,
        ) as client:
            response = await client.post(
                f"{self.base_url}/json/2/{model}/{method}",
                headers=headers,
                json=payload,
            )
            if response.status_code >= 500:
                raise OdooUnavailableError(response.text)
            response.raise_for_status()
            return response.json()

    def _xmlrpc_context(self) -> ssl.SSLContext | None:
        parsed_url = urlparse(self.base_url)
        if parsed_url.scheme != "https" or self.settings.odoo_verify_ssl:
            return None
        return ssl._create_unverified_context()

    async def _xmlrpc_authenticate(self) -> int:
        if not self.settings.odoo_database:
            raise ValueError("ODOO_DATABASE is required for XML-RPC API calls")
        if not self.settings.odoo_username:
            raise ValueError("ODOO_USERNAME is required for XML-RPC API calls")
        if not self.settings.odoo_password:
            raise ValueError("ODOO_PASSWORD or Odoo API key is required for XML-RPC API calls")

        context = self._xmlrpc_context()

        def authenticate() -> int:
            common = xmlrpc.client.ServerProxy(
                f"{self.base_url}/xmlrpc/2/common",
                context=context,
                allow_none=True,
            )
            return common.authenticate(
                self.settings.odoo_database,
                self.settings.odoo_username,
                self.settings.odoo_password,
                {},
            )

        uid = await asyncio.to_thread(authenticate)
        if not uid:
            raise PermissionError("Odoo XML-RPC authentication failed")
        return uid

    async def authenticate(self) -> int:
        if self.settings.odoo_api_style == "json2":
            raise NotImplementedError("JSON-2 uses bearer authentication per request")
        return await self._xmlrpc_authenticate()

    async def xmlrpc_call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        uid = await self._xmlrpc_authenticate()
        context = self._xmlrpc_context()

        def execute_kw() -> Any:
            models = xmlrpc.client.ServerProxy(
                f"{self.base_url}/xmlrpc/2/object",
                context=context,
                allow_none=True,
            )
            return models.execute_kw(
                self.settings.odoo_database,
                uid,
                self.settings.odoo_password,
                model,
                method,
                list(args),
                kwargs,
            )

        return await asyncio.to_thread(execute_kw)

    async def search_open_tasks_for_user(self, odoo_user_id: int) -> list[dict[str, Any]]:
        return await self.call(
            "project.task",
            "search_read",
            [["user_ids", "in", [odoo_user_id]], ["is_closed", "=", False]],
            fields=[
                "name",
                "project_id",
                "user_ids",
                "stage_id",
                "state",
                "date_deadline",
                "date_last_stage_update",
                "access_url",
            ],
        )

    async def search_open_tasks(self, name_query: str | None = None) -> list[dict[str, Any]]:
        domain: list[list[Any]] = [["is_closed", "=", False]]
        if name_query:
            domain.append(["name", "ilike", name_query])
        options: dict[str, Any] = {
            "fields": [
                "name",
                "project_id",
                "user_ids",
                "stage_id",
                "state",
                "date_deadline",
                "access_url",
            ]
        }
        if name_query:
            options["limit"] = 20
        return await self.call(
            "project.task",
            "search_read",
            domain,
            **options,
        )

    async def search_task_stages(self, project_id: int) -> list[dict[str, Any]]:
        return await self.call(
            "project.task.type",
            "search_read",
            [
                "|",
                ["project_ids", "=", False],
                ["project_ids", "in", [project_id]],
            ],
            fields=["name", "fold", "sequence"],
            order="sequence asc, id asc",
        )

    async def search_deadlines(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        return await self.call(
            "project.task",
            "search_read",
            [
                ["is_closed", "=", False],
                ["date_deadline", ">=", date_from],
                ["date_deadline", "<=", date_to],
            ],
            fields=["name", "project_id", "user_ids", "stage_id", "date_deadline"],
            order="date_deadline asc",
        )

    async def update_task_stage(self, task_id: int, stage_id: int) -> bool:
        return await self.call(
            "project.task",
            "write",
            [task_id],
            {"stage_id": stage_id},
        )

    async def update_task_state(self, task_id: int, task_state: str) -> bool:
        return await self.call(
            "project.task",
            "write",
            [task_id],
            {"state": task_state},
        )

    async def post_task_comment(self, task_id: int, body: str) -> int:
        return await self.call(
            "project.task",
            "message_post",
            [task_id],
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

    async def recent_task_updates(self, task_id: int, limit: int = 5) -> list[str]:
        messages = await self.call(
            "mail.message",
            "search_read",
            [
                ["model", "=", "project.task"],
                ["res_id", "=", task_id],
                ["message_type", "in", ["comment", "email"]],
            ],
            fields=["body", "date"],
            order="date desc",
            limit=limit,
        )
        return [
            text
            for message in reversed(messages)
            if (text := html_to_text(str(message.get("body") or "")))
        ]

