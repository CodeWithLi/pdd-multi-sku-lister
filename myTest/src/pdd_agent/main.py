"""
CLI 入口。

子命令：
  plan   — 运行 Orchestrator，解析自然语言为任务计划
  run    — 运行 listing/delist 子图
  api    — 启动 FastAPI（后续接 Vue3）
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pdd_agent.agents.listing import build_listing_graph
from pdd_agent.agents.orchestrator import build_orchestrator_graph
from pdd_agent.core.config import get_account, load_yaml_settings
from pdd_agent.core.logging import setup_logging
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore


def cli() -> None:
    parser = argparse.ArgumentParser(description="PDD Agent Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Orchestrator 自然语言规划")
    plan_p.add_argument("--message", "-m", required=True, help="用户指令")

    run_p = sub.add_parser("run", help="运行指定 Agent 子图")
    run_p.add_argument("agent", choices=["listing", "delist"])
    run_p.add_argument("--account", required=True)
    run_p.add_argument("--product-code", action="append", dest="product_codes")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--category", default="玩偶")

    api_p = sub.add_parser("api", help="启动 FastAPI 服务")
    api_p.add_argument("--host", default="127.0.0.1")
    api_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))

    if args.command == "plan":
        _cmd_plan(args.message)
    elif args.command == "run":
        asyncio.run(_cmd_run(args))
    elif args.command == "api":
        _cmd_api(args.host, args.port)


def _cmd_plan(message: str) -> None:
    """执行 Orchestrator 图并打印计划。"""
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": message})
    print("Plan:", result.get("plan_summary"))
    for task in result.get("planned_tasks", []):
        print(" ", task.model_dump())


async def _cmd_run(args) -> None:
    """执行 listing 子图，并将结果写入 TaskRunStore。"""
    settings = load_yaml_settings()
    account = get_account(settings, args.account)
    if not account:
        print(f"unknown account: {args.account}")
        sys.exit(1)

    codes = args.product_codes or account.product_codes
    store = TaskRunStore()
    run = store.create_run(AgentKind.LISTING, args.account)

    if args.agent == "listing":
        graph = build_listing_graph()
        result = await graph.ainvoke(
            {
                "account_id": args.account,
                "product_codes": codes,
                "dry_run": args.dry_run,
                "category_keyword": args.category,
            }
        )
        status = RunStatus.SUCCESS if not result.get("errors") else RunStatus.FAILED
        store.finish(run.run_id, status, str(result.get("results")))
        print(result)
    else:
        print("delist graph: use API or extend CLI")


def _cmd_api(host: str, port: int) -> None:
    """启动 uvicorn + FastAPI。"""
    import uvicorn

    from pdd_agent.api import create_app

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    cli()
