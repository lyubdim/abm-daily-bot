# GitHub Setup

## Рекомендуемое название

`abm-daily-bot`

## Видимость

Для практики лучше приватный репозиторий, если в README или issues будут упоминаться внутренние ссылки Odoo, имена сотрудников или рабочие детали ABMapex.

## Первичная публикация

```bash
git init
git add .
git commit -m "Initial project package"
git branch -M main
git remote add origin https://github.com/<username>/abm-daily-bot.git
git push -u origin main
```

## Ветки

- `main`: стабильная версия для показа руководителю.
- `feature/odoo-discovery`: проверка Odoo API и моделей.
- `feature/telegram-mvp`: базовый Telegram-сценарий.
- `feature/ai-blockers`: AI-советы и затруднения.
- `feature/pm-digest`: дайджесты и эскалации.

## Milestones

- `M0 Project setup`
- `M1 Odoo discovery`
- `M2 Telegram MVP`
- `M3 Reliable sync`
- `M4 AI blockers`
- `M5 PM digest`
- `M6 Final practice package`

## Что не публиковать

- реальные токены;
- пароли;
- `.env`;
- скриншоты с приватными данными сотрудников без согласования;
- полные выгрузки задач из Odoo.


