"""失败日志挂回原链路重跑 — 常量。"""

from __future__ import annotations

META_STATE_KEY = "failure_log_attach_retry"
META_DEFER_KEY = "failure_log_attach_retry_activity_defer"
PAYLOAD_FLAG = "failure_log_attach_retry"

PHASE_IDLE = "idle"
PHASE_LISTING = "listing"
PHASE_LIMITED_TIME = "limited_time"
PHASE_DONE = "done"
PHASE_PARTIAL = "partial"
PHASE_FAILED = "failed"

ACTIVE_PHASES = frozenset({PHASE_LISTING, PHASE_LIMITED_TIME})

DEFER_POLL_MINUTES = 10
