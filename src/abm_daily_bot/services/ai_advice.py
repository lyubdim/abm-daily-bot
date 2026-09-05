import json
from typing import Any

from openai import AsyncOpenAI

from abm_daily_bot.domain import AdviceResult, TaskContextForAdvice
from abm_daily_bot.prompts import ADVICE_SYSTEM_PROMPT, build_advice_user_prompt

MAX_ADVICE_LENGTH = 1200
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
    ) -> None:
        self.model = model
        self.client = client or AsyncOpenAI(api_key=api_key)

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
