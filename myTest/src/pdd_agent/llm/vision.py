"""视觉模型：从商品图识别颜色（款式规格）。"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from pdd_agent.core.logging import get_logger
from pdd_agent.llm.factory import create_vision_model
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry

logger = get_logger(__name__)

_COLOR_HINTS = (
    "白",
    "黑",
    "红",
    "蓝",
    "绿",
    "黄",
    "紫",
    "粉",
    "灰",
    "棕",
    "橙",
    "米",
    "卡其",
    "藏青",
    "咖",
)


def _image_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return "image/png"


def _normalize_color_text(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"[。．.!！?？\s]+", "", raw)
    for hint in _COLOR_HINTS:
        if hint in raw:
            if hint in {"白", "黑", "红", "蓝", "绿", "黄", "紫", "粉", "灰", "棕", "橙", "米"}:
                return f"{hint}色"
            return hint
    return raw[:12] if raw else ""


def _fallback_color_from_catalog(entry: PddProductEntry | None) -> str:
    if not entry:
        return ""
    spec = entry.color_spec
    for hint in _COLOR_HINTS:
        if hint in spec:
            return _normalize_color_text(hint)
    return ""


def detect_product_color(image_path: Path, *, catalog_entry: PddProductEntry | None = None) -> str:
    """识别商品主色；失败时回退到拼多多商品表颜色规格。"""
    fallback = _fallback_color_from_catalog(catalog_entry)
    if not image_path.is_file():
        return fallback or (catalog_entry.code if catalog_entry else "")

    from pdd_agent.core.config import get_env_settings

    env_key_set = bool(get_env_settings().llm_api_key)
    if not env_key_set:
        return fallback or _normalize_color_text(catalog_entry.color_spec if catalog_entry else "")

    try:
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        media = _image_media_type(image_path)
        model = create_vision_model()
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "这是电商商品图。请判断商品主体最主要的颜色，"
                        "只回答一个中文颜色词（如：白色、黑色、蓝色、紫色、粉色）。不要解释。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}},
            ]
        )
        resp = model.invoke([message])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        color = _normalize_color_text(content)
        if color:
            return color
    except Exception as exc:
        logger.warning("vision color detect failed path=%s err=%s", image_path, exc)

    return fallback or (catalog_entry.code if catalog_entry else "")
