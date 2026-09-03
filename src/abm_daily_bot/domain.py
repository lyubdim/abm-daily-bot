from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class DailyAnswerStatus(StrEnum):
    NO_CHANGES = "no_changes"
    PROGRESS = "progress"
    SKIPPED = "skipped"


class BlockerStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class OdooTask:
    id: int
    name: str
    project_name: str | None
    stage_name: str | None
    deadline: date | None
    url: str | None
    assignee_odoo_ids: tuple[int, ...]
    date_last_stage_update: datetime | None = None


@dataclass(frozen=True)
class TaskContextForAdvice:
    task: OdooTask
    blocker_text: str
    recent_updates: tuple[str, ...]
    days_in_current_stage: int | None


@dataclass(frozen=True)
class AdviceResult:
    recommendation: str
    clarification_question: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification_question)


