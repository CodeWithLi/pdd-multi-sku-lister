"""领域枚举。"""

from enum import StrEnum


class AgentKind(StrEnum):
    ORCHESTRATOR = "orchestrator"
    LISTING = "listing"
    DELIST = "delist"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    NEEDS_HUMAN = "needs_human"
    SKIPPED = "skipped"


class TaskPhase(StrEnum):
    PLAN = "plan"
    PREFLIGHT = "preflight"
    BROWSER = "browser"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPORT = "report"
