"""投流推广列表右侧指标列（与拼多多表头一致）。"""

from __future__ import annotations

import re

# 与拼多多「自定义数据项」已选 38 项一致（不含页面未展示的「结算成交花费(元)」）
DEFAULT_TRAFFIC_METRIC_COLUMNS: list[str] = [
    "成交花费(元)",
    "交易额(元)",
    "实际投产比",
    "总花费(元)",
    "净交易额(元)",
    "净实际投产比",
    "净成交笔数",
    "每笔净成交花费(元)",
    "净交易额占比",
    "净成交笔数占比",
    "每笔净成交金额(元)",
    "结算交易额(元)",
    "结算投产比",
    "结算成交笔数",
    "退款豁免率",
    "退单豁免率",
    "每笔结算成交花费(元)",
    "交易额结算率",
    "订单结算率",
    "每笔结算成交金额(元)",
    "成交笔数",
    "每笔成交花费(元)",
    "每笔成交金额(元)",
    "直接交易额(元)",
    "间接交易额(元)",
    "直接成交笔数",
    "间接成交笔数",
    "曝光量",
    "点击量",
    "询单花费(元)",
    "询单量",
    "平均询单成本(元)",
    "收藏花费(元)",
    "收藏量",
    "平均收藏成本(元)",
    "关注花费(元)",
    "关注量",
    "平均关注成本(元)",
]

# 历史/别名兼容，不在默认 38 列中
LEGACY_TRAFFIC_METRIC_COLUMNS: frozenset[str] = frozenset({"结算成交花费(元)"})

KNOWN_METRIC_COLUMN_SET: frozenset[str] = frozenset(
    DEFAULT_TRAFFIC_METRIC_COLUMNS
) | LEGACY_TRAFFIC_METRIC_COLUMNS

# 页面表头与飞书标准列名的别名（写入时归一化到标准列名）
TRAFFIC_HEADER_ALIASES: dict[str, str] = {
    "成交金额(元)": "成交花费(元)",
    "结算[元]": "结算成交花费(元)",
    "结算（元）": "结算成交花费(元)",
}

_JUNK_VALUE_MARKERS: tuple[str, ...] = (
    "详情",
    "数据",
    "更多",
    "手动暂停",
    "去开启",
    "预算日限额",
    "净目标投产比",
    "拼单价",
    "促进净成交",
    "极速起量",
    "商品 ID",
    "商品ID",
    "商品 id",
)

_NUMERIC_VALUE_RE = re.compile(r"^-?\d+(?:\.\d+)?%?$")


def normalize_traffic_header(header: str) -> str:
    text = str(header or "").strip()
    if not text:
        return ""
    return TRAFFIC_HEADER_ALIASES.get(text, text)


def is_known_metric_header(header: str) -> bool:
    return normalize_traffic_header(header) in KNOWN_METRIC_COLUMN_SET


def is_metric_cell_value(value: str) -> bool:
    """指标单元格合法值：数字/百分比（含 0、0.00），排除操作列与商品描述文本。"""
    text = str(value if value is not None else "").strip()
    if not text or text == "-":
        return False
    if not _NUMERIC_VALUE_RE.fullmatch(text):
        return False
    for marker in _JUNK_VALUE_MARKERS:
        if marker in text:
            return False
    return True


def normalize_traffic_metrics(metrics: dict[str, str]) -> dict[str, str]:
    """将抓取表头归一化到已知指标列，丢弃非指标列与脏数据。"""
    normalized: dict[str, str] = {}
    for key, value in metrics.items():
        column = normalize_traffic_header(str(key or ""))
        if column not in KNOWN_METRIC_COLUMN_SET:
            continue
        text = str(value if value is not None else "").strip()
        if not is_metric_cell_value(text):
            continue
        normalized[column] = text
    return normalized


def collect_metric_columns(
    *,
    configured: list[str] | None = None,
    scraped_headers: list[str] | None = None,
) -> list[str]:
    """合并配置列与本次抓取到的表头，去重并保持顺序。"""
    ordered: list[str] = []
    seen: set[str] = set()
    for source in (configured or DEFAULT_TRAFFIC_METRIC_COLUMNS, scraped_headers or []):
        for item in source:
            column = normalize_traffic_header(str(item or ""))
            if not column or column in seen:
                continue
            if column not in KNOWN_METRIC_COLUMN_SET:
                continue
            seen.add(column)
            ordered.append(column)
    return ordered
