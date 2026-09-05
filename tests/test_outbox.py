from datetime import UTC, datetime
from types import SimpleNamespace

from abm_daily_bot.db.models import OutboxState
from abm_daily_bot.services.odoo_client import OdooUnavailableError
from abm_daily_bot.services.outbox import OdooOutboxService, retry_delay


def test_retry_delay_uses_exponential_backoff() -> None:
    assert retry_delay(1).total_seconds() == 15
    assert retry_delay(2).total_seconds() == 30
    assert retry_delay(3).total_seconds() == 60


def test_retry_delay_is_capped_at_one_hour() -> None:
    assert retry_delay(20).total_seconds() == 3600


class RecordingOdoo:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    async def call(self, *args: object, **kwargs: object) -> object:
        self.calls.append((*args, kwargs))
        return self.result


async def test_deliver_remembers_created_chatter_message_id() -> None:
    odoo = RecordingOdoo(321)
    service = OdooOutboxService(odoo)  # type: ignore[arg-type]
    item = SimpleNamespace(
        model="project.task",
        method="message_post",
        arguments=[[4]],
        keyword_arguments={"body": "status"},
        attempt_count=0,
        state=OutboxState.PENDING,
        next_attempt_at=None,
        sent_at=None,
        last_error=None,
        remote_record_id=None,
    )

    await service._deliver(item, now=SimpleNamespace())  # type: ignore[arg-type]

    assert item.state == OutboxState.SENT
    assert item.remote_record_id == 321


async def test_deliver_remembers_direct_mail_message_id() -> None:
    odoo = RecordingOdoo(654)
    service = OdooOutboxService(odoo)  # type: ignore[arg-type]
    item = SimpleNamespace(
        model="mail.message",
        method="create",
        arguments=[{"model": "project.task", "res_id": 597, "body": "status"}],
        keyword_arguments={},
        attempt_count=0,
        state=OutboxState.PENDING,
        next_attempt_at=None,
        sent_at=None,
        last_error=None,
        remote_record_id=None,
    )

    await service._deliver(item, now=SimpleNamespace())  # type: ignore[arg-type]

    assert item.state == OutboxState.SENT
    assert item.remote_record_id == 654


class TemporarilyUnavailableOdoo:
    def __init__(self) -> None:
        self.call_count = 0

    async def call(self, *args: object, **kwargs: object) -> bool:
        self.call_count += 1
        if self.call_count == 1:
            raise OdooUnavailableError("Odoo is restarting")
        return True


async def test_delivery_is_retried_after_temporary_odoo_failure() -> None:
    odoo = TemporarilyUnavailableOdoo()
    service = OdooOutboxService(odoo)  # type: ignore[arg-type]
    item = SimpleNamespace(
        model="project.task",
        method="write",
        arguments=[[597], {"stage_id": 24}],
        keyword_arguments={},
        attempt_count=0,
        state=OutboxState.PENDING,
        next_attempt_at=None,
        sent_at=None,
        last_error=None,
        remote_record_id=None,
    )
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    await service._deliver(item, now=now)  # type: ignore[arg-type]

    assert item.state == OutboxState.RETRY
    assert item.next_attempt_at > now
    assert "restarting" in item.last_error

    await service._deliver(item, now=item.next_attempt_at)  # type: ignore[arg-type]

    assert item.state == OutboxState.SENT
    assert item.attempt_count == 2
    assert item.last_error is None
