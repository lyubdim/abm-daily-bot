from datetime import date
from types import SimpleNamespace

import pytest

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
    responses = FakeResponses("Проверь права API-ключа на project.task.write.")
    client = SimpleNamespace(responses=responses)
    service = AIAdviceService("gpt-5.1-mini", "test-key", client=client)

    result = await service.make_advice(advice_context())

    assert result.recommendation == "Проверь права API-ключа на project.task.write."
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == "gpt-5.1-mini"
    assert "Odoo возвращает 403" in str(responses.kwargs["input"])


async def test_ai_advice_rejects_empty_response() -> None:
    client = SimpleNamespace(responses=FakeResponses("  "))
    service = AIAdviceService("gpt-5.1-mini", "test-key", client=client)

    with pytest.raises(RuntimeError, match="empty"):
        await service.make_advice(advice_context())

