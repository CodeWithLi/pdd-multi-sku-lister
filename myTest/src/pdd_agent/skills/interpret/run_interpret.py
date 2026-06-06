"""将任务运行记录交给 LLM，生成运营可读的解读。"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from pdd_agent.core.config import get_env_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.models import RunRecord
from pdd_agent.llm import create_chat_model
from pdd_agent.paths import PROMPTS_DIR

logger = get_logger(__name__)

_AGENT_LABEL = {
    "listing": "商品上架",
    "delist": "商品下架",
    "orchestrator": "智能规划",
    "campaign": "活动报名",
    "traffic": "推广投流",
}

_STATUS_LABEL = {
    "success": "成功",
    "failed": "失败",
    "running": "进行中",
    "pending": "等待中",
    "needs_human": "需人工处理",
    "skipped": "已跳过",
}

_RESULT_KEYS = (
    "listing_label",
    "status",
    "error",
    "title",
    "scanned",
    "hit",
    "skipped_old",
    "skipped_other",
    "pages",
    "account_id",
)


def _load_system_prompt() -> str:
    path = PROMPTS_DIR / "run_interpret.md"
    return path.read_text(encoding="utf-8") if path.is_file() else "你是运维解读助手，用中文解释任务结果。"


def build_run_context(record: RunRecord) -> dict:
    """压缩运行记录，去掉 SKU/路径等大字段，便于 LLM 理解。"""
    result = record.result or {}
    agent = record.agent.value if hasattr(record.agent, "value") else str(record.agent)
    status = record.status.value if hasattr(record.status, "value") else str(record.status)

    compact: dict = {
        "run_id": record.run_id,
        "操作类型": _AGENT_LABEL.get(agent, agent),
        "店铺": record.account_id,
        "任务结果": _STATUS_LABEL.get(status, status),
        "执行阶段": record.phase.value if hasattr(record.phase, "value") else str(record.phase),
        "开始时间": record.started_at.isoformat() if record.started_at else "",
        "结束时间": record.finished_at.isoformat() if record.finished_at else "",
        "系统消息": record.message,
        "涉及商品": record.listing_labels,
        "错误列表": result.get("errors") or [],
        "是否仅检查": result.get("dry_run"),
        "商品编码": result.get("product_codes"),
        "类目关键词": result.get("category_keyword"),
    }

    rows = []
    for item in result.get("results") or []:
        if isinstance(item, dict):
            rows.append({k: item[k] for k in _RESULT_KEYS if k in item})
    compact["明细结果"] = rows

    preflight = result.get("preflight") or {}
    issues = preflight.get("issues") or []
    compact["素材检查问题"] = [
        {
            "级别": i.get("level"),
            "商品": i.get("listing_label"),
            "说明": i.get("message"),
        }
        for i in issues
        if isinstance(i, dict)
    ]

    if result.get("delist_params"):
        compact["下架参数"] = result["delist_params"]

    units = result.get("units") or []
    if units:
        compact["待处理套图数"] = len(units)

    return compact


def interpret_run(record: RunRecord) -> str:
    """调用 LLM 解读单条运行记录，返回 Markdown 文本。"""
    env = get_env_settings()
    if not env.llm_api_key:
        raise RuntimeError("未配置 LLM_API_KEY，请在 myTest/.env 中填写后重启后台")

    context = build_run_context(record)
    system = _load_system_prompt()
    user_text = (
        "请解读以下操作记录，帮助运营同事理解结果并知道下一步怎么做：\n\n"
        f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
    )

    model = create_chat_model(temperature=0.2)
    logger.info("interpret run_id=%s agent=%s", record.run_id, record.agent)
    resp = model.invoke([SystemMessage(content=system), HumanMessage(content=user_text)])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return content.strip()
