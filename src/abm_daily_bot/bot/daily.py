from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router(name="daily")

DEMO_TASKS = [
    {
        "id": 101,
        "name": "Подготовить структуру дейли-бота",
        "project": "ABM Club",
        "deadline": "2026-09-08",
    },
    {
        "id": 102,
        "name": "Проверить интеграцию с Odoo",
        "project": "ABM Club",
        "deadline": "2026-09-10",
    },
]


class DailyStates(StatesGroup):
    progress = State()
    status = State()
    blocker = State()
    result_url = State()
    extra = State()


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К выполнению", callback_data="daily:stage:todo"),
                InlineKeyboardButton(text="В работе", callback_data="daily:stage:working"),
            ],
            [InlineKeyboardButton(text="Готово", callback_data="daily:stage:done")],
            [
                InlineKeyboardButton(
                    text="Есть затруднение",
                    callback_data="daily:blocker",
                ),
                InlineKeyboardButton(text="Пропустить", callback_data="daily:skip"),
            ],
            [
                InlineKeyboardButton(
                    text="Пропустить остальные",
                    callback_data="daily:skip_rest",
                )
            ],
        ]
    )


async def ask_current_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task_index = data.get("task_index", 0)
    tasks = data.get("tasks", DEMO_TASKS)
    if task_index >= len(tasks):
        await state.set_state(DailyStates.extra)
        await message.answer("Делал что-то ещё, не из списка? Напиши текст или /skip.")
        return

    task = tasks[task_index]
    await state.set_state(DailyStates.progress)
    await message.answer(
        f"Задача {task_index + 1}/{len(tasks)}\n"
        f"{task['name']}\n"
        f"Проект: {task['project']}\n"
        f"Дедлайн: {task['deadline']}\n\n"
        "Что сделал / какой прогресс? Можно написать «без изменений»."
    )


async def move_to_next_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(task_index=data.get("task_index", 0) + 1, progress=None)
    await ask_current_task(message, state)


def demo_advice(task_name: str, blocker_text: str) -> str:
    return (
        f"Следующий шаг по задаче «{task_name}»: выпиши один проверяемый результат, "
        f"которого не хватает из-за проблемы «{blocker_text}», и запроси его у "
        "конкретного ответственного сегодня."
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет! Я собираю статусы по задачам ABM Club.\n\n"
        "Команды:\n"
        "/daily — пройти тестовый дейли\n"
        "/cancel — остановить текущий опрос"
    )


@router.message(Command("daily"))
async def begin_daily(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(tasks=DEMO_TASKS, task_index=0, answers=[])
    await message.answer("Начинаем дейли в demo-режиме. Данные в Odoo не изменяются.")
    await ask_current_task(message, state)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Опрос остановлен. Чтобы начать заново, отправь /daily.")


@router.message(DailyStates.progress, F.text)
async def receive_progress(message: Message, state: FSMContext) -> None:
    await state.update_data(progress=message.text)
    await state.set_state(DailyStates.status)
    await message.answer("Выбери статус задачи:", reply_markup=status_keyboard())


@router.callback_query(DailyStates.status, F.data == "daily:blocker")
async def request_blocker(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DailyStates.blocker)
    if isinstance(callback.message, Message):
        await callback.message.answer("Опиши затруднение одним сообщением.")


@router.message(DailyStates.blocker, F.text)
async def receive_blocker(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    advice = demo_advice(task["name"], message.text)
    await state.update_data(blocker=message.text, advice=advice)
    await state.set_state(DailyStates.status)
    await message.answer(f"AI-совет:\n{advice}")
    await message.answer("Теперь выбери статус задачи:", reply_markup=status_keyboard())


@router.callback_query(DailyStates.status, F.data == "daily:skip_rest")
async def skip_rest(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DailyStates.extra)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Оставшиеся задачи пропущены. Делал что-то ещё, не из списка? "
            "Напиши текст или /skip."
        )


@router.callback_query(DailyStates.status, F.data == "daily:skip")
async def skip_task(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Задача пропущена")
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    answers = list(data.get("answers", []))
    task = data["tasks"][data["task_index"]]
    answers.append({"task_id": task["id"], "status": "skipped"})
    await state.update_data(answers=answers)
    await move_to_next_task(callback.message, state)


@router.callback_query(DailyStates.status, F.data.startswith("daily:stage:"))
async def choose_stage(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Статус принят")
    if not isinstance(callback.message, Message) or not callback.data:
        return
    stage = callback.data.rsplit(":", maxsplit=1)[-1]
    await state.update_data(selected_stage=stage)
    if stage == "done":
        await state.set_state(DailyStates.result_url)
        await callback.message.answer("Пришли ссылку на результат или отправь /skip.")
        return
    await save_answer_and_continue(callback.message, state)


async def save_answer_and_continue(
    message: Message,
    state: FSMContext,
    result_url: str | None = None,
) -> None:
    data = await state.get_data()
    task = data["tasks"][data["task_index"]]
    answers: list[dict[str, Any]] = list(data.get("answers", []))
    answers.append(
        {
            "task_id": task["id"],
            "progress": data.get("progress"),
            "stage": data.get("selected_stage"),
            "blocker": data.get("blocker"),
            "result_url": result_url,
        }
    )
    await state.update_data(answers=answers, blocker=None, advice=None)
    await message.answer("Ответ сохранён локально для demo.")
    await move_to_next_task(message, state)


@router.message(DailyStates.result_url, F.text)
async def receive_result_url(message: Message, state: FSMContext) -> None:
    result_url = None if message.text == "/skip" else message.text
    await save_answer_and_continue(message, state, result_url=result_url)


@router.message(DailyStates.extra, F.text)
async def receive_extra(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    answers = data.get("answers", [])
    extra = None if message.text == "/skip" else message.text
    await state.clear()
    await message.answer(
        "Дейли завершён.\n"
        f"Ответов по задачам: {len(answers)}.\n"
        f"Дополнительно: {extra or 'нет'}."
    )

