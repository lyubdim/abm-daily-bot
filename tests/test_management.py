from abm_daily_bot.bot.management import parse_telegram_ids


def test_parse_telegram_ids_combines_roles_and_ignores_invalid_values() -> None:
    assert parse_telegram_ids("100, 200", "200,abc,300") == {100, 200, 300}

