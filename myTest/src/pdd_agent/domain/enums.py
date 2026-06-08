"""领域枚举：Agent 类型、任务状态、执行阶段。"""

from enum import StrEnum


class AgentKind(StrEnum):
    """可路由的子 Agent 类型。"""

    ORCHESTRATOR = "orchestrator"
    LISTING = "listing"
    DELIST = "delist"
    CAMPAIGN = "campaign"  # 活动报名（待实现）
    TRAFFIC = "traffic"  # 推广投流（待实现）


class RunStatus(StrEnum):
    """单次任务运行的终态/进行中状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    NEEDS_HUMAN = "needs_human"  # 需人工介入（验证码等）
    SKIPPED = "skipped"


class TaskPhase(StrEnum):
    """LangGraph 节点所处阶段，便于日志与 UI 展示。"""

    PLAN = "plan"
    PREFLIGHT = "preflight"
    BROWSER = "browser"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPORT = "report"
