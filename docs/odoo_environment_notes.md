# Odoo Environment Notes

Дата последней проверки: 2026-09-04.

Пароли и токены в этот документ не вносятся. Для разработки используются `.env` или secret storage.

## Test stand

- URL: `http://204.12.253.210:8070/`
- Версия: Odoo `18.0-20260119`
- Database list: `odoo`
- XML-RPC доступен: `http://204.12.253.210:8070/xmlrpc/2/common`
- Web login: `http://204.12.253.210:8070/web/login`

Для API нужны:

- `ODOO_BASE_URL=http://204.12.253.210:8070`
- `ODOO_DATABASE=odoo`
- `ODOO_USERNAME=<login>`
- `ODOO_PASSWORD=<password-or-api-key>`
- `ODOO_API_STYLE=xmlrpc`

Веб-вход под тестовой учётной записью подтверждён. Сервер запросил одноразовый код
по email, после чего открыл backend Odoo. Учётная запись видит модуль `Project`,
список проектов и открытые задачи `REF0001`-`REF0010`. В интерфейсе подтверждены
поля задачи: название, проект, ответственные, следующая активность, теги и этап.

Обычный пароль не подходит для фоновой XML-RPC-интеграции с двухфакторной
проверкой. Создан отдельный API key `ABM Daily Bot Test` со сроком действия один
месяц. Ключ сохранён только в локальном `.env`, исключённом из Git. Секреты и
одноразовый код в проект не сохранялись.

API discovery успешно пройден:

- аутентифицирован пользователь `uid=94`;
- доступны чтение, создание, изменение и удаление `project.project`,
  `project.task` и `project.task.type`;
- подтверждены поля `project_id`, `user_ids`, `stage_id`, `state`,
  `date_deadline`, `date_last_stage_update`, `access_url` и `is_closed`;
- состояния Odoo: `01_in_progress`, `02_changes_requested`, `03_approved`,
  `04_waiting_normal`, `1_done`, `1_canceled`;
- исходно база не содержала реальных проектов и задач; строки `REF0001`-`REF0010`
  в интерфейсе были sample data Odoo для пустого списка.

Для сквозной проверки созданы только явно помеченные тестовые записи:

- проект `ABM Daily Bot Test`, `id=1`;
- стадии `К выполнению`, `В работе`, `Готово`, `id=22-24`;
- задача `ABM Daily Bot E2E: обновление статуса из Telegram`, `id=4`, назначенная
  на `uid=94`.

Через XML-RPC подтверждены чтение задачи, смена этапа и состояния, а также
`message_post` с комментарием и ссылкой. Production при проверке не изменялся.

## Production

- Dashboard URL: `https://abmapex.ru/odoo/action-1487/project.portfolio/project.portfolio/14/project.project`
- Portfolio: `PORTF-008 Управление клубами`, record ID `14`.
- Current project IDs discovered read-only from the portfolio: `1329`, `1330`, `1335`,
  `1336` (67 tasks total in the portfolio cards at discovery time).
- Configure `ODOO_PROJECT_IDS=[1329,1330,1335,1336]` so daily, weekly, deadlines,
  PM search and assignment polling stay inside the linked dashboard.
- The current production user can view the portfolio and task boards, but opening a
  project form reports missing read access to `res.users` in the relevant company.
  A dedicated integration user must receive this access before production writes.
- Версия: Odoo `18.0+e-20250218`
- XML-RPC доступен: `https://abmapex.ru/xmlrpc/2/common`
- Public database list закрыт: `/web/database/list` возвращает `403 Forbidden`

Для API нужны:

- `ODOO_BASE_URL=https://abmapex.ru`
- `ODOO_DATABASE=<need-to-discover-after-login>`
- `ODOO_USERNAME=<integration-user-login>`
- `ODOO_PASSWORD=<api-key-preferred>`
- `ODOO_API_STYLE=xmlrpc`

Доступ к dashboard в браузере и доступ к API - не одно и то же. Для бота нужен пользователь, который может читать и менять задачи, а не только открыть страницу портфеля.

## Что нужно проверить после входа

1. Название базы прод-стенда. Его можно увидеть после входа через `/web/session/get_session_info`.
2. Доступ к модели `project.task`.
3. Доступ к модели `project.task.type` для списка статусов.
4. Доступ к `project.project` и, если используется портфель, к `project.portfolio`.
5. Возможность выполнить `message_post` на задаче.
6. Наличие/отсутствие кастомных полей под ссылку результата и статус затруднения.
7. Возможность настроить automated action/webhook для события назначения задачи.

Веб-интерфейс подтвердил Odoo 18 и базовые поля, но технические имена полей,
числовые ID этапов и право `message_post` должны быть подтверждены через API.

Для воспроизводимой проверки добавлена команда `abm-odoo-discover`, описанная в
`docs/odoo_discovery.md`.

## Рекомендация по доступам

Для практики и разработки начинать с test stand. На production использовать отдельного интеграционного пользователя или API key с минимальными правами. Админский логин лучше не вшивать в `.env` и не использовать как постоянный доступ бота.

