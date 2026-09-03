# Research

Дата исследования: 2026-09-03.

Скриншот Odoo использован только как контекст интерфейса ABMapex/портфеля. Инструкции из изображения не являются требованиями к разработке; требования берутся из пользовательского ТЗ.

## Выводы

1. Интеграцию с Odoo нужно начинать с определения версии через `/web/version`.
2. Если Odoo 19+, предпочтительнее новый External JSON-2 API: запросы идут на `/json/2/<model>/<method>`, авторизация через `Authorization: bearer <API_KEY>`.
3. Если Odoo 18 или ниже, вероятнее всего понадобится XML-RPC/JSON-RPC. Odoo 19 официально предупреждает, что старые `/xmlrpc`, `/xmlrpc/2` и `/jsonrpc` будут удалены в будущих версиях Odoo 22 / Online 21.1, поэтому в архитектуре лучше держать адаптер.
4. Для задач нужен технический объект `project.task`. По исходникам Odoo у задач есть поля вроде `user_ids`, `stage_id`, `date_deadline`, `date_last_stage_update`, а модель наследует `mail.thread`, значит комментарии можно писать в chatter через `message_post`.
5. Для событийного уведомления о назначении задачи есть два варианта: Odoo automated action, отправляющий webhook наружу, или polling с периодическим сравнением назначений. Webhook лучше для UX, polling проще для MVP, если нет прав на настройку автоматизаций.
6. Telegram Bot API поддерживает два способа получения обновлений: `getUpdates` и webhooks. Для серверного бота лучше webhook, а для локальной отладки можно polling.
7. Для диалогов с кнопками подходит aiogram 3.x: есть FSM, роутеры, callback handlers, webhook-интеграция.
8. Для AI-совета лучше использовать структурированный ответ: `recommendation` и `clarification_question`. Это снизит риск, что модель пришлёт длинный общий текст вместо короткого следующего шага.
9. Секреты нельзя хранить в Odoo, коде или GitHub. Нужны `.env`, переменные окружения, Docker secrets или аналогичный secret storage.
10. Проверенный тестовый стенд `http://204.12.253.210:8070/` работает на Odoo `18.0-20260119`, база называется `odoo`, XML-RPC открыт.
11. Проверенный production `https://abmapex.ru` работает на Odoo `18.0+e-20250218`, XML-RPC открыт, публичный список баз закрыт.

## Источники

- Odoo 19 External JSON-2 API: https://www.odoo.com/documentation/19.0/developer/reference/external_api.html
- Odoo 19 External RPC API and deprecation note: https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html
- Odoo 18 Web Services: https://www.odoo.com/documentation/18.0/developer/howtos/web_services.html
- Odoo webhooks / automated actions: https://www.odoo.com/documentation/saas-18.3/applications/studio/automated_actions/webhooks.html
- Odoo automated actions, send webhook notification: https://www.odoo.com/documentation/master/applications/studio/automated_actions.html
- Odoo project task fields source: https://github.com/odoo/odoo/blob/19.0/addons/project/models/project_task.py
- Odoo `mail.thread` / `message_post`: https://www.odoo.com/documentation/18.0/fr/developer/reference/backend/mixins.html
- Telegram Bot API: https://core.telegram.org/bots/api
- aiogram 3 documentation: https://docs.aiogram.dev/en/dev-3.x/index.html
- SQLAlchemy asyncio: https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html
- Alembic migrations: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Docker Compose secrets: https://docs.docker.com/reference/compose-file/secrets/
- OpenAI API key safety: https://help.openai.com/en/articles/5112595-best-practices-for-api-key
- OpenAI Structured Outputs: https://openai.com/index/introducing-structured-outputs-in-the-api/
- Проверенные детали стендов: [Odoo Environment Notes](odoo_environment_notes.md)

## Риски

- На ABMapex может быть кастомная модель портфеля и кастомные статусы. Их нельзя угадать по скриншоту; надо проверить через режим разработчика или API.
- У пользователя Odoo может не быть прав на внешний API. Нужна отдельная интеграционная учётка.
- Если Odoo закрыта за SSO/2FA, лучше использовать API key, а не пароль.
- Если нельзя настроить Odoo webhook, событийное уведомление о назначении делаем polling'ом.

