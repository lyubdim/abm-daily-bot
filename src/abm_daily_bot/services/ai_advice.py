from abm_daily_bot.domain import AdviceResult, TaskContextForAdvice
from abm_daily_bot.prompts import ADVICE_SYSTEM_PROMPT, build_advice_user_prompt


class AIAdviceService:
    def __init__(self, model: str) -> None:
        self.model = model

    async def make_advice(self, context: TaskContextForAdvice) -> AdviceResult:
        user_prompt = build_advice_user_prompt(context)
        # TODO: call OpenAI Responses API with structured output:
        # {"recommendation": string, "clarification_question": string | null}
        _ = (ADVICE_SYSTEM_PROMPT, user_prompt, self.model)
        return AdviceResult(
            recommendation=(
                "Проверь самый маленький воспроизводимый шаг по задаче и напиши, "
                "какой именно результат блокирует следующий статус."
            )
        )


