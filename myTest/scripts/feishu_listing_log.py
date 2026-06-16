#!/usr/bin/env python
"""
飞书「拼多多每日上架商品日志」独立 CLI（不修改现有 main.py / API）。

用法：
  python scripts/feishu_listing_log.py check-config
  python scripts/feishu_listing_log.py init-table
  python scripts/feishu_listing_log.py sync-today
  python scripts/feishu_listing_log.py sync --date 2026-06-16
  python scripts/feishu_listing_log.py sync --date 2026-06-16 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# 允许在未 pip install -e 时从仓库根运行
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient  # noqa: E402
from pdd_agent.integrations.feishu.config import DEFAULT_FEISHU_CONFIG_PATH, load_feishu_config  # noqa: E402
from pdd_agent.integrations.feishu.listing_log import (  # noqa: E402
    LISTING_LOG_TABLE_NAME,
    ensure_listing_log_table,
    list_published_products_for_date,
    sync_listing_log_for_date,
)


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def cmd_check_config() -> int:
    cfg = load_feishu_config()
    masked_secret = (cfg.app_secret[:4] + "****") if cfg.app_secret else ""
    print(
        json.dumps(
            {
                "config_path": str(DEFAULT_FEISHU_CONFIG_PATH),
                "app_id": cfg.app_id,
                "app_secret": masked_secret,
                "bitable_app_token": cfg.bitable_app_token,
                "table_id": cfg.table_id,
                "table_name": LISTING_LOG_TABLE_NAME,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not cfg.app_id or not cfg.app_secret or not cfg.bitable_app_token:
        print("\n缺少必要配置，请参考 config/feishu.example.yaml", file=sys.stderr)
        return 1
    try:
        client = FeishuClient(cfg)
        token = client.get_tenant_access_token()
        print(f"\nOK: tenant_access_token 获取成功（长度 {len(token)}）")
        return 0
    except FeishuAPIError as exc:
        print(f"\n失败: {exc}", file=sys.stderr)
        return 2


def cmd_init_table() -> int:
    cfg = load_feishu_config()
    try:
        table_id = ensure_listing_log_table(cfg)
        print(
            json.dumps(
                {
                    "table_name": LISTING_LOG_TABLE_NAME,
                    "table_id": table_id,
                    "message": "表与字段已就绪，table_id 已写入 feishu.yaml（若之前为空）",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except FeishuAPIError as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 2


def cmd_preview(day: date) -> int:
    rows = list_published_products_for_date(day)
    print(
        json.dumps(
            {
                "date": day.isoformat(),
                "count": len(rows),
                "items": [
                    {
                        "mapping_id": r.mapping_id,
                        "account_id": r.account_id,
                        "product_code": r.product_code,
                        "listing_label": r.listing_label,
                        "pdd_product_id": r.pdd_product_id,
                        "published_at": (r.published_at or r.created_at).isoformat()
                        if (r.published_at or r.created_at)
                        else "",
                    }
                    for r in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_sync(day: date, *, dry_run: bool, minimal_fields: bool = True) -> int:
    try:
        result = sync_listing_log_for_date(day, dry_run=dry_run, minimal_fields=minimal_fields)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FeishuAPIError, RuntimeError) as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="飞书拼多多每日上架商品日志同步")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-config", help="检查 feishu.yaml / .env 与 token")

    sub.add_parser("init-table", help="在多维表格中创建表与字段")

    preview_p = sub.add_parser("preview", help="预览本地 DB 当日可同步记录（不写飞书）")
    preview_p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")

    sync_p = sub.add_parser("sync", help="同步指定日期记录到飞书")
    sync_p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    sync_p.add_argument("--dry-run", action="store_true", help="只预览将写入的字段")
    sync_p.add_argument(
        "--minimal-fields",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="仅写标准 8 列（默认开启，适配已有表）",
    )

    sub.add_parser("sync-today", help="同步今天（等同 sync --date 今天）")

    args = parser.parse_args()

    if args.command == "check-config":
        return cmd_check_config()
    if args.command == "init-table":
        return cmd_init_table()
    if args.command == "preview":
        return cmd_preview(_parse_date(args.date))
    if args.command == "sync":
        return cmd_sync(
            _parse_date(args.date),
            dry_run=bool(args.dry_run),
            minimal_fields=bool(args.minimal_fields),
        )
    if args.command == "sync-today":
        return cmd_sync(date.today(), dry_run=False, minimal_fields=True)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
