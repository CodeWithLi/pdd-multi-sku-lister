"""Agent 能力查询。"""

from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["agents"])

# 与 config/agents.example.yaml 保持一致，后续可改为读 YAML
_AGENTS = [
    {"id": "orchestrator", "enabled": True, "description": "自然语言任务编排"},
    {"id": "listing", "enabled": True, "description": "多规格商品上架"},
    {"id": "delist", "enabled": True, "description": "在售商品扫描与批量下架"},
    {"id": "campaign", "enabled": True, "description": "限时限量购活动设置"},
    {"id": "traffic", "enabled": False, "description": "推广投流（占位）"},
]


@router.get("")
def list_agents():
    """可用 Agent 列表。"""
    return {"agents": _AGENTS}
