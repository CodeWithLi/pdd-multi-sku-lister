"""
拼多多商品标题 AI 生成（智谱 GLM-5V-Turbo，支持主图视觉分析）

API Key 优先级：参数传入 > 环境变量 GLM_API_KEY > config.json 的 ai.api_key
"""
import base64
import json
import os
import re
from pathlib import Path

from openai import OpenAI

from pdd_auto.paths import CONFIG_PATH
from pdd_auto.products.assets import get_first_carousel_path, get_first_detail_path
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_MODEL = "glm-5v-turbo"
PDD_TITLE_MAX_CHARS = 60
PDD_MAX_HANZI = 30
AI_TITLE_MAX_RETRIES = 3


def load_ai_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f).get("ai", {})


def resolve_api_key(api_key: str | None = None) -> str:
    key = (
        api_key
        or os.environ.get("GLM_API_KEY")
        or os.environ.get("ZHIPU_API_KEY")
        or load_ai_config().get("api_key")
    )
    if not key:
        raise ValueError("未配置 GLM API Key，请在 config.json 的 ai.api_key 或环境变量 GLM_API_KEY 中设置")
    return key


def get_glm_client(api_key: str | None = None) -> OpenAI:
    ai_cfg = load_ai_config()
    base_url = ai_cfg.get("base_url") or GLM_BASE_URL
    return OpenAI(api_key=resolve_api_key(api_key), base_url=base_url)


def image_path_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def clean_title_text(raw: str) -> str:
    title = re.sub(r"[\r\n\t]+", "", (raw or "").strip())
    return re.sub(r"\s{2,}", " ", title)


def count_hanzi(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def title_length_issue(title: str) -> str | None:
    hanzi = count_hanzi(title)
    if hanzi > PDD_MAX_HANZI:
        return f"汉字 {hanzi} 个，超过上限 {PDD_MAX_HANZI} 个"
    if len(title) > PDD_TITLE_MAX_CHARS:
        return f"总长度 {len(title)}，超过上限 {PDD_TITLE_MAX_CHARS} 个字符"
    return None


def build_title_prompt(
    category_keyword: str,
    product_code: str = "",
    extra_hint: str = "",
    retry_feedback: str = "",
    has_cover_image: bool = False,
    has_detail_image: bool = False,
) -> str:
    parts = [
        "你是拼多多电商运营专家，请根据以下信息生成一个商品标题。",
    ]
    if has_cover_image or has_detail_image:
        img_hints = []
        idx = 1
        if has_cover_image:
            img_hints.append(f"第 {idx} 张为商品主图（cover），看整体外观与场景")
            idx += 1
        if has_detail_image:
            img_hints.append(
                f"第 {idx} 张为详情图（detail），以图中商品细节、规格、卖点为准，标题应与之吻合"
            )
        parts.append("请先分析用户上传的图片：" + "；".join(img_hints) + "，再撰写标题。")
    parts.extend([
        "要求：",
        "1. 结构参考：品牌感描述 + 核心卖点 + 规格/场景，自然流畅；",
        "2. 总长度不得超过 30 个汉字，且总字符数不得超过 60；",
        "3. 不要加引号、书名号、换行；只输出标题本身，不要解释。",
        f"类目关键词：{category_keyword or '（未提供）'}",
    ])
    if product_code:
        parts.append(f"商品编码：{product_code}")
    if extra_hint:
        parts.append(f"补充说明：{extra_hint}")
    if retry_feedback:
        parts.append(f"【上次不合格，请修正】{retry_feedback}")
    return "\n".join(parts)


def _build_user_message(
    category_keyword: str,
    product_code: str = "",
    extra_hint: str = "",
    retry_feedback: str = "",
    cover_image_path: str | None = None,
    detail_image_path: str | None = None,
):
    text = build_title_prompt(
        category_keyword,
        product_code,
        extra_hint,
        retry_feedback,
        has_cover_image=bool(cover_image_path),
        has_detail_image=bool(detail_image_path),
    )
    image_paths = [p for p in (cover_image_path, detail_image_path) if p]
    if not image_paths:
        return text

    content = [
        {
            "type": "image_url",
            "image_url": {"url": image_path_to_data_url(path)},
        }
        for path in image_paths
    ]
    content.append({"type": "text", "text": text})
    return content


def _call_glm_for_title(
    category_keyword: str,
    product_code: str = "",
    extra_hint: str = "",
    retry_feedback: str = "",
    cover_image_path: str | None = None,
    detail_image_path: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    client = get_glm_client(api_key)
    ai_cfg = load_ai_config()
    use_model = model or ai_cfg.get("model") or GLM_MODEL

    response = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": "你只输出拼多多商品标题文本，不要输出其他内容。"},
            {
                "role": "user",
                "content": _build_user_message(
                    category_keyword,
                    product_code,
                    extra_hint,
                    retry_feedback,
                    cover_image_path,
                    detail_image_path,
                ),
            },
        ],
        max_tokens=256,
        temperature=0.85,
        extra_body={"thinking": {"type": "disabled"}},
    )

    return (response.choices[0].message.content or "").strip()


def generate_pdd_product_title(
    category_keyword: str,
    product_code: str = "",
    extra_hint: str = "",
    product_path: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    log=print,
    account_id: str = "",
    max_retries: int = AI_TITLE_MAX_RETRIES,
    config: dict | None = None,
) -> str:
    """调用 GLM-5V-Turbo 生成标题；若有 product_path 则附带 1.jpg + 6.jpg 图分析。"""
    if not (category_keyword or "").strip():
        raise ValueError("请先填写类目关键词，再使用 AI 生成标题")

    prefix = f"[{account_id}] " if account_id else ""
    cover_path = get_first_carousel_path(product_path, config) if product_path else None
    detail_path = get_first_detail_path(product_path, config) if product_path else None
    if cover_path:
        log(f"{prefix}已加载轮播主图：{os.path.basename(cover_path)}")
    elif product_path:
        log(f"{prefix}[警告] 素材目录未找到 1.jpg 轮播主图")
    if detail_path:
        log(f"{prefix}已加载详情图：{os.path.basename(detail_path)}")
    elif product_path:
        log(f"{prefix}[警告] 素材目录未找到 6.jpg 详情图")
    if product_path and not cover_path and not detail_path:
        log(f"{prefix}[警告] 无可用图片，将仅按文字生成标题")

    ai_cfg = load_ai_config()
    use_model = model or ai_cfg.get("model") or GLM_MODEL
    last_error: Exception | None = None
    retry_feedback = ""

    for attempt in range(1, max_retries + 1):
        log(f"{prefix}AI 生成标题（{use_model}）第 {attempt}/{max_retries} 次...")
        try:
            raw = _call_glm_for_title(
                category_keyword=category_keyword,
                product_code=product_code,
                extra_hint=extra_hint,
                retry_feedback=retry_feedback,
                cover_image_path=cover_path,
                detail_image_path=detail_path,
                api_key=api_key,
                model=use_model,
            )
            title = clean_title_text(raw)
            if not title:
                raise RuntimeError("AI 未返回标题内容")

            issue = title_length_issue(title)
            if issue:
                raise ValueError(f"{issue}，标题：{title}")

            log(f"{prefix}[成功] AI 生成标题（第 {attempt} 次）：{title}")
            return title

        except Exception as e:
            last_error = e
            log(f"{prefix}[失败] 第 {attempt} 次生成失败：{e}")
            retry_feedback = str(e)
            if attempt >= max_retries:
                break

    raise RuntimeError(
        f"{prefix}AI 标题生成失败，已重试 {max_retries} 次，中断上架：{last_error}"
    )


def resolve_listing_title(
    product_info: dict,
    account_id: str = "",
    log=print,
    product_path: str | None = None,
    config: dict | None = None,
) -> str:
    mode = (product_info.get("title_mode") or "custom").strip().lower()
    prefix = f"[{account_id}] " if account_id else ""

    if mode in ("page_ai", "页面ai", "页面ai生成"):
        log(f"{prefix}标题模式：页面 AI 推荐（上架页上传图片后点击「立即使用」）")
        return ""

    if mode != "ai":
        title = (product_info.get("title") or "").strip()
        if not title:
            raise ValueError("自定义模式下请在控制台填写商品标题")
        log(f"{prefix}标题模式：自定义 → {title}")
        return title

    ai_cfg = load_ai_config()
    model_name = ai_cfg.get("model") or GLM_MODEL
    log(f"{prefix}标题模式：AI 生成（{model_name} + 1.jpg/6.jpg 图分析，最多重试 {AI_TITLE_MAX_RETRIES} 次）")
    return generate_pdd_product_title(
        category_keyword=product_info.get("category_keyword", ""),
        product_code=product_info.get("product_code", ""),
        product_path=product_path,
        api_key=ai_cfg.get("api_key"),
        model=model_name,
        log=log,
        account_id=account_id,
        max_retries=AI_TITLE_MAX_RETRIES,
        config=config,
    )


if __name__ == "__main__":
    import sys

    cat = sys.argv[1] if len(sys.argv) > 1 else "玩偶"
    ppath = sys.argv[2] if len(sys.argv) > 2 else "products/挂件/BCP001/default"
    print(generate_pdd_product_title(cat, product_path=ppath))
