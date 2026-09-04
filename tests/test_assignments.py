from abm_daily_bot.services.scheduled_jobs import new_assignee_ids


def test_new_assignee_ids_returns_only_new_people() -> None:
    assert new_assignee_ids([10, 20], [20, 30]) == {30}


def test_new_assignee_ids_is_empty_when_assignment_did_not_change() -> None:
    assert new_assignee_ids([10, 20], [20, 10]) == set()

