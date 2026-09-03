# ABM Club Daily Bot

Telegram-бот для ежедневных статусов команды по задачам из Odoo. Бот спрашивает прогресс, обновляет статус задачи в Odoo, фиксирует ссылки на результат, помогает с затруднениями через AI и отправляет PM ежедневные дайджесты.

## Зачем проект

Команде не нужно каждый день вручную заходить в Odoo ради коротких статусов. Участник отвечает в Telegram, а бот сохраняет результат в карточку задачи и в собственную историю. PM видит, кто ответил, какие задачи двигаются, где есть затруднения и что висит больше двух дней.

## MVP

- ежедневный опрос по открытым задачам участника в 12:00 по Екатеринбургу;
- недельное планирование по понедельникам перед дейли;
- явный выбор статуса задачи кнопками;
- фиксация затруднения, AI-совета и ссылки на решение;
- запись статусов, комментариев и ссылок обратно в Odoo;
- очередь повторной отправки, если Odoo временно недоступна;
- PM-команды и ежедневный дайджест.

## Технологический стек

- Python 3.12
- aiogram 3.x для Telegram-бота
- FastAPI для webhook endpoint'ов Telegram/Odoo
- PostgreSQL для локальной истории и очереди outbox
- SQLAlchemy + Alembic для БД и миграций
- APScheduler или отдельный worker для расписания
- Odoo API: JSON-2 для Odoo 19+, XML-RPC/JSON-RPC fallback для более старых версий
- OpenAI API или другой LLM-провайдер для короткого AI-совета

## Документация

- [Research](docs/research.md)
- [Technical Design](docs/technical_design.md)
- [Roadmap](docs/roadmap.md)
- [Access Checklist](docs/access_checklist.md)
- [Odoo Environment Notes](docs/odoo_environment_notes.md)
- [Odoo API Discovery](docs/odoo_discovery.md)
- [Practice Report Outline](docs/practice_report_outline.md)
- [GitHub Setup](docs/github_setup.md)
- [Development Log](docs/development_log.md)

## Безопасность

Секреты не хранятся в коде и не попадают в GitHub. Для запуска используются переменные окружения или secret storage. В репозитории есть только `.env.example` с названиями переменных.

## Быстрый старт для разработки

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

После заполнения `.env`:

```bash
uvicorn abm_daily_bot.main:app --reload
```

Для первого теста в Telegram без записи в Odoo:

```bash
abm-bot
```

В Telegram отправить боту `/start`, затем `/daily`. Demo-режим использует две
тестовые задачи и не изменяет данные Odoo.

Контейнерный запуск:

```bash
TELEGRAM_BOT_TOKEN=<token> docker compose up --build bot
```

Проверка доступа к Odoo в режиме чтения:

```bash
abm-odoo-discover
```

## Статус проекта

Готовы исследование, архитектура, модели хранения, outbox с повторной доставкой,
Odoo-клиент и безопасная discovery-команда. Следующий рубеж - активировать доступ
к test stand и реализовать Telegram FSM поверх подтверждённых полей Odoo.

