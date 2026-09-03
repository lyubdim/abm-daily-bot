from abm_daily_bot.domain import TaskContextForAdvice


ADVICE_SYSTEM_PROMPT = """
Ты помогаешь команде ABM Club сдвигать конкретные задачи.
Дай короткий, прикладной следующий шаг по именно этой задаче.
Не давай общую мотивацию, длинные рассуждения и абстрактные советы.
Если без дополнительных данных нельзя выбрать следующий шаг, задай ровно один уточняющий вопрос.
Ответ должен быть пригоден для отправки в Telegram и сохранения в карточку задачи Odoo.
""".strip()


def build_advice_user_prompt(context: TaskContextForAdvice) -> str:
    task = context.task
    updates = "\n".join(f"- {item}" for item in context.recent_updates) or "- нет недавних обновлений"
    deadline = task.deadline.isoformat() if task.deadline else "не указан"
    days_in_stage = (
        str(context.days_in_current_stage)
        if context.days_in_current_stage is not None
        else "неизвестно"
    )

    return f"""
Задача: {task.name}
Проект: {task.project_name or "не указан"}
Текущий статус: {task.stage_name or "не указан"}
Дедлайн: {deadline}
Дней в текущем статусе: {days_in_stage}

Затруднение участника:
{context.blocker_text}

Недавние обновления по этой задаче:
{updates}

Сформулируй один конкретный следующий шаг или один уточняющий вопрос.
""".strip()


