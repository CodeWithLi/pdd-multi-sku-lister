"""Traffic Agent 占位 — 推广投流配置。"""

from typing import TypedDict

from langgraph.graph import END, StateGraph


class TrafficState(TypedDict, total=False):
    account_id: str
    message: str


async def traffic_stub(state: TrafficState) -> dict:
    return {"message": "traffic agent not implemented yet"}


def build_traffic_graph():
    graph = StateGraph(TrafficState)
    graph.add_node("stub", traffic_stub)
    graph.set_entry_point("stub")
    graph.add_edge("stub", END)
    return graph.compile()
