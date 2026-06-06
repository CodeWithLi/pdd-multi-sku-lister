"""
Orchestrator Agent — 自然语言指令 → PlannedTask 列表。

流程：plan 节点（LLM 或规则 fallback）→ END
后续可扩展：dispatch 节点将任务路由到 listing/delist 子图。
"""

from __future__ import annotations

import json
import re

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import OrchestratorState
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.domain.enums import AgentKind
from pdd_agent.domain.models import PlannedTask
from pdd_agent.llm import create_orchestrator_model
from pdd_agent.paths import PROMPTS_DIR

logger = get_logger(__name__)


def _load_system_prompt() -> str:
    """读取 prompts/orchestrator.md 作为系统提示。"""
    path = PROMPTS_DIR / "orchestrator.md"
    return path.read_text(encoding="utf-8") if path.is_file() else "你是运营编排助手。"


def plan_node(state: OrchestratorState) -> dict:
    """
    规划节点：有 LLM_API_KEY 时调用大模型解析 JSON；
    失败或未配置时走 _rule_based_plan 正则 fallback。
    """
    message = state.get("user_message", "")
    settings = load_yaml_settings()

    from pdd_agent.core.config import get_env_settings

    env = get_env_settings()
    tasks: list[PlannedTask] = []

    if env.llm_api_key:
        model = create_orchestrator_model()
        prompt = (
            f"{_load_system_prompt()}\n\n"
            f"用户指令：{message}\n\n"
            "请以 JSON 数组回复，每项含 agent, account_id, product_codes, dry_run。"
        )
        try:
            resp = model.invoke(prompt)
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            # 从回复中提取 JSON 数组
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                raw = json.loads(match.group())
                for item in raw:
                    tasks.append(
                        PlannedTask(
                            agent=AgentKind(item.get("agent", "listing")),
                            account_id=item.get("account_id") or "",
                            product_codes=item.get("product_codes") or [],
                            dry_run=bool(item.get("dry_run", False)),
                        )
                    )
        except Exception as exc:
            logger.warning("LLM plan failed, fallback: %s", exc)

    if not tasks:
        tasks = _rule_based_plan(message, settings)

    summary = "; ".join(
        f"{t.agent.value}@{t.account_id or 'auto'} codes={t.product_codes} dry={t.dry_run}"
        for t in tasks
    )
    return {"planned_tasks": tasks, "plan_summary": summary}


def _rule_based_plan(message: str, settings) -> list[PlannedTask]:
    """
    无 LLM 时的规则解析：
    - 含「检查/校验/dry」→ dry_run=True
    - 正则提取 BDxxx 商品编码
    - 仅一个 enabled 店铺时自动选中
    """
    dry_run = any(k in message for k in ("检查", "校验", "dry", "看看"))
    codes = re.findall(r"BD\d+[A-Z]?", message.upper())
    account_id = ""
    for acc in settings.accounts:
        if acc.account_id in message:
            account_id = acc.account_id
            break
    if not account_id:
        enabled = [a for a in settings.accounts if a.enabled]
        if len(enabled) == 1:
            account_id = enabled[0].account_id
            codes = codes or enabled[0].product_codes

    return [
        PlannedTask(
            agent=AgentKind.LISTING,
            account_id=account_id,
            product_codes=codes,
            dry_run=dry_run,
        )
    ]


def build_orchestrator_graph():
    """编译 Orchestrator 状态图。"""
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", plan_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", END)
    return graph.compile()
