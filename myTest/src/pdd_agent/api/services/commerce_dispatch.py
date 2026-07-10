"""店铺运营周期门禁 + 意图队列（Phase 1）。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import delete, select

from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import (
    AccountLifecycleORM,
    CommerceIntentORM,
    IntegratedPipelineORM,
    ProductClaimORM,
)
from pdd_agent.db.session import is_database_available, session_scope

logger = get_logger(__name__)

TriggerSource = Literal["manual", "rabbitmq_auto", "cycle_relist", "failure_sequential"]

TRIGGER_PRIORITY: dict[str, int] = {
    "cycle_relist": 10,
    "failure_sequential": 10,
    "manual": 5,
    "rabbitmq_auto": 1,
}

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_SCHEDULED = "scheduled"
LIFECYCLE_TERMINAL = frozenset({"completed", "failed", "canceled"})

SCHEDULED_PIPELINE_STEPS = frozenset({"waiting_activity", "waiting_limited_time"})
TERMINAL_PIPELINE_STATUSES = frozenset({"completed", "failed", "canceled"})

BLOCK_REASON_LABELS: dict[str, str] = {
    "account_active": "店铺有进行中的运营周期，已排队",
    "account_scheduled": "店铺等待活动预约时间，已排队",
    "product_claimed": "商品已被其他运营周期占用，已排队",
    "duplicate_pending": "相同商品已在排队中，已合并",
}


def commerce_enabled() -> bool:
    return is_database_available()


def normalize_selectors(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in codes:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def build_claim_key(account_id: str, selector: str) -> str:
    return f"{account_id}|{str(selector or '').strip()}"


def build_intent_dedupe_key(account_id: str, selectors: list[str]) -> str:
    normalized = normalize_selectors(selectors)
    raw = f"{account_id}|{'|'.join(sorted(normalized))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def trigger_priority(trigger_source: str) -> int:
    return int(TRIGGER_PRIORITY.get(str(trigger_source or "").strip(), 1))


def format_block_reason(reason: str, *, detail: str = "", wake_at: datetime | None = None) -> str:
    label = BLOCK_REASON_LABELS.get(reason, reason or "已排队")
    if wake_at:
        label = f"{label}（预计 {wake_at:%Y-%m-%d %H:%M} 后可继续）"
    if detail:
        return f"{label}：{detail}"
    return label


def _new_lifecycle_id() -> str:
    return uuid.uuid4().hex


def _new_intent_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _get_account_lifecycle(account_id: str) -> AccountLifecycleORM | None:
    if not commerce_enabled():
        return None
    with session_scope() as session:
        row = session.get(AccountLifecycleORM, account_id)
        if row:
            session.expunge(row)
        return row


def _find_conflicting_claims(
    account_id: str,
    selectors: list[str],
    *,
    exclude_lifecycle_id: str = "",
) -> list[ProductClaimORM]:
    keys = [build_claim_key(account_id, s) for s in normalize_selectors(selectors)]
    if not keys:
        return []
    with session_scope() as session:
        rows = list(
            session.scalars(select(ProductClaimORM).where(ProductClaimORM.claim_key.in_(keys))).all()
        )
        for row in rows:
            session.expunge(row)
    exclude = str(exclude_lifecycle_id or "").strip()
    if exclude:
        return [row for row in rows if row.lifecycle_id != exclude]
    return rows


def _find_pending_intent_by_dedupe(dedupe_key: str) -> CommerceIntentORM | None:
    with session_scope() as session:
        row = session.scalar(
            select(CommerceIntentORM)
            .where(
                CommerceIntentORM.dedupe_key == dedupe_key,
                CommerceIntentORM.status == "pending",
            )
            .order_by(CommerceIntentORM.created_at.asc())
            .limit(1)
        )
        if row:
            session.expunge(row)
        return row


def evaluate_commerce_gate(
    *,
    account_id: str,
    product_selectors: list[str],
    trigger_source: str,
) -> dict[str, Any]:
    """判断是否可立即启动；不可则返回排队信息（不写入 DB）。"""
    if not commerce_enabled():
        return {"allowed": True}

    account_id = str(account_id or "").strip()
    selectors = normalize_selectors(product_selectors)
    if not account_id:
        return {"allowed": True}

    lifecycle = _get_account_lifecycle(account_id)
    if lifecycle and lifecycle.lifecycle_status not in LIFECYCLE_TERMINAL:
        reason = (
            "account_scheduled"
            if lifecycle.lifecycle_status == LIFECYCLE_SCHEDULED
            else "account_active"
        )
        return {
            "allowed": False,
            "block_reason": reason,
            "block_detail": f"owner={lifecycle.owner_type}:{lifecycle.owner_id}",
            "wake_at": lifecycle.wake_at,
        }

    claims = _find_conflicting_claims(account_id, selectors)
    if claims:
        return {
            "allowed": False,
            "block_reason": "product_claimed",
            "block_detail": ", ".join(row.listing_selector for row in claims[:5]),
            "wake_at": None,
        }

    dedupe_key = build_intent_dedupe_key(account_id, selectors)
    pending = _find_pending_intent_by_dedupe(dedupe_key)
    if pending:
        return {
            "allowed": False,
            "block_reason": "duplicate_pending",
            "block_detail": pending.intent_id,
            "wake_at": None,
            "existing_intent_id": pending.intent_id,
        }

    return {"allowed": True}


def enqueue_commerce_intent(
    *,
    account_id: str,
    product_selectors: list[str],
    trigger_source: str,
    pipeline_payload: dict[str, Any],
    block_reason: str,
    block_detail: str = "",
    wake_at: datetime | None = None,
    existing_intent_id: str = "",
) -> dict[str, Any]:
    """写入待执行意图并返回排队响应。"""
    if existing_intent_id:
        return build_queued_response(
            intent_id=existing_intent_id,
            account_id=account_id,
            product_selectors=product_selectors,
            block_reason=block_reason or "duplicate_pending",
            block_detail=block_detail,
            wake_at=wake_at,
        )

    selectors = normalize_selectors(product_selectors)
    dedupe_key = build_intent_dedupe_key(account_id, selectors)
    pending = _find_pending_intent_by_dedupe(dedupe_key)
    if pending:
        return build_queued_response(
            intent_id=pending.intent_id,
            account_id=account_id,
            product_selectors=list(pending.product_selectors or selectors),
            block_reason="duplicate_pending",
            block_detail=pending.intent_id,
            wake_at=wake_at,
        )

    intent_id = _new_intent_id()
    now = datetime.now()
    row = CommerceIntentORM(
        intent_id=intent_id,
        account_id=account_id,
        trigger_source=str(trigger_source or "manual"),
        priority=trigger_priority(trigger_source),
        product_selectors=selectors,
        payload=dict(pipeline_payload or {}),
        status="pending",
        dedupe_key=dedupe_key,
        block_reason=str(block_reason or "account_active"),
        block_detail=str(block_detail or ""),
        created_at=now,
        updated_at=now,
    )
    with session_scope() as session:
        session.add(row)
    logger.info(
        "commerce intent queued intent_id=%s account=%s source=%s reason=%s products=%s",
        intent_id,
        account_id,
        trigger_source,
        block_reason,
        selectors,
    )
    queued = build_queued_response(
        intent_id=intent_id,
        account_id=account_id,
        product_selectors=selectors,
        block_reason=block_reason,
        block_detail=block_detail,
        wake_at=wake_at,
    )
    _try_notify_commerce_queued(queued, trigger_source=trigger_source)
    return queued


def build_queued_response(
    *,
    intent_id: str,
    account_id: str,
    product_selectors: list[str],
    block_reason: str,
    block_detail: str = "",
    wake_at: datetime | None = None,
) -> dict[str, Any]:
    reason_label = format_block_reason(block_reason, detail=block_detail, wake_at=wake_at)
    return {
        "commerce_queued": True,
        "intent_id": intent_id,
        "account_id": account_id,
        "product_codes": list(product_selectors),
        "block_reason": block_reason,
        "block_reason_label": reason_label,
        "wake_at": wake_at.isoformat(timespec="seconds") if wake_at else "",
        "pipeline_id": "",
        "status": "queued",
        "current_step": "commerce_queued",
        "is_merged": block_reason == "duplicate_pending",
    }


def gate_integrated_pipeline_start(
    *,
    account_id: str,
    product_selectors: list[str],
    trigger_source: str,
    pipeline_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """若不可立即启动则返回排队 dict，否则返回 None。"""
    gate = evaluate_commerce_gate(
        account_id=account_id,
        product_selectors=product_selectors,
        trigger_source=trigger_source,
    )
    if gate.get("allowed"):
        return None
    return enqueue_commerce_intent(
        account_id=account_id,
        product_selectors=product_selectors,
        trigger_source=trigger_source,
        pipeline_payload=pipeline_payload,
        block_reason=str(gate.get("block_reason") or "account_active"),
        block_detail=str(gate.get("block_detail") or ""),
        wake_at=gate.get("wake_at"),
        existing_intent_id=str(gate.get("existing_intent_id") or ""),
    )


def register_integrated_pipeline_lifecycle(
    *,
    account_id: str,
    pipeline_id: str,
    product_selectors: list[str],
    trigger_source: str,
    intent_id: str = "",
) -> None:
    if not commerce_enabled():
        return
    account_id = str(account_id or "").strip()
    pipeline_id = str(pipeline_id or "").strip()
    selectors = normalize_selectors(product_selectors)
    if not account_id or not pipeline_id:
        return

    lifecycle_id = _new_lifecycle_id()
    now = datetime.now()
    with session_scope() as session:
        session.execute(delete(AccountLifecycleORM).where(AccountLifecycleORM.account_id == account_id))
        session.add(
            AccountLifecycleORM(
                account_id=account_id,
                lifecycle_id=lifecycle_id,
                owner_type="integrated_pipeline",
                owner_id=pipeline_id,
                trigger_source=str(trigger_source or "manual"),
                phase="listing",
                lifecycle_status=LIFECYCLE_ACTIVE,
                product_selectors=selectors,
                created_at=now,
                updated_at=now,
            )
        )
        for selector in selectors:
            session.merge(
                ProductClaimORM(
                    claim_key=build_claim_key(account_id, selector),
                    account_id=account_id,
                    lifecycle_id=lifecycle_id,
                    intent_id=str(intent_id or ""),
                    listing_selector=selector,
                    claimed_at=now,
                )
            )
        if intent_id:
            intent = session.get(CommerceIntentORM, intent_id)
            if intent and intent.status == "pending":
                intent.status = "dispatched"
                intent.dispatched_at = now
                intent.result_pipeline_id = pipeline_id
                intent.updated_at = now

    logger.info(
        "commerce lifecycle registered account=%s pipeline=%s lifecycle=%s products=%s",
        account_id,
        pipeline_id,
        lifecycle_id,
        selectors,
    )


def register_failure_sequential_lifecycle(
    *,
    account_id: str,
    job_id: str,
    product_selectors: list[str],
) -> None:
    if not commerce_enabled():
        return
    account_id = str(account_id or "").strip()
    job_id = str(job_id or "").strip()
    selectors = normalize_selectors(product_selectors)
    if not account_id or not job_id:
        return

    lifecycle_id = _new_lifecycle_id()
    now = datetime.now()
    with session_scope() as session:
        existing = session.get(AccountLifecycleORM, account_id)
        if existing and existing.lifecycle_status not in LIFECYCLE_TERMINAL:
            lifecycle_id = existing.lifecycle_id
        else:
            session.execute(delete(AccountLifecycleORM).where(AccountLifecycleORM.account_id == account_id))
            session.add(
                AccountLifecycleORM(
                    account_id=account_id,
                    lifecycle_id=lifecycle_id,
                    owner_type="failure_sequential",
                    owner_id=job_id,
                    trigger_source="failure_sequential",
                    phase="listing",
                    lifecycle_status=LIFECYCLE_ACTIVE,
                    product_selectors=selectors,
                    created_at=now,
                    updated_at=now,
                )
            )
        for selector in selectors:
            session.merge(
                ProductClaimORM(
                    claim_key=build_claim_key(account_id, selector),
                    account_id=account_id,
                    lifecycle_id=lifecycle_id,
                    listing_selector=selector,
                    claimed_at=now,
                )
            )


def _pipeline_lifecycle_status(row: IntegratedPipelineORM) -> tuple[str, str, datetime | None]:
    status = str(row.status or "").strip().lower()
    step = str(row.current_step or "").strip()
    wake_at = row.scheduled_activity_at
    if status in TERMINAL_PIPELINE_STATUSES:
        return status, "terminal", wake_at
    if step in SCHEDULED_PIPELINE_STEPS:
        return LIFECYCLE_SCHEDULED, "scheduled", wake_at
    if step.startswith("waiting_listing_batch_"):
        return LIFECYCLE_ACTIVE, "listing", wake_at
    if "limited_time" in step or "campaign" in step or "traffic" in step:
        return LIFECYCLE_ACTIVE, "post_listing", wake_at
    if "listing" in step:
        return LIFECYCLE_ACTIVE, "listing", wake_at
    return LIFECYCLE_ACTIVE, "active", wake_at


def sync_lifecycle_from_integrated_pipeline(row: IntegratedPipelineORM) -> None:
    if not commerce_enabled():
        return
    try:
        from pdd_agent.api.services.pipeline_mq_auto_commerce import should_mq_pipeline_skip_commerce_sync

        if should_mq_pipeline_skip_commerce_sync(row):
            return
    except Exception:
        logger.exception("mq commerce sync skip check failed pipeline=%s", getattr(row, "pipeline_id", ""))
    account_id = str(row.account_id or "").strip()
    pipeline_id = str(row.pipeline_id or "").strip()
    if not account_id or not pipeline_id:
        return

    lifecycle_status, phase, wake_at = _pipeline_lifecycle_status(row)
    with session_scope() as session:
        lc = session.get(AccountLifecycleORM, account_id)
        if lc and lc.owner_type == "integrated_pipeline" and lc.owner_id != pipeline_id:
            return
        if lifecycle_status in LIFECYCLE_TERMINAL:
            lifecycle_id = lc.lifecycle_id if lc else ""
            session.execute(delete(AccountLifecycleORM).where(AccountLifecycleORM.account_id == account_id))
            if lifecycle_id:
                session.execute(
                    delete(ProductClaimORM).where(ProductClaimORM.lifecycle_id == lifecycle_id)
                )
            session.flush()
        elif lc:
            lc.lifecycle_status = lifecycle_status
            lc.phase = phase
            lc.wake_at = wake_at
            lc.updated_at = datetime.now()
        else:
            lifecycle_id = _new_lifecycle_id()
            session.add(
                AccountLifecycleORM(
                    account_id=account_id,
                    lifecycle_id=lifecycle_id,
                    owner_type="integrated_pipeline",
                    owner_id=pipeline_id,
                    trigger_source=str((row.meta or {}).get("commerce_trigger_source") or "manual"),
                    phase=phase,
                    lifecycle_status=lifecycle_status,
                    wake_at=wake_at,
                    product_selectors=list(row.product_codes or []),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )

    if lifecycle_status in LIFECYCLE_TERMINAL:
        try_dispatch_pending_for_account(account_id)


def sync_failure_sequential_job_lifecycle(
    *,
    account_id: str,
    job_id: str,
    product_selectors: list[str],
    phase: str,
    lifecycle_status: str,
    wake_at: datetime | None = None,
) -> None:
    if not commerce_enabled():
        return
    account_id = str(account_id or "").strip()
    job_id = str(job_id or "").strip()
    if not account_id or not job_id:
        return

    status = str(lifecycle_status or LIFECYCLE_ACTIVE).strip()
    with session_scope() as session:
        lc = session.get(AccountLifecycleORM, account_id)
        if status in LIFECYCLE_TERMINAL:
            lifecycle_id = lc.lifecycle_id if lc else ""
            session.execute(delete(AccountLifecycleORM).where(AccountLifecycleORM.account_id == account_id))
            if lifecycle_id:
                session.execute(
                    delete(ProductClaimORM).where(ProductClaimORM.lifecycle_id == lifecycle_id)
                )
        elif lc and lc.owner_type == "failure_sequential":
            lc.phase = str(phase or lc.phase)
            lc.lifecycle_status = status
            lc.wake_at = wake_at
            lc.owner_id = job_id
            lc.product_selectors = normalize_selectors(product_selectors)
            lc.updated_at = datetime.now()
        elif not lc:
            register_failure_sequential_lifecycle(
                account_id=account_id,
                job_id=job_id,
                product_selectors=product_selectors,
            )

    if status in LIFECYCLE_TERMINAL:
        try_dispatch_pending_for_account(account_id)


def gate_failure_sequential_job(
    *,
    account_id: str,
    product_selectors: list[str],
) -> tuple[bool, str]:
    gate = evaluate_commerce_gate(
        account_id=account_id,
        product_selectors=product_selectors,
        trigger_source="failure_sequential",
    )
    if gate.get("allowed"):
        return True, ""
    reason = str(gate.get("block_reason") or "account_active")
    return False, format_block_reason(
        reason,
        detail=str(gate.get("block_detail") or ""),
        wake_at=gate.get("wake_at"),
    )


def try_dispatch_pending_for_account(account_id: str) -> dict[str, Any] | None:
    """店铺周期结束后，尝试启动队首 pending 意图。"""
    if not commerce_enabled():
        return None
    account_id = str(account_id or "").strip()
    if not account_id:
        return None

    lifecycle = _get_account_lifecycle(account_id)
    if lifecycle and lifecycle.lifecycle_status not in LIFECYCLE_TERMINAL:
        return None

    with session_scope() as session:
        intent = session.scalar(
            select(CommerceIntentORM)
            .where(
                CommerceIntentORM.account_id == account_id,
                CommerceIntentORM.status == "pending",
            )
            .order_by(
                CommerceIntentORM.priority.desc(),
                CommerceIntentORM.created_at.asc(),
            )
            .limit(1)
        )
        if not intent:
            return None
        session.expunge(intent)

    payload = _restore_pipeline_payload(dict(intent.payload or {}))
    product_codes = list(intent.product_selectors or payload.pop("product_codes", []))
    trigger_source = str(intent.trigger_source or payload.pop("trigger_source", "manual"))

    from pdd_agent.api.services.pipeline_service import start_integrated_pipeline

    try:
        result = start_integrated_pipeline(
            account_id=account_id,
            product_codes=product_codes,
            trigger_source=trigger_source,
            skip_commerce_gate=True,
            commerce_intent_id=intent.intent_id,
            **payload,
        )
    except Exception as exc:
        logger.exception(
            "commerce dispatch failed intent_id=%s account=%s",
            intent.intent_id,
            account_id,
        )
        with session_scope() as session:
            row = session.get(CommerceIntentORM, intent.intent_id)
            if row:
                row.status = "rejected"
                row.block_detail = str(exc)
                row.updated_at = datetime.now()
        return {"intent_id": intent.intent_id, "dispatched": False, "error": str(exc)}

    if result.get("commerce_queued"):
        return {"intent_id": intent.intent_id, "dispatched": False, "queued_again": True}

    logger.info(
        "commerce intent dispatched intent_id=%s pipeline_id=%s account=%s",
        intent.intent_id,
        result.get("pipeline_id"),
        account_id,
    )
    _try_notify_commerce_dispatched(
        account_id=account_id,
        intent_id=intent.intent_id,
        pipeline_id=str(result.get("pipeline_id") or ""),
        product_codes=product_codes,
        trigger_source=trigger_source,
    )
    return {
        "intent_id": intent.intent_id,
        "dispatched": True,
        "pipeline_id": result.get("pipeline_id"),
    }


def dispatch_all_pending_intents(*, limit: int = 20) -> list[dict[str, Any]]:
    """扫描有 pending 意图且店铺空闲的 account，批量尝试派发。"""
    if not commerce_enabled():
        return []
    with session_scope() as session:
        account_ids = list(
            session.scalars(
                select(CommerceIntentORM.account_id)
                .where(CommerceIntentORM.status == "pending")
                .distinct()
                .limit(max(1, limit))
            ).all()
        )
    outcomes: list[dict[str, Any]] = []
    for account_id in account_ids:
        outcome = try_dispatch_pending_for_account(account_id)
        if outcome:
            outcomes.append(outcome)
    return outcomes


_PIPELINE_PAYLOAD_KEYS = frozenset(
    {
        "activity_id",
        "activity_ids",
        "category_keyword",
        "auto_promotion",
        "auto_limited_time_setup",
        "continue_after_limited_time_failure",
        "continue_after_activity_failure",
        "promote_after_limited_time_failure",
        "activity_delay_hours",
        "demo_mode",
        "platform_listing_code",
        "slot_alignment_test",
        "spec_fill_verify_test",
        "primary_style_first_test",
        "category_next_burst_demo",
        "listing_scheduled_at",
        "batch_id",
        "skip_listing",
        "listing_skip_selectors",
        "material_source",
        "listing_input_mode",
        "relist_strategy",
        "listing_throttle_enabled",
        "listing_batch_set_count",
        "listing_batch_interval_minutes",
        "listing_per_batch_limited_time_enabled",
        "listing_per_batch_campaign_enabled",
        "listing_per_batch_lt_traffic_activity_enabled",
        "listing_per_batch_promote_lt_success_only_enabled",
        "delist_spec_code_search_enabled",
        "activity_limited_time_success_only",
        "activity_traffic_batch_enabled",
        "activity_traffic_batch_size",
        "extra_meta",
    }
)


def build_pipeline_payload_from_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """从 start_integrated_pipeline 参数提取可序列化 payload（不含 account/product）。"""
    payload: dict[str, Any] = {}
    for key in _PIPELINE_PAYLOAD_KEYS:
        if key not in kwargs:
            continue
        value = kwargs[key]
        if isinstance(value, datetime):
            payload[key] = value.isoformat(timespec="seconds")
        elif value is not None:
            payload[key] = value
    payload["trigger_source"] = str(kwargs.get("trigger_source") or "manual")
    return payload


def _restore_pipeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    restored = dict(payload or {})
    restored.pop("trigger_source", None)
    raw_scheduled = restored.get("listing_scheduled_at")
    if isinstance(raw_scheduled, str) and raw_scheduled.strip():
        try:
            restored["listing_scheduled_at"] = datetime.fromisoformat(raw_scheduled)
        except ValueError:
            restored.pop("listing_scheduled_at", None)
    return restored


def lifecycle_to_dict(row: AccountLifecycleORM | None) -> dict[str, Any]:
    if not row:
        return {}
    wake = ""
    if row.wake_at:
        wake = row.wake_at.isoformat(timespec="seconds")
    return {
        "account_id": row.account_id,
        "lifecycle_id": row.lifecycle_id,
        "owner_type": row.owner_type,
        "owner_id": row.owner_id,
        "trigger_source": row.trigger_source,
        "phase": row.phase,
        "lifecycle_status": row.lifecycle_status,
        "wake_at": wake,
        "product_selectors": list(row.product_selectors or []),
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else "",
    }


def intent_to_dict(row: CommerceIntentORM) -> dict[str, Any]:
    wake = ""
    dispatched = ""
    if row.dispatched_at:
        dispatched = row.dispatched_at.isoformat(timespec="seconds")
    return {
        "intent_id": row.intent_id,
        "account_id": row.account_id,
        "trigger_source": row.trigger_source,
        "priority": row.priority,
        "product_selectors": list(row.product_selectors or []),
        "status": row.status,
        "block_reason": row.block_reason,
        "block_reason_label": format_block_reason(row.block_reason, detail=row.block_detail),
        "block_detail": row.block_detail,
        "result_pipeline_id": row.result_pipeline_id,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
        "dispatched_at": dispatched,
        "is_merged": str(row.block_reason or "") == "duplicate_pending",
    }


def list_pending_intents(*, account_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    if not commerce_enabled():
        return []
    with session_scope() as session:
        stmt = select(CommerceIntentORM).where(CommerceIntentORM.status == "pending")
        if account_id:
            stmt = stmt.where(CommerceIntentORM.account_id == account_id)
        stmt = stmt.order_by(
            CommerceIntentORM.priority.desc(),
            CommerceIntentORM.created_at.asc(),
        ).limit(max(1, min(limit, 200)))
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
    return [intent_to_dict(row) for row in rows]


def get_account_lifecycle_status(account_id: str) -> dict[str, Any]:
    return lifecycle_to_dict(_get_account_lifecycle(account_id))


def list_active_account_lifecycles(*, limit: int = 100) -> list[dict[str, Any]]:
    if not commerce_enabled():
        return []
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(AccountLifecycleORM)
                .where(AccountLifecycleORM.lifecycle_status.notin_(list(LIFECYCLE_TERMINAL)))
                .order_by(AccountLifecycleORM.updated_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
        )
        for row in rows:
            session.expunge(row)
    return [lifecycle_to_dict(row) for row in rows]


def get_commerce_overview(*, intent_limit: int = 100) -> dict[str, Any]:
    """整合链路页：活跃店铺周期 + 排队意图汇总。"""
    if not commerce_enabled():
        return {
            "lifecycles": [],
            "pending_intents": [],
            "pending_total": 0,
            "pending_by_account": {},
        }
    from pdd_agent.api.services.commerce_overview_sync import refresh_commerce_overview_state

    refresh_commerce_overview_state(dispatch_pending=False)
    lifecycles = list_active_account_lifecycles()
    pending = list_pending_intents(limit=intent_limit)
    pending_by_account: dict[str, int] = {}
    for item in pending:
        aid = str(item.get("account_id") or "").strip()
        if not aid:
            continue
        pending_by_account[aid] = pending_by_account.get(aid, 0) + 1
    return {
        "lifecycles": lifecycles,
        "pending_intents": pending,
        "pending_total": len(pending),
        "pending_by_account": pending_by_account,
    }


def _try_notify_commerce_queued(queued: dict[str, Any], *, trigger_source: str) -> None:
    if not queued.get("commerce_queued"):
        return
    if str(queued.get("block_reason") or "") == "duplicate_pending":
        return
    try:
        from pdd_agent.integrations.wecom.notify import notify_commerce_queued

        notify_commerce_queued(
            account_id=str(queued.get("account_id") or ""),
            intent_id=str(queued.get("intent_id") or ""),
            product_codes=list(queued.get("product_codes") or []),
            trigger_source=trigger_source,
            block_reason=str(queued.get("block_reason") or ""),
            block_reason_label=str(queued.get("block_reason_label") or ""),
        )
    except Exception:
        logger.warning("wecom commerce queued notify failed", exc_info=True)


def _try_notify_commerce_dispatched(
    *,
    account_id: str,
    intent_id: str,
    pipeline_id: str,
    product_codes: list[str],
    trigger_source: str,
) -> None:
    try:
        from pdd_agent.integrations.wecom.notify import notify_commerce_dispatched

        notify_commerce_dispatched(
            account_id=account_id,
            intent_id=intent_id,
            pipeline_id=pipeline_id,
            product_codes=product_codes,
            trigger_source=trigger_source,
        )
    except Exception:
        logger.warning("wecom commerce dispatched notify failed intent=%s", intent_id, exc_info=True)


def cancel_commerce_intent(intent_id: str) -> dict[str, Any]:
    if not commerce_enabled():
        return {"ok": False, "error": "database_unavailable"}
    intent_id = str(intent_id or "").strip()
    if not intent_id:
        return {"ok": False, "error": "intent_id_required"}
    with session_scope() as session:
        row = session.get(CommerceIntentORM, intent_id)
        if not row:
            return {"ok": False, "error": "not_found", "intent_id": intent_id}
        if row.status != "pending":
            return {
                "ok": False,
                "error": "not_pending",
                "intent_id": intent_id,
                "status": row.status,
            }
        row.status = "canceled"
        row.block_detail = "用户取消"
        row.updated_at = datetime.now()
        session.flush()
        session.expunge(row)
        canceled = intent_to_dict(row)
    logger.info("commerce intent canceled intent_id=%s", intent_id)
    return {"ok": True, "intent_id": intent_id, "intent": canceled}


def cancel_commerce_intents(
    *,
    intent_ids: list[str] | None = None,
    account_id: str = "",
    all_pending: bool = False,
) -> dict[str, Any]:
    ids = [str(x).strip() for x in (intent_ids or []) if str(x).strip()]
    aid = str(account_id or "").strip()
    if not ids and not aid and not all_pending:
        return {"ok": False, "error": "intent_ids_or_account_id_required", "canceled": []}

    canceled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    target_ids = list(ids)
    if not target_ids and all_pending:
        target_ids = [item["intent_id"] for item in list_pending_intents(limit=200)]
    elif not target_ids and aid:
        target_ids = [item["intent_id"] for item in list_pending_intents(account_id=aid, limit=200)]

    for intent_id in target_ids:
        outcome = cancel_commerce_intent(intent_id)
        if outcome.get("ok"):
            canceled.append(outcome)
        else:
            failed.append(outcome)
    return {
        "ok": bool(canceled),
        "canceled_count": len(canceled),
        "failed_count": len(failed),
        "canceled": canceled,
        "failed": failed,
    }


def _force_clear_account_lifecycle(account_id: str, *, reason: str = "") -> bool:
    """强制清除店铺运营周期与商品占用（不取消底层 pipeline）。"""
    if not commerce_enabled():
        return False
    account_id = str(account_id or "").strip()
    if not account_id:
        return False
    cleared = False
    with session_scope() as session:
        lc = session.get(AccountLifecycleORM, account_id)
        if not lc:
            return False
        lifecycle_id = str(lc.lifecycle_id or "")
        session.execute(delete(AccountLifecycleORM).where(AccountLifecycleORM.account_id == account_id))
        if lifecycle_id:
            session.execute(delete(ProductClaimORM).where(ProductClaimORM.lifecycle_id == lifecycle_id))
        cleared = True
    if cleared:
        logger.info(
            "commerce lifecycle cleared account=%s reason=%s",
            account_id,
            reason or "manual",
        )
    return cleared


def reconcile_stale_lifecycles() -> int:
    """清除 owner 链路已结束或已丢失的残留运营周期。"""
    if not commerce_enabled():
        return 0
    from pdd_agent.api.services.pipeline_service import TERMINAL_PIPELINE_STATUSES
    from pdd_agent.db.repositories import get_integrated_pipeline

    cleared = 0
    for lc in list_active_account_lifecycles():
        account_id = str(lc.get("account_id") or "").strip()
        owner_type = str(lc.get("owner_type") or "")
        owner_id = str(lc.get("owner_id") or "").strip()
        if not account_id:
            continue
        if owner_type == "integrated_pipeline" and owner_id:
            row = get_integrated_pipeline(owner_id)
            if row and str(row.status or "") not in TERMINAL_PIPELINE_STATUSES:
                continue
        elif owner_type == "failure_sequential" and owner_id:
            try:
                from pdd_agent.failure_sequential.repository import get_job

                job = get_job(owner_id)
                if job and str(job.get("status") or "") not in {"completed", "failed", "canceled"}:
                    continue
            except Exception:
                pass
        if _force_clear_account_lifecycle(account_id, reason="stale_lifecycle_reconcile"):
            cleared += 1
    return cleared


def _list_non_terminal_pipeline_ids_for_account(account_id: str) -> list[str]:
    from pdd_agent.api.services.pipeline_service import TERMINAL_PIPELINE_STATUSES
    from pdd_agent.db.repositories import list_integrated_pipelines

    account_id = str(account_id or "").strip()
    if not account_id:
        return []
    ids: list[str] = []
    for row in list_integrated_pipelines(limit=200):
        if str(row.account_id or "") != account_id:
            continue
        if str(row.status or "") in TERMINAL_PIPELINE_STATUSES:
            continue
        pid = str(row.pipeline_id or "").strip()
        if pid:
            ids.append(pid)
    return ids


def reset_account_commerce_state(
    account_id: str,
    *,
    cancel_pipelines: bool = True,
    cancel_intents: bool = True,
    clear_lifecycle: bool = True,
    reconcile_stale: bool = True,
) -> dict[str, Any]:
    """重置单店：可选取消活跃链路、清空排队、清除运营周期。"""
    account_id = str(account_id or "").strip()
    if not account_id:
        return {"ok": False, "error": "account_id_required", "account_id": account_id}

    canceled_pipelines: list[str] = []
    pipeline_errors: list[dict[str, str]] = []
    if cancel_pipelines:
        from pdd_agent.api.services.pipeline_service import cancel_integrated_pipeline

        for pipeline_id in _list_non_terminal_pipeline_ids_for_account(account_id):
            try:
                cancel_integrated_pipeline(pipeline_id)
                canceled_pipelines.append(pipeline_id)
            except Exception as exc:
                logger.warning(
                    "reset cancel pipeline failed account=%s pipeline=%s error=%s",
                    account_id,
                    pipeline_id,
                    exc,
                )
                pipeline_errors.append({"pipeline_id": pipeline_id, "error": str(exc)})

    canceled_intents = 0
    if cancel_intents:
        outcome = cancel_commerce_intents(account_id=account_id)
        canceled_intents = int(outcome.get("canceled_count") or 0)

    from pdd_agent.api.services.commerce_queue_reset import cancel_account_queue_tasks

    queue_outcome = cancel_account_queue_tasks(account_id)
    canceled_queue_tasks = int(queue_outcome.get("canceled_count") or 0)

    lifecycle_cleared = False
    if reconcile_stale:
        lc = _get_account_lifecycle(account_id)
        if lc:
            owner_type = str(lc.owner_type or "")
            owner_id = str(lc.owner_id or "")
            if owner_type == "integrated_pipeline" and owner_id:
                from pdd_agent.api.services.pipeline_service import TERMINAL_PIPELINE_STATUSES
                from pdd_agent.db.repositories import get_integrated_pipeline

                row = get_integrated_pipeline(owner_id)
                if not row or str(row.status or "") in TERMINAL_PIPELINE_STATUSES:
                    lifecycle_cleared = _force_clear_account_lifecycle(account_id, reason="reset_reconcile")
            else:
                lifecycle_cleared = _force_clear_account_lifecycle(account_id, reason="reset_reconcile")
    if clear_lifecycle and not lifecycle_cleared:
        lifecycle_cleared = _force_clear_account_lifecycle(account_id, reason="reset_force")

    had_work = bool(canceled_pipelines or canceled_intents or lifecycle_cleared or canceled_queue_tasks)
    result: dict[str, Any] = {
        "ok": had_work or not pipeline_errors,
        "account_id": account_id,
        "canceled_pipelines": canceled_pipelines,
        "canceled_intents": canceled_intents,
        "canceled_queue_tasks": canceled_queue_tasks,
        "lifecycle_cleared": lifecycle_cleared,
        "pipeline_errors": pipeline_errors,
    }
    if not had_work and not pipeline_errors:
        result["message"] = "店铺已是空闲状态"
    return result


def reset_commerce_state(
    *,
    account_ids: list[str] | None = None,
    all_accounts: bool = False,
    cancel_pipelines: bool = True,
    cancel_intents: bool = True,
    clear_lifecycle: bool = True,
) -> dict[str, Any]:
    """批量重置店铺运营状态。"""
    if not commerce_enabled():
        return {"ok": False, "error": "database_unavailable", "results": []}

    targets: set[str] = set()
    if all_accounts:
        for lc in list_active_account_lifecycles():
            aid = str(lc.get("account_id") or "").strip()
            if aid:
                targets.add(aid)
        for item in list_pending_intents(limit=200):
            aid = str(item.get("account_id") or "").strip()
            if aid:
                targets.add(aid)
        from pdd_agent.api.services.commerce_queue_reset import list_accounts_with_active_queue_tasks

        for aid in list_accounts_with_active_queue_tasks():
            targets.add(aid)
    else:
        for aid in account_ids or []:
            aid = str(aid or "").strip()
            if aid:
                targets.add(aid)

    if not targets:
        stale = reconcile_stale_lifecycles()
        from pdd_agent.api.services.commerce_queue_reset import (
            cancel_account_queue_tasks,
            list_accounts_with_active_queue_tasks,
        )

        queue_cleared = 0
        for aid in list_accounts_with_active_queue_tasks():
            outcome = cancel_account_queue_tasks(aid)
            queue_cleared += int(outcome.get("canceled_count") or 0)
        return {
            "ok": stale > 0 or queue_cleared > 0,
            "count": 0,
            "stale_cleared": stale,
            "queue_tasks_cleared": queue_cleared,
            "results": [],
            "message": (
                "没有需要重置的店铺"
                if stale <= 0 and queue_cleared <= 0
                else f"已清理残留（周期 {stale}，队列任务 {queue_cleared}）"
            ),
        }

    results = [
        reset_account_commerce_state(
            aid,
            cancel_pipelines=cancel_pipelines,
            cancel_intents=cancel_intents,
            clear_lifecycle=clear_lifecycle,
        )
        for aid in sorted(targets)
    ]
    stale = reconcile_stale_lifecycles()
    return {
        "ok": True,
        "count": len(results),
        "stale_cleared": stale,
        "results": results,
        "canceled_pipelines_total": sum(len(r.get("canceled_pipelines") or []) for r in results),
        "canceled_intents_total": sum(int(r.get("canceled_intents") or 0) for r in results),
        "canceled_queue_tasks_total": sum(int(r.get("canceled_queue_tasks") or 0) for r in results),
        "lifecycle_cleared_total": sum(1 for r in results if r.get("lifecycle_cleared")),
    }


def nudge_due_scheduled_pipelines() -> int:
    """活动预约时间已到：推进卡住的 waiting_activity 链路。"""
    if not commerce_enabled():
        return 0
    from pdd_agent.api.services.pipeline_service import (
        TERMINAL_PIPELINE_STATUSES,
        _reconcile_stuck_pipeline_row,
    )
    from pdd_agent.db.repositories import list_integrated_pipelines

    count = 0
    now = datetime.now()
    for row in list_integrated_pipelines(limit=200):
        if str(row.status or "") in TERMINAL_PIPELINE_STATUSES:
            try:
                sync_lifecycle_from_integrated_pipeline(row)
            except Exception:
                logger.exception("sync terminal pipeline lifecycle failed pipeline=%s", row.pipeline_id)
            continue
        step = str(row.current_step or "")
        scheduled_at = getattr(row, "scheduled_activity_at", None)
        if step == "waiting_activity" and scheduled_at and scheduled_at <= now:
            try:
                _reconcile_stuck_pipeline_row(row)
                count += 1
            except Exception:
                logger.exception("nudge waiting_activity pipeline failed pipeline=%s", row.pipeline_id)
    return count


def sync_lifecycle_from_active_pipelines() -> int:
    """为活跃整合链路补登记/修正店铺运营周期。"""
    if not commerce_enabled():
        return 0
    from pdd_agent.api.services.pipeline_service import TERMINAL_PIPELINE_STATUSES
    from pdd_agent.db.repositories import list_integrated_pipelines

    synced = 0
    for row in list_integrated_pipelines(limit=200):
        if str(row.status or "") in TERMINAL_PIPELINE_STATUSES:
            continue
        try:
            from pdd_agent.api.services.pipeline_mq_auto_commerce import should_mq_pipeline_skip_commerce_sync

            if should_mq_pipeline_skip_commerce_sync(row):
                continue
        except Exception:
            logger.exception("mq commerce active sync skip failed pipeline=%s", row.pipeline_id)
        lc = _get_account_lifecycle(str(row.account_id or ""))
        try:
            if not lc:
                sync_lifecycle_from_integrated_pipeline(row)
                synced += 1
            elif lc.owner_type == "integrated_pipeline" and lc.owner_id != row.pipeline_id:
                sync_lifecycle_from_integrated_pipeline(row)
                synced += 1
        except Exception:
            logger.exception("sync active pipeline lifecycle failed pipeline=%s", row.pipeline_id)
    return synced


def reconcile_commerce_state(*, dispatch_limit: int = 30) -> dict[str, Any]:
    """对账 + 活动到点推进 + 派发排队任务（调度器每轮调用）。"""
    stale = reconcile_stale_lifecycles()
    nudged = nudge_due_scheduled_pipelines()
    synced = sync_lifecycle_from_active_pipelines()
    dispatched = dispatch_all_pending_intents(limit=dispatch_limit)
    return {
        "stale_cleared": stale,
        "nudged": nudged,
        "synced": synced,
        "dispatched_count": len(dispatched),
        "dispatched": dispatched,
    }
