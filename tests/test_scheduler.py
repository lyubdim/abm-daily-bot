from abm_daily_bot.jobs import build_scheduler


def test_scheduler_contains_required_jobs() -> None:
    scheduler = build_scheduler()

    assert {job.id for job in scheduler.get_jobs()} == {
        "daily_cycle",
        "weekly_planning",
        "remind_non_responders",
        "pm_digest",
        "blocker_escalations",
    }


def test_scheduler_uses_yekaterinburg_timezone() -> None:
    scheduler = build_scheduler()

    assert str(scheduler.timezone) == "Asia/Yekaterinburg"

