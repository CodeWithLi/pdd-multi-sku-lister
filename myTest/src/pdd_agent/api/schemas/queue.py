"""Queue control API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueuePauseRequest(BaseModel):
    reason: str = ""


class QueueTaskOut(BaseModel):
    task_id: str
    run_id: str
    agent: str
    account_id: str
    status: str
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 1
    error: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class QueueControlOut(BaseModel):
    scope: str
    account_id: str = ""
    paused: bool
    reason: str = ""
    updated_at: datetime | None = None


class QueueStatusOut(BaseModel):
    paused: bool
    counts: dict[str, int] = Field(default_factory=dict)
    controls: list[QueueControlOut] = Field(default_factory=list)
    tasks: list[QueueTaskOut] = Field(default_factory=list)


class QueueCancelResponse(BaseModel):
    canceled: int
    run_ids: list[str] = Field(default_factory=list)
