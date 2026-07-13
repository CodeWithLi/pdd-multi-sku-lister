"""
CLI 入口。

子命令：
  plan   — 运行 Orchestrator，解析自然语言为任务计划
  run    — 运行 listing 子图
  api    — 启动 FastAPI
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dy_agent.agents.listing import build_listing_graph
from dy_agent.agents.orchestrator import build_orchestrator_graph
from dy_agent.api.services.listing_state import listing_flags_from_settings
from dy_agent.core.config import load_yaml_settings
from dy_agent.db.repositories import get_account_config
from dy_agent.core.logging import setup_logging
from dy_agent.domain.enums import AgentKind, RunStatus
from dy_agent.integrations.feishu.listing_bootstrap import bootstrap_listing_feishu
from dy_agent.storage import TaskRunStore


def cli() -> None:
    parser = argparse.ArgumentParser(description="抖音运营智能体平台 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Orchestrator 自然语言规划")
    plan_p.add_argument("--message", "-m", required=True)

    run_p = sub.add_parser("run", help="运行指定 Agent 子图")
    run_p.add_argument("agent", choices=["listing"])
    run_p.add_argument("--account", required=True)
    run_p.add_argument("--product-code", action="append", dest="product_codes")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--category", default="")
    run_p.add_argument("--slot-alignment-test", action="store_true")
    run_p.add_argument("--spec-fill-verify-test", action="store_true")
    run_p.add_argument("--primary-style-first-test", action="store_true")
    run_p.add_argument("--no-category-next-burst", action="store_true")
    run_p.add_argument("--accessory-cost-pricing", action="store_true")
    run_p.add_argument("--accessory-tiered-float", action="store_true")

    api_p = sub.add_parser("api", help="启动 FastAPI 服务")
    api_p.add_argument("--host", default="127.0.0.1")
    api_p.add_argument("--port", type=int, default=8020)

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
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": message})
    print("Plan:", result.get("plan_summary"))
    for task in result.get("planned_tasks", []):
        print(" ", task.model_dump())


def _json_safe(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _summarize_listing_message(result: dict) -> str:
    if result.get("errors"):
        return "; ".join(str(e) for e in result["errors"])
    results = result.get("results") or []
    if not results:
        return "listing finished"
    first = results[0] if isinstance(results[0], dict) else {}
    if first.get("summary"):
        return str(first["summary"])
    if first.get("message"):
        return str(first["message"])
    if first.get("status") == "success":
        pid = first.get("dy_product_id") or (first.get("goods_list_capture") or {}).get("dy_product_id")
        return f"{first.get('listing_label', '')} 发布成功 ID={pid or '-'}"
    if first.get("status") == "step5_done":
        return f"{first.get('listing_label', '')} step5 完成（价格/库存/商家编码）"
    if first.get("status") == "step4_done":
        return f"{first.get('listing_label', '')} step4 完成（颜色分类/尺寸大小）"
    if first.get("status") == "step3_done":
        return f"{first.get('listing_label', '')} step3 完成（价格库存/手动填写）"
    if first.get("status") == "step2_done":
        return f"{first.get('listing_label', '')} step2 完成（白底图/详情图）"
    if first.get("status") == "step1_done":
        return f"{first.get('listing_label', '')} step1 完成"
    return "listing finished"


async def _cmd_run(args) -> None:
    settings = load_yaml_settings()
    account = get_account_config(settings, args.account)
    if not account:
        print(f"unknown account: {args.account}")
        sys.exit(1)

    codes = args.product_codes or account.product_codes
    store = TaskRunStore()
    run = store.create_run(AgentKind.LISTING, args.account)

    graph = build_listing_graph()
    listing_flags = listing_flags_from_settings(settings)
    if args.no_category_next_burst:
        listing_flags["category_next_burst_demo"] = False
    if args.slot_alignment_test:
        listing_flags["slot_alignment_test"] = True
    if args.spec_fill_verify_test:
        listing_flags["spec_fill_verify_test"] = True
    if args.primary_style_first_test:
        listing_flags["primary_style_first_test"] = True
    if args.accessory_cost_pricing:
        listing_flags["accessory_cost_pricing"] = True
    if args.accessory_tiered_float:
        listing_flags["accessory_tiered_float"] = True

    bootstrap_listing_feishu(
        accessory_cost_pricing=bool(listing_flags.get("accessory_cost_pricing")),
        accessory_tiered_float=bool(listing_flags.get("accessory_tiered_float")),
    )

    result = await graph.ainvoke(
        {
            "account_id": args.account,
            "product_codes": codes,
            "dry_run": args.dry_run,
            "category_keyword": args.category or settings.listing.category_keyword,
            "run_id": run.run_id,
            **listing_flags,
        }
    )
    result = _json_safe(result)
    status = RunStatus.SUCCESS if not result.get("errors") else RunStatus.FAILED
    store.finish(run.run_id, status, _summarize_listing_message(result), result=result)
    print(result)


def _cmd_api(host: str, port: int) -> None:
    import uvicorn

    from dy_agent.api import create_app

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    cli()
