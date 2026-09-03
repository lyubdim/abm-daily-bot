from abm_daily_bot.services.outbox import retry_delay


def test_retry_delay_uses_exponential_backoff() -> None:
    assert retry_delay(1).total_seconds() == 15
    assert retry_delay(2).total_seconds() == 30
    assert retry_delay(3).total_seconds() == 60


def test_retry_delay_is_capped_at_one_hour() -> None:
    assert retry_delay(20).total_seconds() == 3600

