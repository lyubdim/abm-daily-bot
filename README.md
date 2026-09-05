# ABM Club Daily Bot

Telegram-бот для ежедневных статусов команды по задачам из Odoo. Бот спрашивает прогресс, обновляет статус задачи в Odoo, фиксирует ссылки на результат, помогает с затруднениями через AI и отправляет PM ежедневные дайджесты.

## Зачем проект

Команде не нужно каждый день вручную заходить в Odoo ради коротких статусов. Участник отвечает в Telegram, а бот сохраняет результат в карточку задачи и в собственную историю. PM видит, кто ответил, какие задачи двигаются, где есть затруднения и что висит больше двух дней.

## MVP

- ежедневный опрос по открытым задачам участника в 12:00 по Екатеринбургу;
- недельное планирование по понедельникам перед дейли;
- явный выбор этапа задачи кнопками из фактического workflow проекта Odoo;
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
- [Production Deployment](docs/deployment.md)
- [E2E Test Plan](docs/e2e_test_plan.md)
- [E2E Test Results: 2026-09-05](docs/e2e_results_2026-09-05.md)
- [Supervisor Demo](docs/supervisor_demo.md)
- [Requirements Traceability](docs/requirements_traceability.md)

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

Команды участника:

- `/daily` - ежедневный статус по открытым задачам;
- `/weekly` - выбор фокуса недели;
- `/blockers` - открытые затруднения и их снятие.

Команды PM и техлида:

- `/status` или `/status <человек или задача>`;
- `/deadlines` - дедлайны на ближайшие семь дней;
- `/remind` - напомнить неответившим;
- `/digest` и `/digest week` - дневной и недельный дайджест.

Доступ к управленческим командам задаётся числовыми Telegram ID в
`PM_TELEGRAM_IDS` и `TECH_LEAD_TELEGRAM_IDS`.

Связь участников с Odoo задаётся JSON-объектом, например:

```dotenv
TELEGRAM_ODOO_USER_MAP={"123456789":94,"987654321":105}
```

Для самостоятельного первого входа можно выдать персональную deep link. Код и роль
хранятся только в production environment:

```dotenv
TELEGRAM_INVITE_CODES={"private-random-code":{"odoo_user_id":105,"role":"pm"}}
```

Ссылка имеет вид `https://t.me/abm_club_daily_bot?start=private-random-code`. После
первого подключения тот же Odoo-профиль нельзя занять другим Telegram-аккаунтом.

Это bootstrap-вариант для первого PM. Дальше PM создаёт приглашения без перезапуска:

```text
/invite employee@company.ru member
/invite 105 tech_lead
```

Одноразовая ссылка действует 7 дней, а в PostgreSQL хранится только её SHA-256 хеш.
Сотрудник проверяет свою привязку командой `/whoami`; `/daily` получает только задачи,
где его Odoo user указан в `user_ids`. Пароли отдельных сотрудников боту не нужны.

`ODOO_DEFAULT_USER_ID` предназначен только для одиночного тестового запуска.

Ограничение задач связанным production-дашбордом:

```dotenv
ODOO_PROJECT_IDS=[1329,1330,1335,1336]
ODOO_SCOPE_LABEL=PORTF-008 · Управление клубами
```

Этот allowlist применяется к дейли, недельному фокусу, дедлайнам, поиску PM и
уведомлениям о назначении. Так бот не показывает задачи из посторонних проектов.

Контейнерный запуск:

```bash
TELEGRAM_BOT_TOKEN=<token> docker compose up --build bot
```

На Windows для тестового запуска можно открыть
[`scripts/start-test.cmd`](scripts/start-test.cmd). Скрипт проверит Docker, соберёт
актуальный образ, запустит PostgreSQL и бота и покажет состояние контейнеров.

Для согласованного сквозного теста с production Odoo используется локальный
`scripts/start-prod-preview.cmd`. Секреты он берёт из исключённого из Git файла
`.env.prod.local`; тестовая задача должна иметь префикс `[BOT TEST]`.
При каждом контейнерном запуске `alembic upgrade head` автоматически приводит схему
PostgreSQL к версии приложения до старта Telegram polling.

Если test Odoo медленно открывается в браузере, [`scripts/check-test.cmd`](scripts/check-test.cmd)
показывает последние ответы, завершённые дейли и состояние доставки. Значение `SENT`
означает, что Odoo API принял операцию; `RETRY` будет повторён автоматически.

Для постоянной работы на сервере используется отдельная production-конфигурация.
Она не публикует PostgreSQL в интернет и хранит секреты вне Git:

```bash
docker compose --env-file deploy/production.env \
  -f deploy/compose.production.yml up -d --build
```

Полная инструкция: [docs/deployment.md](docs/deployment.md).

Проверка доступа к Odoo в режиме чтения:

```bash
abm-odoo-discover
```

## Статус проекта

Готовы исследование, архитектура, модели хранения, outbox, Telegram FSM и
Odoo-клиент. На test stand и в production подтверждены чтение назначенной задачи,
смена этапа и запись внутреннего комментария в chatter. Реализован AI-совет через OpenAI Responses
API с контекстом задачи и недавними сообщениями из chatter. Ответы дейли сохраняются
в PostgreSQL и доставляются в Odoo через retryable outbox; повторный ответ за день
обновляет ту же запись и chatter-сообщение. Общий ответ вне списка задач сохраняется
отдельно и отмечает дейли завершённым. Команда `/weekly` позволяет кнопками
выбрать задачи фокуса и сохранить стратегический текст на текущую неделю. Открытые
затруднения доступны через `/blockers`; после снятия ссылка на решение обновляет ту же
запись в Odoo. Реализованы защищённые PM-команды статуса, дедлайнов, напоминаний и
дневного/недельного дайджеста. Плановые сообщения и эскалации запускаются по расписанию
Екатеринбурга. Следующий рубеж - постоянный серверный rollout и самостоятельная
приёмка руководителем проекта по персональной Telegram-ссылке.

Текст затруднения по умолчанию не публикуется в общем chatter задачи: там виден
AI-совет, а полное описание доступно автору и PM/техлиду через Telegram. Для
осознанного изменения этого поведения существует `ODOO_INCLUDE_BLOCKER_TEXT`.

Схема PostgreSQL зафиксирована Alembic-миграцией `0001_initial_schema`; Docker-образ
выполняет миграции автоматически перед запуском приложения.

Назначения задач отслеживаются fallback polling раз в минуту. После настройки
публичного HTTPS endpoint его можно дополнить Odoo webhook без изменения Telegram UX.
Для командного запуска используется индивидуальная карта Telegram ID в Odoo user ID.
