"""Delist Agent 占位 — 后续从旧项目 pdd_auto/delist 迁移。"""

from typing import TypedDict

from langgraph.graph import END, StateGraph


class DelistState(TypedDict, total=False):
    account_id: str
    dry_run: bool
    message: str


async def delist_stub(state: DelistState) -> dict:
    return {"message": "delist agent not implemented yet"}


def build_delist_graph():
    graph = StateGraph(DelistState)
    graph.add_node("stub", delist_stub)
    graph.set_entry_point("stub")
    graph.add_edge("stub", END)
    return graph.compile()
