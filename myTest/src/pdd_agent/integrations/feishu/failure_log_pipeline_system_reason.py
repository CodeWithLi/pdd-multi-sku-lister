"""失败日志「系统原因」字段：承载整合链路 pipeline_id（不改飞书表结构）。

约定格式：`[pipeline:{pipeline_id}]`
- 有链路 id → 写入该格式
- 无链路 id → 留空（不再写入技术诊断文案）
后续可用 parse_pipeline_id_from_system_reason 切割取出。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping

from pdd_agent.core.logging import get_logger

logger = get_logger(__name__)

PIPELINE_SYSTEM_REASON_PREFIX = "[pipeline:"
PIPELINE_SYSTEM_REASON_SUFFIX = "]"
_PIPELINE_SYSTEM_REASON_RE = re.compile(
    r"\[pipeline:([^\]]+)\]",
    flags=re.IGNORECASE,
)


def format_pipeline_system_reason(pipeline_id: str = "") -> str:
    """将 pipeline_id 格式化为系统原因；空 id 返回空串。"""
    pid = str(pipeline_id or "").strip()
    if not pid:
        return ""
    return f"{PIPELINE_SYSTEM_REASON_PREFIX}{pid}{PIPELINE_SYSTEM_REASON_SUFFIX}"


def parse_pipeline_id_from_system_reason(text: str = "") -> str:
    """从系统原因文本中切割 pipeline_id；无法解析则返回空串。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = _PIPELINE_SYSTEM_REASON_RE.search(raw)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def lookup_pipeline_id_for_listing_run(run_id: str = "") -> str:
    """按上架 run_id 反查整合链路 id（当前 listing_run_id 或任务队列 payload）。"""
    rid = str(run_id or "").strip()
    if not rid:
        return ""

    try:
        from pdd_agent.db.repositories import get_integrated_pipeline_by_listing_run_id

        row = get_integrated_pipeline_by_listing_run_id(rid)
        pid = str(getattr(row, "pipeline_id", "") or "").strip() if row is not None else ""
        if pid:
            return pid
    except Exception:
        logger.debug("lookup pipeline by listing_run_id failed run_id=%s", rid, exc_info=True)

    try:
        from pdd_agent.db.models import TaskQueueORM
        from pdd_agent.db.session import is_database_available, session_scope

        if not is_database_available():
            return ""
        with session_scope() as session:
            task = (
                session.query(TaskQueueORM)
                .filter(TaskQueueORM.run_id == rid)
                .order_by(TaskQueueORM.updated_at.desc())
                .first()
            )
            if task is None:
                return ""
            payload = task.payload if isinstance(task.payload, dict) else {}
            return str(payload.get("pipeline_id") or "").strip()
    except Exception:
        logger.debug("lookup pipeline by task_queue failed run_id=%s", rid, exc_info=True)
        return ""


def resolve_pipeline_id_for_failure_log(
    *,
    pipeline_id: str = "",
    run_id: str = "",
    system_reason: str = "",
) -> str:
    """解析失败日志要用的 pipeline_id：显式参数 > 已有系统原因标签 > run_id 反查。"""
    pid = str(pipeline_id or "").strip()
    if pid:
        return pid
    pid = parse_pipeline_id_from_system_reason(system_reason)
    if pid:
        return pid
    return lookup_pipeline_id_for_listing_run(run_id)


def build_failure_log_system_reason(
    *,
    pipeline_id: str = "",
    run_id: str = "",
    system_reason: str = "",
) -> str:
    """构建失败表「系统原因」：有链路写 `[pipeline:id]`，否则空串。"""
    pid = resolve_pipeline_id_for_failure_log(
        pipeline_id=pipeline_id,
        run_id=run_id,
        system_reason=system_reason,
    )
    return format_pipeline_system_reason(pid)


def prepare_failure_log_system_reason_kwargs(
    kwargs: Mapping[str, Any] | MutableMapping[str, Any],
) -> dict[str, Any]:
    """规范化写入失败日志的 kwargs：强制用封装规则覆盖 system_reason。

    仍保留 pipeline_id / run_id 键，便于下游忽略或继续使用。
    """
    out = dict(kwargs)
    out["system_reason"] = build_failure_log_system_reason(
        pipeline_id=str(out.get("pipeline_id") or ""),
        run_id=str(out.get("run_id") or ""),
        system_reason=str(out.get("system_reason") or ""),
    )
    return out
