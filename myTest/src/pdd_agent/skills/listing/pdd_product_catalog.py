"""拼多多所有商品.xls — 商品编码 / 颜色规格 / 商品类型。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import xlrd

def default_catalog_path() -> Path:
    import pdd_agent.paths as paths

    return paths.PROJECT_ROOT / "data" / "assets" / "拼多多所有商品.xls"


@dataclass(frozen=True)
class PddProductEntry:
    code: str
    color_spec: str
    product_type: str


def _norm_code(value: str) -> str:
    return str(value or "").strip().upper()


def load_pdd_product_catalog(path: Path | None = None) -> dict[str, PddProductEntry]:
    excel_path = path or default_catalog_path()
    if not excel_path.is_file():
        return {}

    book = xlrd.open_workbook(str(excel_path))
    if book.nsheets <= 0:
        return {}
    sheet = book.sheet_by_index(0)
    if sheet.nrows <= 1:
        return {}

    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    code_col = headers.index("商品编码") if "商品编码" in headers else 0
    color_col = headers.index("颜色规格") if "颜色规格" in headers else 1
    type_col = headers.index("商品类型") if "商品类型" in headers else 2

    catalog: dict[str, PddProductEntry] = {}
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        code = _norm_code(raw_code)
        if not code:
            continue
        catalog[code] = PddProductEntry(
            code=code,
            color_spec=str(sheet.cell_value(row_idx, color_col)).strip(),
            product_type=str(sheet.cell_value(row_idx, type_col)).strip(),
        )
    return catalog


@lru_cache
def get_pdd_product_catalog() -> dict[str, PddProductEntry]:
    return load_pdd_product_catalog()


def catalog_has_code(code: str) -> bool:
    return _norm_code(code) in get_pdd_product_catalog()


def get_catalog_entry(code: str) -> PddProductEntry | None:
    return get_pdd_product_catalog().get(_norm_code(code))


def infer_sub_product_category(entry: PddProductEntry) -> str:
    """子商品归类名：挂件 / 尺子 / 或回退到商品类型。"""
    spec = entry.color_spec
    if "挂件" in spec:
        return "挂件"
    if "尺子" in spec or "摇摇乐" in spec:
        return "尺子"
    if entry.product_type in {"挂件", "尺子", "亚克力"}:
        if entry.product_type == "亚克力":
            if "挂件" in spec:
                return "挂件"
            if "尺子" in spec or "摇摇乐" in spec:
                return "尺子"
        return entry.product_type
    return entry.product_type or "配件"


def resolve_size_label(style_code: str, model_code: str, catalog: dict[str, PddProductEntry]) -> str:
    """第二个规格（尺寸）展示名：笔袋 / 笔袋+挂件 / 笔袋+尺子 …"""
    base = catalog.get(_norm_code(style_code))
    if not base:
        return model_code

    model_norm = _norm_code(model_code)
    style_norm = _norm_code(style_code)
    if not model_norm or model_norm == style_norm:
        return base.product_type or style_code

    sub = catalog.get(model_norm)
    if not sub:
        return model_code

    sub_cat = infer_sub_product_category(sub)
    base_type = base.product_type or style_code
    return f"{base_type}+{sub_cat}"
