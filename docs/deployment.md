# Постоянная работа бота

## Выбранная схема

Для стабильного запуска используется небольшой VPS с Ubuntu и Docker Compose:

- `bot` постоянно получает обновления Telegram через long polling;
- `postgres` хранит историю, очередь доставки в Odoo и состояние сценариев;
- Docker перезапускает сервисы после сбоя или перезагрузки сервера;
- исходный код и история изменений остаются в приватном GitHub-репозитории;
- секреты находятся только в файле `deploy/production.env` на сервере.

Для polling не нужны домен, публичный HTTP-порт и TLS-сертификат. На сервере
достаточно открыть SSH для администрирования. Когда появится webhook от Odoo,
можно будет отдельно добавить HTTPS reverse proxy.

## Рекомендуемый сервер

- Ubuntu 24.04 LTS;
- 2 vCPU, 2 GB RAM, 30-40 GB SSD;
- публичный IPv4;
- автоматические резервные копии диска, если они доступны у провайдера;
- регион, близкий к Екатеринбургу и серверам Odoo.

Этого достаточно для текущего бота, PostgreSQL и небольшого объёма истории.

## Первое развёртывание

1. Создать VPS и добавить SSH-ключ администратора.
2. Установить Docker Engine и Compose plugin по официальной инструкции Docker.
3. Клонировать приватный репозиторий в `/opt/abm-daily-bot` с read-only deploy key.
4. Создать файл окружения из шаблона:

   ```bash
   cd /opt/abm-daily-bot
   cp deploy/production.env.example deploy/production.env
   chmod 600 deploy/production.env
   ```

5. Заполнить токен Telegram и сгенерированные пароли. Пароль PostgreSQL в
   `DATABASE_URL` должен быть URL-encoded.
6. Собрать и запустить сервисы:

   ```bash
   docker compose \
     --env-file deploy/production.env \
     -f deploy/compose.production.yml \
     up -d --build
   ```

   Контейнер `bot` сначала выполняет `alembic upgrade head`, а затем запускает
   Telegram polling. Если миграция завершилась с ошибкой, бот не стартует и не
   работает с частично обновлённой схемой.

7. Проверить состояние и последние логи:

   ```bash
   docker compose -f deploy/compose.production.yml ps
   docker compose -f deploy/compose.production.yml logs --tail=100 bot
   ```

8. Отправить боту `/start` и `/daily` в Telegram.

## Обновление после коммита

Перед обновлением создать резервную копию базы:

```bash
docker compose -f deploy/compose.production.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "backup-$(date +%F-%H%M).sql"
```

Затем получить код и пересобрать сервисы:

```bash
cd /opt/abm-daily-bot
git pull --ff-only
docker compose \
  --env-file deploy/production.env \
  -f deploy/compose.production.yml \
  up -d --build
docker image prune -f
```

Перед автоматическим деплоем CI должен оставаться зелёным. На первом этапе
обновление запускается вручную, чтобы ошибочный коммит не попадал в production.
Миграции применяются автоматически контейнером `bot`; откат схемы выполняется только
по отдельному плану восстановления из проверенной резервной копии.

## Проверки и обслуживание

Еженедельно:

- проверить `docker compose ps` и ошибки в логах;
- убедиться, что резервная копия PostgreSQL создаётся и восстанавливается;
- проверить свободное место командой `df -h`;
- обновлять Ubuntu и Docker в согласованное окно обслуживания.

После утечки или публикации секрета нужно отозвать его у провайдера, заменить в
`production.env` и пересоздать контейнер. Токены нельзя отправлять в issue,
commit, README или отчёт по практике.

## Следующий уровень надёжности

После подключения реальных пользователей следует добавить:

- ежедневный зашифрованный backup PostgreSQL вне VPS;
- внешний uptime-monitor и оповещение PM при остановке;
- healthcheck приложения;
- GitHub Actions deployment только после успешных тестов;
- отдельного Linux-пользователя и запрет SSH-входа по паролю;
- ротацию Telegram, Odoo и AI-секретов.
## Роли Telegram

Для доступа к управленческим командам укажите числовые ID через запятую:

```dotenv
PM_TELEGRAM_IDS=123456789
TECH_LEAD_TELEGRAM_IDS=987654321
```

Идентификатор можно получить после первого сообщения боту из журнала регистрации
пользователя. Username не используется как право доступа, потому что его можно менять.

## Связь пользователей с Odoo

Для команды настройте индивидуальную карту в `deploy/production.env`:

```dotenv
TELEGRAM_ODOO_USER_MAP={"123456789":94,"987654321":105}
ODOO_DEFAULT_USER_ID=0
```

Ключ слева - неизменяемый числовой Telegram ID, значение справа - ID записи
`res.users` в Odoo. Нулевой default предотвращает случайную работу от имени другого
участника, если его забыли добавить в карту.

