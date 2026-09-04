from abm_daily_bot.jobs import build_scheduler


def test_scheduler_contains_required_jobs() -> None:
    scheduler = build_scheduler()

    assert {job.id for job in scheduler.get_jobs()} == {
        "daily_cycle",
        "weekly_planning",
        "remind_non_responders",
        "pm_digest",
        "blocker_escalations",
        "assignment_poll",
    }


def test_scheduler_uses_yekaterinburg_timezone() -> None:
    scheduler = build_scheduler()

    assert str(scheduler.timezone) == "Asia/Yekaterinburg"


def test_scheduler_uses_supplied_callbacks() -> None:
    def daily_callback() -> None:
        return None

    scheduler = build_scheduler(callbacks={"daily_cycle": daily_callback})

    assert scheduler.get_job("daily_cycle").func is daily_callback

