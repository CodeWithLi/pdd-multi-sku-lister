"""提交前 AI 改标题（独立于历史 page_ai 流程）。"""

from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from pdd_agent.api.services.submit_ai_title_config_service import (
    SubmitAiTitleConfig,
    get_submit_ai_title_config,
)
from pdd_agent.llm.factory import create_chat_model_with_runtime
from pdd_agent.skills.listing.page_ai_title import (
    _diagnose_title_length_error,
    _fill_manual_title,
    _has_title_length_error,
    _read_title_from_input,
)
from pdd_agent.skills.listing.pdd_listing_quality_v2 import (
    generate_compliant_title,
    quality_v2_enabled,
)

# 单次模型调用硬超时（秒）；超时视为失败并走兜底/跳过，避免上架线程无限阻塞。
SUBMIT_AI_TITLE_REQUEST_TIMEOUT_SECONDS = 60


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


def _classify_title_model_exception(exc: Exception) -> tuple[str, str]:
    text = str(exc or "").strip()
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "image_url",
            "image url",
            "vision",
            "multimodal",
            "multi-modal",
            "does not support images",
            "doesn't support images",
            "image input",
        )
    ):
        return "model_not_vision_capable", text
    if any(
        token in lowered
        for token in (
            "invalid image",
            "invalid base64",
            "base64",
            "payload too large",
            "request too large",
            "image too large",
            "unsupported image",
            "image format",
        )
    ):
        return "image_payload_rejected", text
    if any(
        token in lowered
        for token in (
            "timeout",
            "timed out",
            "time out",
            "readtimeout",
            "connecttimeout",
            "deadline exceeded",
        )
    ):
        return "model_invoke_timeout", text
    return "model_invoke_failed", text


def _model_label(cfg: SubmitAiTitleConfig) -> str:
    provider = str(cfg.provider or "").strip() or "model"
    model = str(cfg.model or "").strip() or "-"
    return f"{provider}/{model}"


def _build_title_message_content(prompt: str, images: list[Path]) -> list[dict[str, Any]]:
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
    return content


def _invoke_title_model_once(
    *,
    cfg: SubmitAiTitleConfig,
    prompt: str,
    images: list[Path],
    request_timeout: float,
) -> str:
    content = _build_title_message_content(prompt, images)
    model = create_chat_model_with_runtime(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        request_timeout=request_timeout,
    )
    resp = model.invoke([HumanMessage(content=content)])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    return _normalize_title_text(raw)


def _invoke_title_model(
    *,
    cfg: SubmitAiTitleConfig,
    prompt: str,
    images: list[Path],
    account_id: str,
    label: str,
    role: str,
    request_timeout: float = SUBMIT_AI_TITLE_REQUEST_TIMEOUT_SECONDS,
) -> str:
    timeout_seconds = max(1.0, float(request_timeout or SUBMIT_AI_TITLE_REQUEST_TIMEOUT_SECONDS))
    model_name = _model_label(cfg)
    _log(
        account_id,
        label,
        f"提交前 AI 标题：开始调用{role} {model_name}，图片 {len(images)} 张，超时 {int(timeout_seconds)}s",
    )
    started = time.monotonic()

    def _run() -> str:
        return _invoke_title_model_once(
            cfg=cfg,
            prompt=prompt,
            images=images,
            request_timeout=timeout_seconds,
        )

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="submit-ai-title") as pool:
        future = pool.submit(_run)
        try:
            title = future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as exc:
            raise TimeoutError(
                f"{role} 调用超时（>{int(timeout_seconds)}s） model={model_name}"
            ) from exc

    elapsed = time.monotonic() - started
    preview = title[:40] if title else "（空）"
    _log(
        account_id,
        label,
        f"提交前 AI 标题：{role} {model_name} 返回（{elapsed:.1f}s） title={preview}",
    )
    return title


def _invoke_title_with_fallback(
    *,
    cfg: SubmitAiTitleConfig,
    prompt: str,
    images: list[Path],
    account_id: str,
    label: str,
) -> dict[str, Any]:
    """
    一级：提交前标题配置（默认 deepseek）
    二级兜底：环境 LLM（建议配成 glm）
    """
    primary_reason = ""
    primary_error = ""
    timeout_seconds = SUBMIT_AI_TITLE_REQUEST_TIMEOUT_SECONDS
    try:
        title = _invoke_title_model(
            cfg=cfg,
            prompt=prompt,
            images=images,
            account_id=account_id,
            label=label,
            role="主模型",
            request_timeout=timeout_seconds,
        )
        if title:
            return {
                "title": title,
                "source": "primary",
                "reason": "",
                "fallback_used": False,
                "primary_reason": "",
                "primary_error": "",
                "fallback_reason": "",
                "fallback_error": "",
            }
        _log(account_id, label, "提交前 AI 标题：主模型返回空标题，尝试 GLM 兜底")
        primary_reason = "empty_title"
    except Exception as exc:
        primary_reason, primary_error = _classify_title_model_exception(exc)
        _log(account_id, label, f"提交前 AI 标题：主模型失败，尝试 GLM 兜底（{primary_reason}: {exc}）")

    if not cfg.fallback_enabled:
        return {
            "title": "",
            "source": "primary",
            "reason": primary_reason or "fallback_disabled",
            "fallback_used": False,
            "primary_reason": primary_reason,
            "primary_error": primary_error,
            "fallback_reason": "fallback_disabled",
            "fallback_error": "",
        }
    if not str(cfg.fallback_api_key or "").strip():
        return {
            "title": "",
            "source": "primary",
            "reason": primary_reason or "fallback_missing_api_key",
            "fallback_used": False,
            "primary_reason": primary_reason,
            "primary_error": primary_error,
            "fallback_reason": "fallback_missing_api_key",
            "fallback_error": "",
        }

    fallback_cfg = SubmitAiTitleConfig(
        enabled=True,
        provider=cfg.fallback_provider,
        model=cfg.fallback_model,
        base_url=cfg.fallback_base_url,
        api_key=cfg.fallback_api_key,
        prompt=cfg.prompt,
        temperature=cfg.temperature,
        max_image_count=cfg.max_image_count,
    )
    fallback_reason = ""
    fallback_error = ""
    try:
        title = _invoke_title_model(
            cfg=fallback_cfg,
            prompt=prompt,
            images=images,
            account_id=account_id,
            label=label,
            role="兜底模型",
            request_timeout=timeout_seconds,
        )
        if title:
            return {
                "title": title,
                "source": "glm_fallback",
                "reason": "fallback_used",
                "fallback_used": True,
                "primary_reason": primary_reason,
                "primary_error": primary_error,
                "fallback_reason": "",
                "fallback_error": "",
            }
        fallback_reason = "fallback_empty_title"
        _log(account_id, label, "提交前 AI 标题：兜底模型返回空标题，跳过 AI 改标题并继续提交")
    except Exception as exc:
        fallback_reason, fallback_error = _classify_title_model_exception(exc)
        _log(account_id, label, f"提交前 AI 标题：GLM 兜底也失败（{fallback_reason}: {exc}），跳过并继续提交")
    return {
        "title": "",
        "source": "glm_fallback",
        "reason": fallback_reason or primary_reason or "fallback_failed",
        "fallback_used": False,
        "primary_reason": primary_reason,
        "primary_error": primary_error,
        "fallback_reason": fallback_reason,
        "fallback_error": fallback_error,
    }


def _invoke_title_for_active_policy(
    *,
    cfg: SubmitAiTitleConfig,
    prompt: str,
    images: list[Path],
    account_id: str,
    label: str,
) -> dict[str, Any]:
    def _invoke(candidate_prompt: str) -> dict[str, Any]:
        return _invoke_title_with_fallback(
            cfg=cfg,
            prompt=candidate_prompt,
            images=images,
            account_id=account_id,
            label=label,
        )

    if quality_v2_enabled():
        return generate_compliant_title(base_prompt=prompt, invoke=_invoke)
    return _invoke(prompt)


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
    _log(
        account_id,
        label,
        "提交前 AI 标题：开始生成（失败或超时将沿用页面标题并继续提交）",
    )
    invoke_result = _invoke_title_for_active_policy(
        cfg=cfg,
        prompt=final_prompt,
        images=images,
        account_id=account_id,
        label=label,
    )
    generated = str(invoke_result.get("title") or "").strip()
    source = str(invoke_result.get("source") or "")
    reason = str(invoke_result.get("reason") or "")
    fallback_used = bool(invoke_result.get("fallback_used"))
    primary_reason = str(invoke_result.get("primary_reason") or "")
    primary_error = str(invoke_result.get("primary_error") or "")
    fallback_reason = str(invoke_result.get("fallback_reason") or "")
    fallback_error = str(invoke_result.get("fallback_error") or "")

    if not generated:
        preserved = _read_title_from_input(page) or current_title or ""
        _log(
            account_id,
            label,
            f"提交前 AI 标题：未生成可用标题（{reason or source or 'empty_title'}），沿用页面现有标题并继续提交",
        )
        return {
            "ok": not bool(invoke_result.get("policy_failed")),
            "applied": False,
            "reason": reason or source or "empty_title",
            "preserved_title": preserved,
            "previous_title": current_title,
            "generated_title": "",
            "final_title": preserved,
            "length_reverted": False,
            "fallback_used": fallback_used,
            "primary_reason": primary_reason,
            "primary_error": primary_error,
            "fallback_reason": fallback_reason,
            "fallback_error": fallback_error,
            "images_used": [str(p) for p in images],
        }

    if not _fill_manual_title(page, account_id, generated):
        _log(account_id, label, "提交前 AI 标题：未找到标题输入框，跳过")
        preserved = _read_title_from_input(page) or current_title or ""
        return {
            "ok": True,
            "applied": False,
            "reason": "title_input_not_found",
            "preserved_title": preserved,
            "previous_title": current_title,
            "generated_title": generated,
            "final_title": preserved,
            "length_reverted": False,
            "fallback_used": fallback_used,
            "primary_reason": primary_reason,
            "primary_error": primary_error,
            "fallback_reason": fallback_reason,
            "fallback_error": fallback_error,
            "images_used": [str(p) for p in images],
        }

    length_diag = _diagnose_title_length_error(page)
    _log(
        account_id,
        label,
        "提交前 AI 标题长度校验探测："
        f" has_error={bool(length_diag.get('has_error'))}"
        f" matched={str(length_diag.get('matched_text') or '-')[:80]}"
        f" source={str(length_diag.get('matched_source') or '-')}"
        f" placeholder={str(length_diag.get('placeholder') or '-')[:60]}",
    )
    if _has_title_length_error(page):
        quality_v2 = quality_v2_enabled()
        restored = False
        original_title = (current_title or "").strip()
        if original_title:
            restored = _fill_manual_title(page, account_id, original_title)
        preserved = _read_title_from_input(page) or original_title
        _log(
            account_id,
            label,
            "提交前 AI 标题：新标题触发页面长度校验，已回退到原标题",
        )
        return {
            "ok": not quality_v2,
            "applied": False,
            "reason": (
                "title_platform_length_rejected"
                if quality_v2
                else "title_length_exceeded_reverted"
            ),
            "preserved_title": preserved,
            "generated_title": generated,
            "previous_title": current_title,
            "final_title": preserved,
            "length_reverted": True,
            "length_check": length_diag,
            "restored": restored,
            "fallback_used": fallback_used,
            "primary_reason": primary_reason,
            "primary_error": primary_error,
            "fallback_reason": fallback_reason,
            "fallback_error": fallback_error,
            "images_used": [str(p) for p in images],
        }

    confirmed = _read_title_from_input(page) or generated
    _log(
        account_id,
        label,
        "提交前 AI 标题结果："
        f" source={source or '-'}"
        f" reason={reason or '-'}"
        f" fallback_used={fallback_used}"
        f" previous={current_title[:40] or '（空）'}"
        f" generated={generated[:40]}"
        f" final={confirmed[:40]}"
        f" images={len(images)}",
    )
    return {
        "ok": True,
        "applied": True,
        "source": source,
        "reason": reason,
        "title": confirmed,
        "previous_title": current_title,
        "generated_title": generated,
        "final_title": confirmed,
        "length_reverted": False,
        "fallback_used": fallback_used,
        "primary_reason": primary_reason,
        "primary_error": primary_error,
        "fallback_reason": fallback_reason,
        "fallback_error": fallback_error,
        "images_used": [str(p) for p in images],
    }


def generate_submit_ai_title(
    *,
    account_id: str,
    label: str,
    image_paths: list[str],
    listing_info: dict[str, Any] | None = None,
    current_title: str = "",
) -> dict[str, Any]:
    """
    纯生成版本：用于配置页/接口测试（不依赖 Playwright page）。

    - 若配置未启用或缺 key：返回 applied=False + reason
    - 成功：返回 title + images_used + source
    """
    cfg = get_submit_ai_title_config()
    if not cfg.enabled:
        return {"ok": True, "applied": False, "reason": "disabled"}
    if not str(cfg.api_key or "").strip():
        return {"ok": True, "applied": False, "reason": "missing_api_key"}

    images = _collect_valid_image_paths(image_paths, cfg.max_image_count)
    if not images:
        return {"ok": True, "applied": False, "reason": "no_images"}

    li = listing_info or {}
    context_lines = [
        f"商品编码：{str(li.get('merchant_code') or li.get('product_code') or '').strip()}",
        f"类目关键词：{str(li.get('category_keyword') or '').strip()}",
        f"当前标题：{str(current_title or '').strip() or '（空）'}",
        "请基于图片生成新标题，只返回最终标题。",
    ]
    final_prompt = f"{cfg.prompt}\n\n补充上下文：\n" + "\n".join(context_lines)
    invoke_result = _invoke_title_for_active_policy(
        cfg=cfg,
        prompt=final_prompt,
        images=images,
        account_id=account_id,
        label=label,
    )
    generated = str(invoke_result.get("title") or "").strip()
    source = str(invoke_result.get("source") or "")
    reason = str(invoke_result.get("reason") or "")
    if not generated:
        return {
            "ok": not bool(invoke_result.get("policy_failed")),
            "applied": False,
            "reason": reason or source or "empty_title",
            "source": source,
            "fallback_used": bool(invoke_result.get("fallback_used")),
            "primary_reason": str(invoke_result.get("primary_reason") or ""),
            "primary_error": str(invoke_result.get("primary_error") or ""),
            "fallback_reason": str(invoke_result.get("fallback_reason") or ""),
            "fallback_error": str(invoke_result.get("fallback_error") or ""),
            "previous_title": str(current_title or "").strip(),
            "generated_title": "",
            "final_title": str(current_title or "").strip(),
            "images_used": [str(p) for p in images],
        }
    return {
        "ok": True,
        "applied": True,
        "source": source,
        "reason": reason,
        "title": generated,
        "fallback_used": bool(invoke_result.get("fallback_used")),
        "primary_reason": str(invoke_result.get("primary_reason") or ""),
        "primary_error": str(invoke_result.get("primary_error") or ""),
        "fallback_reason": str(invoke_result.get("fallback_reason") or ""),
        "fallback_error": str(invoke_result.get("fallback_error") or ""),
        "previous_title": str(current_title or "").strip(),
        "generated_title": generated,
        "final_title": generated,
        "length_reverted": False,
        "images_used": [str(p) for p in images],
    }
