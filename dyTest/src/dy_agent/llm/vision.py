"""视觉/文本模型：款式颜色与子类尺寸识别。"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from dy_agent.core.logging import get_logger
from dy_agent.llm.factory import create_chat_model, create_vision_model
from dy_agent.skills.listing.pdd_product_catalog import (
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

    from dy_agent.core.config import get_env_settings

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
                        "这是电商商品规格图。请判断商品主体（笔袋/公仔/拖鞋等本体）的主色，"
                        "忽略白色背景、小面积印花和挂件配件的颜色。"
                        "浅灰色应回答「灰色」，不要回答白色。"
                        "只回答一个中文颜色词（如：白色、黑色、灰色、绿色、蓝色）。不要解释。"
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
    from dy_agent.core.config import get_env_settings

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


def _normalize_size_display_label(text: str, max_len: int = 24) -> str:
    raw = re.sub(r"[。．.!！?？\s]+", "", str(text or "").strip())
    raw = raw.strip("「」\"'")
    if not raw:
        return ""
    if len(raw) > max_len:
        return raw[:max_len]
    return raw


def disambiguate_conflicting_size_labels_ai(
    style_code: str,
    skus: list,
    catalog: dict,
) -> dict[str, str]:
    """
    同款式下尺寸名仍冲突时，结合规格图 + 商品表为每个子编码生成唯一尺寸名。
    返回 model_code.upper() -> 完整尺寸展示名。
    """
    from dy_agent.skills.listing.pdd_product_catalog import get_catalog_entry

    if not skus or not _llm_api_available():
        return {}
    lines: list[str] = [
        "你是电商拼多多规格命名助手。",
        f"款式编码（固定，不可改）：{style_code}",
        "以下子商品同属该款式，当前尺寸展示名冲突，请为每个子商品编码生成唯一尺寸名。",
        "格式：{基础尺寸名}({商品类型}-{2~4字区分词})，例如 笔袋+挂件(公仔-鲨鱼)、笔袋+挂件(公仔-KT)。",
        "区分词从颜色规格或图片主体提取；商品类型用商品表字段。",
        "每个编码的尺寸名必须互不相同；编码必须与本款式严格对应，不得混淆到其他款式。",
        "只返回 JSON 对象，键为子商品编码，值为完整尺寸名。不要 markdown、不要解释。",
        "",
        "商品列表：",
    ]
    content: list = []
    for idx, sku in enumerate(skus, start=1):
        model_code = sku.model_code.strip().upper()
        entry = catalog.get(model_code) or get_catalog_entry(model_code)
        base_label = sku.model_name or ""
        ptype = entry.product_type if entry else ""
        color_spec = entry.color_spec if entry else ""
        lines.append(
            f"{idx}. 子商品编码={model_code}；当前尺寸名={base_label}；"
            f"商品类型={ptype}；颜色规格={color_spec}；组合文件夹={sku.combo_folder}"
        )
        image = sku.preview_image if sku.preview_image and sku.preview_image.is_file() else None
        if image:
            lines.append(f"   （下图对应子商品编码 {model_code}）")
            try:
                data = base64.b64encode(image.read_bytes()).decode("ascii")
                media = _image_media_type(image)
                content.append({"type": "text", "text": f"子商品编码 {model_code} 规格图："})
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{data}"},
                    }
                )
            except Exception as exc:
                logger.warning("size label image load failed code=%s err=%s", model_code, exc)

    content.insert(0, {"type": "text", "text": "\n".join(lines)})

    try:
        model = create_vision_model()
        resp = model.invoke([HumanMessage(content=content)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        parsed = _parse_size_label_json(raw, expected_codes=[s.model_code for s in skus])
        out: dict[str, str] = {}
        for sku in skus:
            code = sku.model_code.strip().upper()
            label = parsed.get(code) or parsed.get(sku.model_code.strip())
            if label:
                out[code] = _normalize_size_display_label(label)
        return out
    except Exception as exc:
        logger.warning("size label AI disambiguate failed style=%s err=%s", style_code, exc)
        return {}


def _parse_size_label_json(raw: str, expected_codes: list[str]) -> dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {}
    # 去掉 markdown 代码块
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
    try:
        import json

        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k).strip().upper(): str(v).strip() for k, v in data.items()}
    except Exception:
        pass
    out: dict[str, str] = {}
    for code in expected_codes:
        norm = code.strip().upper()
        m = re.search(
            rf'["\']?{re.escape(norm)}["\']?\s*[:：]\s*["\']?([^"\']+)["\']?',
            text,
            re.IGNORECASE,
        )
        if m:
            out[norm] = m.group(1).strip()
    return out
