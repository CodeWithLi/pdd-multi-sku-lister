"""
RabbitMQ 自动整合链路 — 店铺运营周期（Commerce Gate）专用逻辑。

阶段一（上架 + 限时限量购）完成后释放店铺占用，允许同店排队任务继续派发；
活动/推广由 phase2 定时任务在后台执行，不再占用 commerce lifecycle。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_integrated_pipeline, update_integrated_pipeline

logger = get_logger(__name__)

META_STORE_RELEASED_KEY = "mq_commerce_store_released"
META_STORE_RELEASED_AT = "mq_commerce_store_released_at"
META_DISPATCH_AFTER_RELEASE = "mq_commerce_dispatch_after_release"
META_PHASE2_WAIT_REASON = "mq_phase2_wait_reason"
META_PHASE2_WAIT_DETAIL = "mq_phase2_wait_detail"
META_PHASE2_LAST_WAIT_AT = "mq_phase2_last_wait_at"

MQ_PHASE2_WAIT_REASON_LABELS: dict[str, str] = {
    "queue_running_or_lock": "店铺有任务正在执行或浏览器占用中",
    "queue_pending": "店铺任务队列中仍有排队任务",
    "commerce_lifecycle": "店铺有其他运营周期占用",
    "commerce_pending": "店铺有排队待启动的整合链路",
    "other_pipeline": "店铺有其他进行中的整合链路",
}

# 同店其他 MQ 链路若也在等阶段二，不视为占用浏览器
MQ_PHASE2_PEER_IDLE_STEPS = frozenset({"waiting_mq_phase2"})


def format_mq_phase2_wait_detail(meta: dict[str, Any] | None) -> str:
    meta = meta if isinstance(meta, dict) else {}
    reason = str(meta.get(META_PHASE2_WAIT_REASON) or "").strip()
    detail = str(meta.get(META_PHASE2_WAIT_DETAIL) or "").strip()
    label = MQ_PHASE2_WAIT_REASON_LABELS.get(reason, reason or "店铺未空闲")
    if detail:
        return f"活动/推广已到期，等待店铺空闲：{label}（{detail}）"
    return f"活动/推广已到期，等待店铺空闲：{label}"


def assess_mq_phase2_account_idle(*, account_id: str, pipeline_id: str) -> dict[str, Any]:
    """
    判断 MQ 阶段二是否可在该店铺启动（不抢跑、不插队）。

    到期后若店铺仍有整合链路/队列任务/运营周期占用，则返回 ready=False，下次定时任务再试。
    """
    from pdd_agent.api.services.commerce_dispatch import (
        LIFECYCLE_TERMINAL,
        _get_account_lifecycle,
        _list_non_terminal_pipeline_ids_for_account,
        list_pending_intents,
    )
    from pdd_agent.db.repositories import count_account_queue_tasks, list_busy_account_ids

    account_id = str(account_id or "").strip()
    pipeline_id = str(pipeline_id or "").strip()
    checks: list[dict[str, str]] = []

    if account_id in list_busy_account_ids():
        checks.append(
            {
                "reason": "queue_running_or_lock",
                "detail": "任务队列 running 或 Profile 锁未释放",
            }
        )

    queued_count = count_account_queue_tasks(account_id, statuses=("queued",))
    if queued_count > 0:
        checks.append(
            {
                "reason": "queue_pending",
                "detail": f"queued_tasks={queued_count}",
            }
        )

    lifecycle = _get_account_lifecycle(account_id)
    if lifecycle and str(lifecycle.lifecycle_status or "") not in LIFECYCLE_TERMINAL:
        owner_type = str(lifecycle.owner_type or "")
        owner_id = str(lifecycle.owner_id or "")
        if owner_id != pipeline_id:
            checks.append(
                {
                    "reason": "commerce_lifecycle",
                    "detail": f"{owner_type}:{owner_id}",
                }
            )

    pending_intents = list_pending_intents(account_id=account_id, limit=3)
    if pending_intents:
        intent_ids = ", ".join(str(item.get("intent_id") or "") for item in pending_intents[:3])
        checks.append(
            {
                "reason": "commerce_pending",
                "detail": intent_ids,
            }
        )

    for other_pipeline_id in _list_non_terminal_pipeline_ids_for_account(account_id):
        if other_pipeline_id == pipeline_id:
            continue
        other = get_integrated_pipeline(other_pipeline_id)
        if not other:
            continue
        step = str(other.current_step or "").strip()
        if step in MQ_PHASE2_PEER_IDLE_STEPS:
            continue
        checks.append(
            {
                "reason": "other_pipeline",
                "detail": f"{other_pipeline_id}:{step}",
            }
        )

    if checks:
        first = checks[0]
        return {
            "ready": False,
            "reason": first["reason"],
            "detail": first["detail"],
            "checks": checks,
        }
    return {"ready": True, "reason": "", "detail": "", "checks": []}


def clear_mq_phase2_wait_for_account_idle(pipeline_id: str) -> None:
    update_integrated_pipeline(
        pipeline_id,
        meta_patch={
            META_PHASE2_WAIT_REASON: "",
            META_PHASE2_WAIT_DETAIL: "",
        },
    )


def record_mq_phase2_wait_for_account_idle(row, assessment: dict[str, Any]) -> None:
    """记录阶段二因店铺未空闲而暂缓（不取消，下次定时任务继续尝试）。"""
    pipeline_id = str(row.pipeline_id or "").strip()
    if not pipeline_id:
        return
    reason = str(assessment.get("reason") or "").strip()
    detail = str(assessment.get("detail") or "").strip()
    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get(META_PHASE2_WAIT_REASON) == reason and meta.get(META_PHASE2_WAIT_DETAIL) == detail:
        return
    update_integrated_pipeline(
        pipeline_id,
        meta_patch={
            META_PHASE2_WAIT_REASON: reason,
            META_PHASE2_WAIT_DETAIL: detail,
            META_PHASE2_LAST_WAIT_AT: datetime.now().isoformat(),
        },
    )
    logger.info(
        "mq phase2 deferred pipeline=%s account=%s reason=%s detail=%s",
        pipeline_id,
        row.account_id,
        reason,
        detail,
    )


def is_mq_commerce_store_released(row) -> bool:
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}
    return bool(meta.get(META_STORE_RELEASED_KEY))


def should_mq_pipeline_skip_commerce_sync(row) -> bool:
    """
    MQ 延迟阶段二链路在释放店铺后，不再通过 sync_lifecycle 重新占用店铺。

    避免 reconcile / update_integrated_pipeline 把 waiting_mq_phase2 又写回 active。
    """
    from pdd_agent.api.services.pipeline_mq_auto_phase2 import is_mq_auto_deferred_phase2_row

    if not is_mq_auto_deferred_phase2_row(row):
        return False
    return is_mq_commerce_store_released(row)


def release_mq_store_after_phase1(row) -> dict[str, Any]:
    """
    阶段一完成后释放店铺运营周期与商品占用，并尝试派发同店排队任务。

    仅用于 trigger_source=rabbitmq_auto 且 mq_auto_deferred_phase2 的整合链路。
    """
    from pdd_agent.api.services.pipeline_mq_auto_phase2 import is_mq_auto_deferred_phase2_row

    if not is_mq_auto_deferred_phase2_row(row):
        return {"released": False, "reason": "not_mq_deferred_pipeline"}

    pipeline_id = str(row.pipeline_id or "").strip()
    account_id = str(row.account_id or "").strip()
    if not pipeline_id or not account_id:
        return {"released": False, "reason": "missing_pipeline_or_account"}

    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get(META_STORE_RELEASED_KEY):
        return {"released": False, "reason": "already_released", "pipeline_id": pipeline_id}

    from pdd_agent.api.services.commerce_dispatch import (
        _force_clear_account_lifecycle,
        try_dispatch_pending_for_account,
    )

    cleared = _force_clear_account_lifecycle(account_id, reason="mq_phase1_complete")
    dispatch = try_dispatch_pending_for_account(account_id)

    update_integrated_pipeline(
        pipeline_id,
        meta_patch={
            META_STORE_RELEASED_KEY: True,
            META_STORE_RELEASED_AT: datetime.now().isoformat(),
            META_DISPATCH_AFTER_RELEASE: dispatch or {},
        },
    )

    logger.info(
        "mq commerce store released pipeline=%s account=%s cleared=%s dispatched=%s",
        pipeline_id,
        account_id,
        cleared,
        bool(dispatch and dispatch.get("dispatched")),
    )
    return {
        "released": True,
        "pipeline_id": pipeline_id,
        "account_id": account_id,
        "lifecycle_cleared": cleared,
        "dispatched": dispatch,
    }


def release_mq_store_after_phase1_by_id(pipeline_id: str) -> dict[str, Any]:
    row = get_integrated_pipeline(str(pipeline_id or "").strip())
    if not row:
        return {"released": False, "reason": "pipeline_not_found"}
    return release_mq_store_after_phase1(row)
