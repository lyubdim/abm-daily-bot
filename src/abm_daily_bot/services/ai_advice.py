from typing import Any

from openai import AsyncOpenAI

from abm_daily_bot.domain import AdviceResult, TaskContextForAdvice
from abm_daily_bot.prompts import ADVICE_SYSTEM_PROMPT, build_advice_user_prompt


MAX_ADVICE_LENGTH = 1200


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
            store=False,
        )
        advice = response.output_text.strip()
        if not advice:
            raise RuntimeError("AI returned an empty recommendation")
        return AdviceResult(recommendation=advice[:MAX_ADVICE_LENGTH])

