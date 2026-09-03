from fastapi import FastAPI, Header, HTTPException, Request

from abm_daily_bot.config import get_settings

app = FastAPI(title="ABM Club Daily Bot")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    settings = get_settings()
    if (
        settings.telegram_webhook_secret
        and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    update_payload = await request.json()
    # TODO: pass update_payload to aiogram Dispatcher.feed_update after bot initialization.
    _ = update_payload
    return {"ok": True}


@app.post("/odoo/assignment-webhook")
async def odoo_assignment_webhook(request: Request) -> dict[str, bool]:
    payload = await request.json()
    # TODO: validate Odoo webhook secret and enqueue task-assignment notification.
    _ = payload
    return {"ok": True}

