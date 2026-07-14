"""分批限时限量购 — 自动重跑配置常量。"""

from __future__ import annotations

META_STATE_KEY = "pipeline_batch_limited_time_auto_retry"
META_ENABLED_KEY = "pipeline_batch_limited_time_auto_retry_enabled"
META_MAX_ATTEMPTS_KEY = "pipeline_batch_limited_time_auto_retry_max_attempts"

DEFAULT_MAX_ATTEMPTS = 1
MAX_ATTEMPTS_CAP = 10
MIN_ATTEMPTS = 1
