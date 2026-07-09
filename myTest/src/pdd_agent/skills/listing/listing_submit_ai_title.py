"""提交前 AI 改标题（独立于历史 page_ai 流程）。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from pdd_agent.api.services.submit_ai_title_config_service import (
    SubmitAiTitleConfig,
    get_submit_ai_title_config,
)
from pdd_agent.llm.factory import create_chat_model_with_runtime
from pdd_agent.skills.listing.page_ai_title import _fill_manual_title, _read_title_from_input


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def _image_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return "image/png"


def _collect_valid_image_paths(image_paths: list[str], max_count: int) -> list[Path]:
    out: list[Path] = []
    for raw in image_paths:
        p = Path(str(raw or "").strip())
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        out.append(p)
        if len(out) >= max_count:
            break
    return out


def _normalize_title_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ").strip()
    for token in ("标题：", "标题:", "title:", "Title:", "答案：", "答案:"):
        if text.startswith(token):
            text = text[len(token) :].strip()
    text = text.strip("`'\"“”")
    return text


def _invoke_title_model(
    *,
    cfg: SubmitAiTitleConfig,
    prompt: str,
    images: list[Path],
) -> str:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in images:
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{_image_media_type(path)};base64,{data}"},
            }
        )
    model = create_chat_model_with_runtime(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
    )
    resp = model.invoke([HumanMessage(content=content)])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    return _normalize_title_text(raw)


def apply_submit_ai_title_before_submit(
    page,
    *,
    account_id: str,
    label: str,
    image_paths: list[str],
    listing_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    在「提交并上架」前，使用图片 + 提示词生成新标题并写回标题输入框。

    失败不阻断提交流程（只返回状态）。
    """
    cfg = get_submit_ai_title_config()
    if not cfg.enabled:
        return {"ok": True, "applied": False, "reason": "disabled"}
    if not str(cfg.api_key or "").strip():
        _log(account_id, label, "提交前 AI 标题：未配置 API Key，跳过")
        return {"ok": True, "applied": False, "reason": "missing_api_key"}

    images = _collect_valid_image_paths(image_paths, cfg.max_image_count)
    if not images:
        _log(account_id, label, "提交前 AI 标题：未找到可用主图，跳过")
        return {"ok": True, "applied": False, "reason": "no_images"}

    current_title = _read_title_from_input(page)
    li = listing_info or {}
    context_lines = [
        f"商品编码：{str(li.get('merchant_code') or li.get('product_code') or '').strip()}",
        f"类目关键词：{str(li.get('category_keyword') or '').strip()}",
        f"当前标题：{current_title or '（空）'}",
        "请基于图片生成新标题，只返回最终标题。",
    ]
    final_prompt = f"{cfg.prompt}\n\n补充上下文：\n" + "\n".join(context_lines)
    try:
        generated = _invoke_title_model(cfg=cfg, prompt=final_prompt, images=images)
    except Exception as exc:
        _log(account_id, label, f"提交前 AI 标题调用失败：{exc}")
        return {"ok": True, "applied": False, "reason": "invoke_failed", "error": str(exc)}

    if not generated:
        _log(account_id, label, "提交前 AI 标题：模型返回空标题，跳过")
        return {"ok": True, "applied": False, "reason": "empty_title"}

    if not _fill_manual_title(page, account_id, generated):
        _log(account_id, label, "提交前 AI 标题：未找到标题输入框，跳过")
        return {"ok": True, "applied": False, "reason": "title_input_not_found"}

    confirmed = _read_title_from_input(page) or generated
    _log(account_id, label, f"提交前 AI 标题已更新：{confirmed[:60]}")
    return {
        "ok": True,
        "applied": True,
        "title": confirmed,
        "images_used": [str(p) for p in images],
    }
