"""规格与库存抓取：列映射逻辑（与页面 JS 对齐的 Python 参考实现，用于单测）。"""

from __future__ import annotations


def map_header(text: str) -> str:
    t = " ".join(str(text or "").split()).strip()
    if not t:
        return "skip"
    if "预览图" in t or t == "预览":
        return "skip"
    if "上下架" in t or t == "库存" or t == "活动价":
        return "skip"
    if "款式" in t:
        return "style"
    if "套餐" in t:
        return "package"
    if "尺寸" in t or "型号" in t:
        return "package"
    if "拼单价" in t:
        return "group_price"
    if "单买价" in t:
        return "single_price"
    if "规格编码" in t or "商家编码" in t:
        return "spec_code"
    return "skip"


def parse_row_by_columns(
    cells: list[str],
    current_style: str,
    headers: list[str],
) -> dict[str, str]:
    col_types = [map_header(h) for h in headers]
    item = {
        "style_name": "",
        "package_name": "",
        "group_price": "",
        "single_price": "",
        "spec_code": "",
    }
    if not col_types:
        return item

    cell_idx = 0
    col_idx = 0
    missing_style = col_types[0] == "style" and len(cells) < len(col_types)
    if missing_style:
        item["style_name"] = current_style
        col_idx = 1

    while col_idx < len(col_types) and cell_idx < len(cells):
        field = col_types[col_idx]
        value = cells[cell_idx]
        if field == "style":
            item["style_name"] = value or current_style
        elif field == "package" and value not in ("预览", "") and "已上架" not in value:
            item["package_name"] = value
        elif field == "group_price" and value:
            item["group_price"] = value
        elif field == "single_price" and value:
            item["single_price"] = value
        elif field == "spec_code" and value:
            item["spec_code"] = value
        col_idx += 1
        cell_idx += 1

    if not item["style_name"]:
        item["style_name"] = current_style
    return item


HEADERS = [
    "款式",
    "套餐",
    "库存",
    "活动价",
    "拼单价(元)",
    "单买价(元)",
    "规格编码",
    "规格预览图",
    "上下架状态",
]


def test_parse_row_with_rowspan_style_group():
  """首行 9 列：款式+套餐；续行 8 列：无款式（rowspan）。"""
  first = parse_row_by_columns(
      [
          "蓝色慕斯星星笔袋",
          "单件装：包包【爆款热销】",
          "298",
          "12.80",
          "13.80",
          "50.00",
          "BD630D",
          "预览",
          "已上架",
      ],
      "",
      HEADERS,
  )
  assert first["style_name"] == "蓝色慕斯星星笔袋"
  assert first["package_name"] == "单件装：包包【爆款热销】"
  assert first["spec_code"] == "BD630D"
  assert first["package_name"] != "预览"

  second = parse_row_by_columns(
      [
          "两件套：包包+挂件",
          "300",
          "13.80",
          "14.80",
          "50.00",
          "BD630D+YKL001A",
          "预览",
          "已上架",
      ],
      first["style_name"],
      HEADERS,
  )
  assert second["style_name"] == "蓝色慕斯星星笔袋"
  assert second["package_name"] == "两件套：包包+挂件"
  assert second["spec_code"] == "BD630D+YKL001A"
