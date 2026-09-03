# Odoo Environment Notes

Дата проверки: 2026-09-03.

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

Проверка переданной пары логин/пароль завершилась безуспешно: XML-RPC вернул
`uid=false`, web-session - `uid=null`. Вероятные причины: пользователь не активирован,
логин отличается от почты, пароль относится к другой записи или требуется завершить
приглашение/сброс. Секрет в проект не сохранялся.

Следующее действие администратора: подтвердить точный login, активировать пользователя,
выдать новый временный пароль или API key и права на модуль Project.

## Production

- Dashboard URL: `https://abmapex.ru/odoo/action-1487/project.portfolio/project.portfolio/14/project.project`
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

Для воспроизводимой проверки добавлена команда `abm-odoo-discover`, описанная в
`docs/odoo_discovery.md`.

## Рекомендация по доступам

Для практики и разработки начинать с test stand. На production использовать отдельного интеграционного пользователя или API key с минимальными правами. Админский логин лучше не вшивать в `.env` и не использовать как постоянный доступ бота.

