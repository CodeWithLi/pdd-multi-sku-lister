"""Price range rules for PDD campaign product filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import xlrd

from pdd_agent.paths import PROJECT_ROOT


@dataclass(frozen=True)
class CampaignPriceRange:
    code: str
    min_price: float
    max_price: float


@dataclass(frozen=True)
class CodePriceEntry:
    raw_code: str
    norm_code: str
    label: str
    price: float


def _to_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def normalize_price_code(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    match = re.match(r"^[A-Z0-9+-]+", text)
    return match.group(0) if match else text


def price_rule_candidates(value: str) -> list[str]:
    text = str(value or "").strip().upper()
    candidates = [text, normalize_price_code(text)]
    if "+" in text:
        left, right = text.split("+", 1)
        candidates.extend([left.strip(), right.strip(), normalize_price_code(right)])
    return [item for item in dict.fromkeys(candidates) if item]


def load_pdd_price_ranges(path: Path | None = None, *, force_refresh: bool = False) -> dict[str, CampaignPriceRange]:
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import load_price_range_catalog

    catalog = load_price_range_catalog(force_refresh=force_refresh, excel_path=path)
    return catalog.ranges


def load_pdd_price_ranges_from_excel(path: Path | None = None) -> dict[str, CampaignPriceRange]:
    """仅从本地 pdd.xls 读取控价区间（迁移/回退用）。"""
    excel_path = path or (PROJECT_ROOT / "data" / "assets" / "pdd.xls")
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
    min_col = headers.index("下限价格") if "下限价格" in headers else 1
    max_col = headers.index("上限价格") if "上限价格" in headers else 2

    ranges: dict[str, CampaignPriceRange] = {}
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        code = normalize_price_code(raw_code)
        if not code:
            continue
        min_price = _to_float(sheet.cell_value(row_idx, min_col), 0.0)
        max_price = _to_float(sheet.cell_value(row_idx, max_col), 0.0)
        if max_price <= 0:
            continue
        rule = CampaignPriceRange(code=code, min_price=min_price, max_price=max_price)
        for key in price_rule_candidates(raw_code):
            ranges[key] = rule
    return ranges


def find_pdd_price_range(
    ranges: dict[str, CampaignPriceRange],
    candidates: list[str],
) -> CampaignPriceRange | None:
    for value in candidates:
        for key in price_rule_candidates(value):
            rule = ranges.get(key)
            if rule:
                return rule
    return None


def _load_code_price_map(
    excel_path: Path,
    *,
    price_header: str,
) -> dict[str, float]:
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
    price_col = headers.index(price_header) if price_header in headers else 1

    prices: dict[str, float] = {}
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        code = normalize_price_code(raw_code)
        if not code:
            continue
        price = _to_float(sheet.cell_value(row_idx, price_col), 0.0)
        if price <= 0:
            continue
        for key in price_rule_candidates(raw_code):
            prices[key] = price
    return prices


def load_pdd_pricing(path: Path | None = None, *, force_refresh: bool = False) -> dict[str, float]:
    """母商品定价表：商品编码 -> 拼多多定价。"""
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import load_pricing_catalog

    catalog = load_pricing_catalog(force_refresh=force_refresh, excel_path=path)
    return catalog.prices


def load_pdd_control_prices(path: Path | None = None, *, force_refresh: bool = False) -> dict[str, float]:
    """子商品控价表：商品编码 -> PDD控价。"""
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import load_control_catalog

    catalog = load_control_catalog(force_refresh=force_refresh, excel_path=path)
    return catalog.prices


def find_code_price(prices: dict[str, float], code: str) -> float | None:
    for key in price_rule_candidates(code):
        value = prices.get(key)
        if value is not None and value > 0:
            return value
    return None


def _label_from_raw_code(raw_code: str) -> str:
    norm = normalize_price_code(raw_code)
    upper = str(raw_code or "").strip().upper()
    if norm and upper.startswith(norm):
        return str(raw_code)[len(norm) :].strip()
    return str(raw_code or "").strip()


def _load_code_price_entries(
    excel_path: Path,
    *,
    price_header: str,
) -> list[CodePriceEntry]:
    if not excel_path.is_file():
        return []
    book = xlrd.open_workbook(str(excel_path))
    if book.nsheets <= 0:
        return []
    sheet = book.sheet_by_index(0)
    if sheet.nrows <= 1:
        return []

    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    code_col = headers.index("商品编码") if "商品编码" in headers else 0
    price_col = headers.index(price_header) if price_header in headers else 1

    entries: list[CodePriceEntry] = []
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        norm_code = normalize_price_code(raw_code)
        if not norm_code:
            continue
        price = _to_float(sheet.cell_value(row_idx, price_col), 0.0)
        entries.append(
            CodePriceEntry(
                raw_code=raw_code,
                norm_code=norm_code,
                label=_label_from_raw_code(raw_code),
                price=price,
            )
        )
    return entries


def load_pdd_control_entries(path: Path | None = None, *, force_refresh: bool = False) -> list[CodePriceEntry]:
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import load_control_catalog

    catalog = load_control_catalog(force_refresh=force_refresh, excel_path=path)
    if catalog.entries:
        return catalog.entries
    excel_path = path or (PROJECT_ROOT / "data" / "assets" / "拼多多控价.xls")
    return _load_code_price_entries(excel_path, price_header="PDD控价")


def load_pdd_pricing_entries(path: Path | None = None, *, force_refresh: bool = False) -> list[CodePriceEntry]:
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import load_pricing_catalog

    catalog = load_pricing_catalog(force_refresh=force_refresh, excel_path=path)
    if catalog.entries:
        return catalog.entries
    excel_path = path or (PROJECT_ROOT / "data" / "assets" / "拼多多定价.xls")
    return _load_code_price_entries(excel_path, price_header="拼多多定价")


def find_code_by_label(entries: list[CodePriceEntry], text: str) -> str:
    """按名称片段在 Excel 商品编码列反查编码（如「灰鲨鱼头套」→ YKLxxx）。"""
    query = str(text or "").strip()
    if not query:
        return ""

    best_code = ""
    best_score = 0
    for entry in entries:
        if entry.price <= 0:
            continue
        for label in (entry.label, entry.raw_code):
            if not label:
                continue
            if query == label:
                return entry.norm_code
            if label in query or query in label:
                score = min(len(label), len(query))
                if score > best_score:
                    best_score = score
                    best_code = entry.norm_code
    return best_code
