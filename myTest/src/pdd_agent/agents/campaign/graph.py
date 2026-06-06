"""Campaign Agent 占位 — 活动报名、素材上传。"""

from typing import TypedDict

from langgraph.graph import END, StateGraph


class CampaignState(TypedDict, total=False):
    account_id: str
    message: str


async def campaign_stub(state: CampaignState) -> dict:
    return {"message": "campaign agent not implemented yet"}


def build_campaign_graph():
    graph = StateGraph(CampaignState)
    graph.add_node("stub", campaign_stub)
    graph.set_entry_point("stub")
    graph.add_edge("stub", END)
    return graph.compile()
