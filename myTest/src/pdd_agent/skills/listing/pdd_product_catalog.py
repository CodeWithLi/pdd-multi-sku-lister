"""拼多多所有商品.xls — 商品编码 / 颜色规格 / 商品类型。"""

from __future__ import annotations

import re
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
    inventory: int = 0
    price: float = 0.0


# 规则无法给出有意义分组时的「弱类型」（如亚克力配件需再推断子类）
WEAK_SUB_CATEGORIES = frozenset({"", "亚克力", "半成品", "配件"})

# 预览图文件名含 3 段及以上「+」时，型号统一解析为此编码（展示名为 {母商品类型}+套装）
BUNDLE_MODEL_CODE = "套装"

# 颜色规格关键词 → 尺寸子类（按优先级，先匹配先生效）
_SUB_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("挂件", "挂件"),
    ("套尺", "套尺"),
    ("磁吸夹", "磁吸夹"),
    ("冰箱贴", "冰箱贴"),
    ("PP夹", "PP夹"),
    ("发夹", "发夹"),
    ("钥匙扣", "钥匙扣"),
    ("打卡棒", "打卡棒"),
    ("书签", "书签"),
    ("便签本", "便签"),
    ("便签", "便签"),
    ("徽章", "徽章"),
    ("摇摇乐", "尺子"),
    ("直尺", "尺子"),
    ("尺子", "尺子"),
    ("卡套", "卡套"),
    ("贴纸", "贴纸"),
    ("镜子", "镜子"),
    ("镜", "镜子"),
)


def _norm_code(value: str) -> str:
    return str(value or "").strip().upper()


def _parse_cell_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _parse_cell_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _format_price(value: float) -> str:
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _load_xls_sheet(excel_path: Path):
    book = xlrd.open_workbook(str(excel_path))
    if book.nsheets <= 0:
        return None, []
    sheet = book.sheet_by_index(0)
    if sheet.nrows <= 1:
        return None, []
    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    rows: list[tuple] = []
    for row_idx in range(1, sheet.nrows):
        rows.append(tuple(sheet.cell_value(row_idx, col) for col in range(sheet.ncols)))
    return headers, rows


def _load_xlsx_sheet(excel_path: Path):
    from openpyxl import load_workbook

    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    iter_rows = ws.iter_rows(values_only=True)
    header_row = next(iter_rows, None)
    if not header_row:
        wb.close()
        return None, []
    headers = [str(cell or "").strip() for cell in header_row]
    rows = [row for row in iter_rows if row and row[0]]
    wb.close()
    return headers, rows


def _load_sheet_rows(excel_path: Path) -> tuple[list[str], list[tuple]] | tuple[None, list]:
    suffix = excel_path.suffix.lower()
    if suffix == ".xls":
        return _load_xls_sheet(excel_path)
    if suffix == ".xlsx":
        return _load_xlsx_sheet(excel_path)
    return None, []


def load_pdd_product_catalog(path: Path | None = None) -> dict[str, PddProductEntry]:
    excel_path = path or default_catalog_path()
    if not excel_path.is_file():
        return {}

    try:
        headers, rows = _load_sheet_rows(excel_path)
    except Exception:
        return {}
    if not headers:
        return {}

    code_col = headers.index("商品编码") if "商品编码" in headers else 0
    color_col = headers.index("颜色规格") if "颜色规格" in headers else 1
    type_col = headers.index("商品类型") if "商品类型" in headers else 2
    inv_col = headers.index("库存") if "库存" in headers else None
    price_col = headers.index("价格") if "价格" in headers else None

    catalog: dict[str, PddProductEntry] = {}
    for row in rows:
        if not row or code_col >= len(row):
            continue
        raw_code = str(row[code_col] or "").strip()
        code = _norm_code(raw_code)
        if not code:
            continue
        color_spec = str(row[color_col] or "").strip() if color_col < len(row) else ""
        if not color_spec:
            continue
        catalog[code] = PddProductEntry(
            code=code,
            color_spec=color_spec,
            product_type=str(row[type_col] or "").strip() if type_col < len(row) else "",
            inventory=_parse_cell_int(row[inv_col], 0) if inv_col is not None and inv_col < len(row) else 0,
            price=_parse_cell_float(row[price_col], 0.0) if price_col is not None and price_col < len(row) else 0.0,
        )
    return catalog


@lru_cache
def get_pdd_product_catalog() -> dict[str, PddProductEntry]:
    return load_pdd_product_catalog()


def catalog_has_code(code: str) -> bool:
    return _norm_code(code) in get_pdd_product_catalog()


def get_catalog_entry(code: str) -> PddProductEntry | None:
    return get_pdd_product_catalog().get(_norm_code(code))


def lookup_catalog_spec(code: str, catalog: dict[str, PddProductEntry] | None = None) -> str | None:
    """颜色规格（等同原 sku+名称.xlsx 中的名称列）。"""
    entry = (catalog or get_pdd_product_catalog()).get(_norm_code(code))
    return entry.color_spec if entry else None


def resolve_combo_pricing(
    style_code: str,
    model_code: str,
    catalog: dict[str, PddProductEntry],
    defaults: dict[str, str],
) -> tuple[str, str, str]:
    """组合 SKU 库存/拼单价/单买价（数据来自商品表）。"""
    fallback_inv = defaults.get("inventory", "10")
    fallback_gp = defaults.get("group_price", "199.9")
    fallback_sp = defaults.get("single_price", "299.9")

    style = catalog.get(_norm_code(style_code))
    model_norm = _norm_code(model_code)
    style_norm = _norm_code(style_code)
    if model_norm == style_norm:
        if not style:
            return fallback_inv, fallback_gp, fallback_sp
        group_price = style.price
        return str(style.inventory or fallback_inv), _format_price(group_price), _format_price(group_price + 100)

    model = catalog.get(model_norm)
    if not style or not model:
        return fallback_inv, fallback_gp, fallback_sp

    inventory = min(style.inventory, model.inventory)
    group_price = style.price + model.price
    single_price = group_price + 100
    return str(inventory), _format_price(group_price), _format_price(single_price)


def is_weak_sub_category(category: str) -> bool:
    cat = str(category or "").strip()
    if not cat or cat in WEAK_SUB_CATEGORIES:
        return True
    return len(cat) > 8


def infer_sub_product_category_rules(entry: PddProductEntry) -> str | None:
    """仅用规则从商品表推断子类；无法推断时返回 None。"""
    spec = entry.color_spec
    for keyword, category in _SUB_CATEGORY_KEYWORDS:
        if keyword in spec:
            return category
    product_type = entry.product_type.strip()
    if product_type and product_type not in WEAK_SUB_CATEGORIES:
        return product_type
    return None


def fallback_sub_category_from_spec(entry: PddProductEntry) -> str:
    """无 AI 时的最后兜底：从颜色规格截取可读短名。"""
    spec = entry.color_spec.strip()
    for prefix in ("亚克力定制款", "亚克力定制", "定制款", "亚克力"):
        if spec.startswith(prefix):
            spec = spec[len(prefix) :].strip()
    spec = re.sub(r"[()（）【】].*", "", spec).strip("款 ")
    if spec:
        return spec[:6]
    return entry.code


def infer_sub_product_category(entry: PddProductEntry) -> str:
    """子商品归类名（仅规则，不含 AI）。"""
    ruled = infer_sub_product_category_rules(entry)
    if ruled:
        return ruled
    return fallback_sub_category_from_spec(entry)


def append_product_type_to_size_label(base_label: str, product_type: str) -> str:
    """在尺寸名后附加商品类型，如 笔袋+挂件 → 笔袋+挂件(公仔)。"""
    label = (base_label or "").strip()
    ptype = (product_type or "").strip()
    if not label or not ptype:
        return label
    if f"({ptype})" in label or label.endswith(f"({ptype})"):
        return label
    return f"{label}({ptype})"


def meaningful_product_type_for_label(entry: PddProductEntry | None) -> str:
    """可用于尺寸名后缀的商品类型（排除亚克力等弱类型）。"""
    if not entry:
        return ""
    ptype = entry.product_type.strip()
    if not ptype or ptype in WEAK_SUB_CATEGORIES:
        return ""
    return ptype


def resolve_size_label(
    style_code: str,
    model_code: str,
    catalog: dict[str, PddProductEntry],
    *,
    sub_category_cache: dict[str, str] | None = None,
) -> str:
    """第二个规格（尺寸）展示名：{母商品类型} / {母商品类型}+{子类} …"""
    base = catalog.get(_norm_code(style_code))
    if not base:
        return model_code

    model_norm = _norm_code(model_code)
    style_norm = _norm_code(style_code)
    base_type = base.product_type.strip() or style_code
    if not model_norm or model_norm == style_norm:
        return base_type
    if model_norm == BUNDLE_MODEL_CODE:
        return f"{base_type}+{BUNDLE_MODEL_CODE}"

    sub = catalog.get(model_norm)
    if not sub:
        return model_code

    cache = sub_category_cache or {}
    sub_cat = cache.get(model_norm)
    if not sub_cat:
        sub_cat = infer_sub_product_category(sub)
    return f"{base_type}+{sub_cat}"
