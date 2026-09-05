import json
from datetime import date
from types import SimpleNamespace

import pytest

from abm_daily_bot.config import Settings
from abm_daily_bot.domain import OdooTask, TaskContextForAdvice
from abm_daily_bot.services.ai_advice import AIAdviceService


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


def advice_context() -> TaskContextForAdvice:
    return TaskContextForAdvice(
        task=OdooTask(
            id=4,
            name="Подключить Telegram к Odoo",
            project_name="ABM Club",
            stage_name="В работе",
            deadline=date(2026, 9, 11),
            url=None,
            assignee_odoo_ids=(94,),
        ),
        blocker_text="Odoo возвращает 403",
        recent_updates=("Проверил API key",),
        days_in_current_stage=3,
    )


async def test_ai_advice_uses_responses_api_without_storage() -> None:
    responses = FakeResponses(
        json.dumps(
            {
                "recommendation": "Проверь права API-ключа на project.task.write.",
                "clarification_question": None,
            }
        )
    )
    client = SimpleNamespace(responses=responses)
    service = AIAdviceService("gpt-5.1-mini", "test-key", client=client)

    result = await service.make_advice(advice_context())

    assert result.recommendation == "Проверь права API-ключа на project.task.write."
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == "gpt-5.1-mini"
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"
    assert "Odoo возвращает 403" in str(responses.kwargs["input"])


async def test_ai_advice_rejects_empty_response() -> None:
    client = SimpleNamespace(
        responses=FakeResponses(json.dumps({"recommendation": "", "clarification_question": None}))
    )
    service = AIAdviceService("gpt-5.1-mini", "test-key", client=client)

    with pytest.raises(RuntimeError, match="either advice"):
        await service.make_advice(advice_context())


async def test_ai_advice_can_request_one_clarification() -> None:
    client = SimpleNamespace(
        responses=FakeResponses(
            json.dumps(
                {
                    "recommendation": "",
                    "clarification_question": "Какой HTTP-код возвращает Odoo?",
                },
                ensure_ascii=False,
            )
        )
    )
    service = AIAdviceService("gpt-5-mini", "test-key", client=client)

    result = await service.make_advice(advice_context())

    assert result.needs_clarification is True
    assert result.recommendation == ""
    assert result.clarification_question == "Какой HTTP-код возвращает Odoo?"


def test_auto_provider_prefers_yandex_alice() -> None:
    settings = Settings(
        ai_provider="auto",
        yandex_api_key="yandex-key",
        yandex_folder_id="folder-123",
        openai_api_key="openai-key",
    )

    service = AIAdviceService.from_settings(settings)

    assert service.provider == "yandex"
    assert service.model == "gpt://folder-123/aliceai-llm"
    assert str(service.client.base_url) == "https://ai.api.cloud.yandex.net/v1/"


def test_explicit_yandex_provider_requires_both_credentials() -> None:
    settings = Settings(ai_provider="yandex", yandex_api_key="key-only")

    assert AIAdviceService.configured_provider(settings) is None
    with pytest.raises(RuntimeError, match="credentials"):
        AIAdviceService.from_settings(settings)


def test_auto_provider_falls_back_to_openai() -> None:
    settings = Settings(openai_api_key="openai-key", ai_model="gpt-test")

    service = AIAdviceService.from_settings(settings)

    assert service.provider == "openai"
    assert service.model == "gpt-test"
