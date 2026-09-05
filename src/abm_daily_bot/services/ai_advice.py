import json
from typing import Any

from openai import AsyncOpenAI

from abm_daily_bot.config import Settings
from abm_daily_bot.domain import AdviceResult, TaskContextForAdvice
from abm_daily_bot.prompts import ADVICE_SYSTEM_PROMPT, build_advice_user_prompt

MAX_ADVICE_LENGTH = 1200
YANDEX_AI_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
ADVICE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "task_blocker_advice",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "recommendation": {"type": "string"},
            "clarification_question": {"type": ["string", "null"]},
        },
        "required": ["recommendation", "clarification_question"],
        "additionalProperties": False,
    },
}


class AIAdviceService:
    def __init__(
        self,
        model: str,
        api_key: str,
        client: Any | None = None,
        *,
        provider: str = "openai",
        base_url: str | None = None,
        project: str | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        client_options: dict[str, str] = {"api_key": api_key}
        if base_url:
            client_options["base_url"] = base_url
        if project:
            client_options["project"] = project
        self.client = client or AsyncOpenAI(**client_options)

    @staticmethod
    def configured_provider(settings: Settings) -> str | None:
        yandex_ready = bool(settings.yandex_api_key and settings.yandex_folder_id)
        openai_ready = bool(settings.openai_api_key)
        if settings.ai_provider == "yandex":
            return "yandex" if yandex_ready else None
        if settings.ai_provider == "openai":
            return "openai" if openai_ready else None
        if yandex_ready:
            return "yandex"
        if openai_ready:
            return "openai"
        return None

    @classmethod
    def from_settings(cls, settings: Settings) -> "AIAdviceService":
        provider = cls.configured_provider(settings)
        if provider == "yandex":
            model = settings.yandex_ai_model
            if not model.startswith("gpt://"):
                model = f"gpt://{settings.yandex_folder_id}/{model}"
            return cls(
                model=model,
                api_key=settings.yandex_api_key,
                provider="yandex",
                base_url=YANDEX_AI_BASE_URL,
                project=settings.yandex_folder_id,
            )
        if provider == "openai":
            return cls(
                model=settings.ai_model,
                api_key=settings.openai_api_key,
                provider="openai",
            )
        raise RuntimeError("AI provider credentials are not configured")

    @classmethod
    def configured_model(cls, settings: Settings) -> str | None:
        provider = cls.configured_provider(settings)
        if provider == "yandex":
            return settings.yandex_ai_model
        if provider == "openai":
            return settings.ai_model
        return None

    async def make_advice(self, context: TaskContextForAdvice) -> AdviceResult:
        user_prompt = build_advice_user_prompt(context)
        response = await self.client.responses.create(
            model=self.model,
            instructions=ADVICE_SYSTEM_PROMPT,
            input=user_prompt,
            text={"format": ADVICE_RESPONSE_FORMAT},
            store=False,
        )
        try:
            payload = json.loads(response.output_text)
            recommendation = str(payload.get("recommendation") or "").strip()
            question = str(payload.get("clarification_question") or "").strip() or None
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError("AI returned an invalid structured response") from exc
        if bool(recommendation) == bool(question):
            raise RuntimeError("AI must return either advice or one clarification question")
        return AdviceResult(
            recommendation=recommendation[:MAX_ADVICE_LENGTH],
            clarification_question=question[:MAX_ADVICE_LENGTH] if question else None,
        )
