"""Port PDD Feishu integration files into dy_agent (one-time migration helper)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDD_SRC = ROOT.parent / "myTest" / "src" / "pdd_agent"
DY_SRC = ROOT / "src" / "dy_agent"

FILES = [
    "integrations/feishu/__init__.py",
    "integrations/feishu/config.py",
    "integrations/feishu/client.py",
    "integrations/feishu/bitable.py",
    "integrations/feishu/cache.py",
    "integrations/feishu/field_display.py",
    "integrations/feishu/schemas.py",
    "integrations/feishu/traffic_metric_columns.py",
    "integrations/feishu/listing_feishu_catalog.py",
    "integrations/feishu/listing_feishu_snapshot.py",
    "integrations/feishu/pdd_product_catalog_sync.py",
    "integrations/feishu/pdd_price_compare_sync.py",
    "integrations/feishu/jushuitan_erp_inventory.py",
    "skills/listing/pdd_product_catalog.py",
    "skills/listing/listing_accessory_cost_pricing.py",
    "skills/listing/listing_accessory_cost_float_registry.py",
    "skills/campaign/price_rules.py",
    "domain/listing_errors.py",
    "api/routes/feishu_oauth.py",
    "api/schemas/feishu_cache.py",
]

REPLACEMENTS = [
    ("pdd_agent", "dy_agent"),
    ("http://127.0.0.1:8010/api/feishu/oauth/callback", "http://127.0.0.1:8020/api/feishu/oauth/callback"),
    ("http://localhost:5173/", "http://localhost:5175/"),
    ("拼多多上架助手", "抖店上架助手"),
    (
        "from dy_agent.integrations.feishu.pdd_upload_sync import _resolve_or_create_pdd_table_id",
        "from dy_agent.integrations.feishu.table_resolve import resolve_feishu_table_id as _resolve_or_create_pdd_table_id",
    ),
]


def transform(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    copied = 0
    for rel in FILES:
        src = PDD_SRC / rel.replace("/", "\\") if False else PDD_SRC / Path(rel)
        dst = DY_SRC / Path(rel)
        if not src.is_file():
            print(f"SKIP missing: {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = transform(src.read_text(encoding="utf-8"))
        dst.write_text(content, encoding="utf-8")
        copied += 1
        print(f"OK {rel}")
    print(f"Copied {copied} files")


if __name__ == "__main__":
    main()
