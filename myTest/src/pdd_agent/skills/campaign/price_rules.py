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


def load_pdd_price_ranges(path: Path | None = None) -> dict[str, CampaignPriceRange]:
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
