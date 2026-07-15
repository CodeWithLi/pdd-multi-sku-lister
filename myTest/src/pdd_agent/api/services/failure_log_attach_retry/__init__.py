"""失败日志挂回原链路重跑（上架 → 限时 → 活动改期 + 精准回写每批状态）。"""

from __future__ import annotations

from pdd_agent.api.services.failure_log_attach_retry.bridge import (
    build_attach_retry_public_state,
    dispatch_attach_retry_queue_task_finished,
    is_attach_source_pipeline_enabled,
    maybe_defer_activity_task_execution,
    patch_batch_product_stage,
    try_process_attach_source_pipeline,
)
from pdd_agent.api.services.failure_log_attach_retry.capture_pipeline_id import (
    is_attach_path_fully_enabled,
    is_capture_pipeline_id_enabled,
)
from pdd_agent.api.services.failure_log_attach_retry.policy import (
    start_attach_retry_on_source_pipeline,
)
from pdd_agent.api.services.failure_log_attach_retry.stage_patch import (
    patch_batch_product_stage as patch_pipeline_batch_product_stage,
)

__all__ = [
    "build_attach_retry_public_state",
    "dispatch_attach_retry_queue_task_finished",
    "is_attach_path_fully_enabled",
    "is_attach_source_pipeline_enabled",
    "is_capture_pipeline_id_enabled",
    "maybe_defer_activity_task_execution",
    "patch_batch_product_stage",
    "patch_pipeline_batch_product_stage",
    "start_attach_retry_on_source_pipeline",
    "try_process_attach_source_pipeline",
]
