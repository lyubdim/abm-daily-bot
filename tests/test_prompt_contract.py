from datetime import date

from abm_daily_bot.domain import OdooTask, TaskContextForAdvice
from abm_daily_bot.prompts import ADVICE_SYSTEM_PROMPT, build_advice_user_prompt


def test_advice_prompt_demands_specific_step_or_one_question() -> None:
    assert "конкрет" in ADVICE_SYSTEM_PROMPT.lower()
    assert "ровно один уточняющий вопрос" in ADVICE_SYSTEM_PROMPT.lower()


def test_advice_prompt_contains_task_context() -> None:
    context = TaskContextForAdvice(
        task=OdooTask(
            id=42,
            name="Настроить интеграцию Telegram и Odoo",
            project_name="ABM Club",
            stage_name="В работе",
            deadline=date(2026, 9, 10),
            url="https://abmapex.ru/odoo/task/42",
            assignee_odoo_ids=(7,),
        ),
        blocker_text="Не понимаю, какой API Odoo использовать.",
        recent_updates=("Проверил Telegram webhook",),
        days_in_current_stage=3,
    )

    prompt = build_advice_user_prompt(context)

    assert "Настроить интеграцию Telegram и Odoo" in prompt
    assert "2026-09-10" in prompt
    assert "Не понимаю, какой API Odoo использовать." in prompt
    assert "Проверил Telegram webhook" in prompt


