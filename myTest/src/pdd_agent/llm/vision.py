"""视觉/文本模型：款式颜色与子类尺寸识别。"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from pdd_agent.core.logging import get_logger
from pdd_agent.llm.factory import create_chat_model, create_vision_model
from pdd_agent.skills.listing.pdd_product_catalog import (
    PddProductEntry,
    fallback_sub_category_from_spec,
    infer_sub_product_category_rules,
    is_weak_sub_category,
)

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


def _normalize_sub_category_text(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"[。．.!！?？,，、\s]+", "", raw)
    raw = raw.strip("「」\"'")
    if not raw:
        return ""
    if len(raw) > 8:
        raw = raw[:6]
    return raw


def _llm_api_available() -> bool:
    from pdd_agent.core.config import get_env_settings

    return bool(get_env_settings().llm_api_key)


def _ai_infer_sub_category_from_text(entry: PddProductEntry) -> str:
    if not _llm_api_available():
        return ""
    try:
        model = create_chat_model(temperature=0)
        prompt = (
            "你是电商商品分类助手。根据商品信息判断「配件子类型」，用于把同款不同配件分到同一尺寸组。\n"
            f"商品编码：{entry.code}\n"
            f"商品类型：{entry.product_type}\n"
            f"颜色规格：{entry.color_spec}\n"
            "只回答一个简短中文类别名（2-6字），例如：挂件、尺子、套尺、磁吸夹、冰箱贴、PP夹、发夹、镜子、打卡棒、贴纸。\n"
            "不要解释，不要标点。"
        )
        resp = model.invoke([HumanMessage(content=prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _normalize_sub_category_text(content)
    except Exception as exc:
        logger.warning("text sub-category detect failed code=%s err=%s", entry.code, exc)
        return ""


def _ai_infer_sub_category_from_image(entry: PddProductEntry, image_path: Path) -> str:
    if not _llm_api_available() or not image_path.is_file():
        return ""
    try:
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        media = _image_media_type(image_path)
        model = create_vision_model()
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "这是电商配件/组合商品图。请判断图中「附加配件」的类型，用于规格尺寸分组。\n"
                        f"商品类型：{entry.product_type}\n"
                        f"颜色规格：{entry.color_spec}\n"
                        "只回答一个简短中文类别名（2-6字），如：挂件、尺子、套尺、磁吸夹、冰箱贴、PP夹、发夹、镜子。\n"
                        "不要解释。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}},
            ]
        )
        resp = model.invoke([message])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _normalize_sub_category_text(content)
    except Exception as exc:
        logger.warning("vision sub-category detect failed code=%s err=%s", entry.code, exc)
        return ""


def detect_sub_product_category(
    entry: PddProductEntry,
    *,
    image_path: Path | None = None,
) -> str:
    """推断配件子类：规则 → 文本 AI → 视觉 AI → 颜色规格截取。"""
    ruled = infer_sub_product_category_rules(entry)
    if ruled and not is_weak_sub_category(ruled):
        return ruled

    text_cat = _ai_infer_sub_category_from_text(entry)
    if text_cat and not is_weak_sub_category(text_cat):
        return text_cat

    if image_path:
        image_cat = _ai_infer_sub_category_from_image(entry, image_path)
        if image_cat and not is_weak_sub_category(image_cat):
            return image_cat

    if ruled:
        return ruled
    return fallback_sub_category_from_spec(entry)
