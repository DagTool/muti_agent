from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal[1] = 1
    event_type: Literal["task.execute.requested", "task.execute.completed"]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID
    causation_id: UUID | None = None
    workspace_id: str
    project_id: UUID
    task_id: UUID
    execution_id: UUID
    idempotency_key: str
    sender: str
    recipient_role: str
    attempt: int = Field(ge=1, le=3)
    payload: dict[str, Any]


TASK_COMMANDS = "agentforge.task.commands.v1"
TASKS_DEVELOPER = "agentforge.tasks.developer.v1"
TASKS_QA = "agentforge.tasks.qa.v1"
TASKS_PM = "agentforge.tasks.pm.v1"
TASKS_ARCHITECT = "agentforge.tasks.architect.v1"
TASK_RESULTS = "agentforge.task.results.v1"
TASK_DLQ = "agentforge.task.dlq.v1"
