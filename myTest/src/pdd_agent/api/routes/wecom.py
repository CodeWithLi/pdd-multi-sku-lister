"""企业微信消息推送 API。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.wecom import (
    WecomConfigOut,
    WecomConfigUpdateIn,
    WecomDailyContentOut,
    WecomDailyContentUpdateIn,
    WecomDailyReportLogDetailOut,
    WecomDailyReportLogListOut,
    WecomDailyReportLogOut,
    WecomDailyReportPlatform,
    WecomDailyReportPreviewOut,
    WecomDailyReportTriggerIn,
    WecomDailyReportTriggerOut,
    WecomHealthOut,
    WecomInProgressDraftOut,
    WecomTestSendIn,
    WecomTestSendOut,
)
from pdd_agent.api.services.wecom_daily_report_scheduler import get_wecom_daily_report_scheduler
from pdd_agent.integrations.wecom.client import (
    WecomAPIError,
    build_markdown_payload,
    build_text_payload,
    send_webhook_payload,
)
from pdd_agent.integrations.wecom.config import (
    DEFAULT_WECOM_CONFIG_PATH,
    WecomConfig,
    daily_report_webhook_configured,
    load_wecom_config,
    mask_webhook_url,
    resolve_alert_webhook_url,
    save_wecom_config,
    wecom_configured,
)
from pdd_agent.integrations.git.digest import GitDigestError
from pdd_agent.integrations.wecom.daily_content import (
    PddDailyContent,
    TaobaoDailyContent,
    WecomDailyContent,
    load_wecom_daily_content,
    save_wecom_daily_content,
)
from pdd_agent.integrations.wecom.daily_report import generate_daily_report_draft
from pdd_agent.core.report_time_window import REPORT_WINDOW_DESCRIPTION, format_report_window_iso, report_listing_window
from pdd_agent.integrations.wecom.in_progress_draft import collect_in_progress_draft_lines
from pdd_agent.db.repositories import get_wecom_daily_report_log, list_wecom_daily_report_logs
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/wecom", tags=["wecom"])


def _config_path() -> str:
    return str(Path(os.getenv("WECOM_CONFIG_PATH", DEFAULT_WECOM_CONFIG_PATH)))


def _config_out(cfg: WecomConfig, *, expose_webhook: bool = False) -> WecomConfigOut:
    url = str(cfg.webhook_url or "").strip()
    daily_url = str(cfg.webhook_url_daily_report or "").strip()
    scheduler = get_wecom_daily_report_scheduler()
    hour = int(cfg.daily_report_schedule_hour)
    minute = int(cfg.daily_report_schedule_minute)
    return WecomConfigOut(
        enabled=bool(cfg.enabled),
        webhook_url=url if expose_webhook else "",
        webhook_url_masked=mask_webhook_url(url) if url else "",
        webhook_configured=bool(url),
        webhook_url_daily_report=daily_url if expose_webhook else "",
        webhook_url_daily_report_masked=mask_webhook_url(daily_url) if daily_url else "",
        webhook_daily_report_configured=bool(daily_url or url),
        notify_on_listing_failed=bool(cfg.notify_on_listing_failed),
        notify_on_pipeline_failed=bool(cfg.notify_on_pipeline_failed),
        notify_on_commerce_queued=bool(cfg.notify_on_commerce_queued),
        notify_on_commerce_dispatched=bool(cfg.notify_on_commerce_dispatched),
        daily_report_schedule_enabled=bool(cfg.daily_report_schedule_enabled),
        daily_report_schedule_hour=hour,
        daily_report_schedule_minute=minute,
        daily_report_schedule_time=f"{hour:02d}:{minute:02d}",
        daily_report_scheduler_running=scheduler.is_running,
        daily_report_last_run_date=(
            scheduler.last_run_date.isoformat() if scheduler.last_run_date else ""
        ),
        config_path=_config_path(),
    )


def _merge_webhook_url(incoming: str, existing: str) -> str:
    text = str(incoming or "").strip()
    if text:
        return text
    return str(existing or "").strip()


def _build_test_payload(body: WecomTestSendIn) -> dict:
    if body.msgtype == "raw":
        if not body.raw_payload:
            raise ValueError("raw 模式需提供 raw_payload（完整企业微信消息体）")
        return dict(body.raw_payload)

    content = str(body.content or "").strip()
    if not content:
        raise ValueError("消息内容不能为空")

    if body.msgtype == "text":
        return build_text_payload(content)
    if body.msgtype == "markdown_v2":
        return build_markdown_payload(content, version="markdown_v2")
    return build_markdown_payload(content, version="markdown")


@router.get("/health", response_model=WecomHealthOut)
def wecom_health():
    cfg = load_wecom_config()
    url = str(cfg.webhook_url or "").strip()
    return WecomHealthOut(
        configured=wecom_configured(cfg),
        enabled=bool(cfg.enabled),
        webhook_configured=bool(url),
        config_path=_config_path(),
    )


@router.get("/config", response_model=WecomConfigOut)
def get_wecom_config():
    return _config_out(load_wecom_config())


@router.put("/config", response_model=WecomConfigOut)
def update_wecom_config(body: WecomConfigUpdateIn):
    existing = load_wecom_config()
    webhook_url = _merge_webhook_url(body.webhook_url, existing.webhook_url)
    webhook_url_daily_report = _merge_webhook_url(
        body.webhook_url_daily_report,
        existing.webhook_url_daily_report,
    )
    if body.enabled and not webhook_url and not webhook_url_daily_report:
        raise HTTPException(status_code=400, detail="启用前请填写至少一个 Webhook 地址")

    saved = save_wecom_config(
        WecomConfig(
            enabled=bool(body.enabled),
            webhook_url=webhook_url,
            webhook_url_daily_report=webhook_url_daily_report,
            notify_on_listing_failed=bool(body.notify_on_listing_failed),
            notify_on_pipeline_failed=bool(body.notify_on_pipeline_failed),
            notify_on_commerce_queued=bool(body.notify_on_commerce_queued),
            notify_on_commerce_dispatched=bool(body.notify_on_commerce_dispatched),
            daily_report_schedule_enabled=bool(body.daily_report_schedule_enabled),
            daily_report_schedule_hour=int(body.daily_report_schedule_hour),
            daily_report_schedule_minute=int(body.daily_report_schedule_minute),
        )
    )
    get_wecom_daily_report_scheduler().reset_last_run_date()
    return _config_out(saved)


@router.post("/test", response_model=WecomTestSendOut)
def test_wecom_send(body: WecomTestSendIn):
    cfg = load_wecom_config()
    webhook_url = str(body.webhook_url or "").strip()
    if body.use_saved_webhook or not webhook_url:
        webhook_url = resolve_alert_webhook_url(cfg)
    if not webhook_url:
        raise HTTPException(status_code=400, detail="未配置 Webhook 地址")

    try:
        payload = _build_test_payload(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        data = send_webhook_payload(payload, webhook_url=webhook_url, cfg=cfg)
    except WecomAPIError as exc:
        return WecomTestSendOut(
            ok=False,
            errcode=int(exc.errcode or -1),
            errmsg=str(exc),
            payload_sent=payload,
            response=dict(exc.payload or {}),
        )

    return WecomTestSendOut(
        ok=True,
        errcode=0,
        errmsg="ok",
        payload_sent=payload,
        response=data,
    )


def _daily_content_out(content: WecomDailyContent) -> WecomDailyContentOut:
    return WecomDailyContentOut(
        content_date=str(content.content_date or ""),
        pdd_in_progress=str(content.pdd.in_progress or ""),
        taobao_netdisk_materials=str(content.taobao.netdisk_materials or ""),
        taobao_in_progress=str(content.taobao.in_progress or ""),
        updated_at=str(content.updated_at or ""),
        database_available=is_database_available(),
    )


def _preview_out(draft) -> WecomDailyReportPreviewOut:
    return WecomDailyReportPreviewOut(
        platform=draft.platform,
        report_date=draft.report_date,
        repo_path=draft.repo_path,
        commit_count=draft.commit_count,
        progress_summary=draft.progress_summary,
        progress_summary_from_cache=bool(draft.progress_summary_from_cache),
        store_progress=draft.store_progress,
        netdisk_materials=draft.netdisk_materials,
        in_progress=draft.in_progress,
        in_progress_manual=draft.in_progress_manual,
        in_progress_auto_draft=draft.in_progress_auto_draft,
        listing_window_start=draft.listing_window_start,
        listing_window_end=draft.listing_window_end,
        git_window_start=draft.git_window_start,
        git_window_end=draft.git_window_end,
        store_summaries=[
            {
                "account_id": s.account_id,
                "shop_display_name": s.shop_display_name,
                "count": s.count,
                "limited_time_success_count": s.limited_time_success_count,
                "activity_register_success_count": s.activity_register_success_count,
                "promotion_success_count": s.promotion_success_count,
            }
            for s in draft.store_summaries
        ],
        message=draft.message,
        commits=[
            {
                "short_hash": c.short_hash,
                "author": c.author,
                "committed_at": c.committed_at,
                "subject": c.subject,
                "body": c.body,
                "file_count": len(c.files),
            }
            for c in draft.commits
        ],
    )


@router.get("/daily-content", response_model=WecomDailyContentOut)
def get_wecom_daily_content():
    return _daily_content_out(load_wecom_daily_content())


@router.put("/daily-content", response_model=WecomDailyContentOut)
def update_wecom_daily_content(body: WecomDailyContentUpdateIn):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="数据库不可用，无法保存日报手动内容")
    try:
        saved = save_wecom_daily_content(
            WecomDailyContent(
                pdd=PddDailyContent(in_progress=str(body.pdd_in_progress or "")),
                taobao=TaobaoDailyContent(
                    netdisk_materials=str(body.taobao_netdisk_materials or ""),
                    in_progress=str(body.taobao_in_progress or ""),
                ),
            )
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _daily_content_out(saved)


def _log_out(row, *, include_message: bool = False) -> WecomDailyReportLogOut | WecomDailyReportLogDetailOut:
    message = str(row.message or "")
    preview = message[:240] + ("…" if len(message) > 240 else "")
    window_start = row.window_start.strftime("%Y-%m-%d %H:%M") if row.window_start else ""
    window_end = row.window_end.strftime("%Y-%m-%d %H:%M") if row.window_end else ""
    created_at = row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else ""
    common = dict(
        log_id=row.log_id,
        platform=row.platform,
        report_date=row.report_date.isoformat(),
        window_start=window_start,
        window_end=window_end,
        trigger_kind=str(row.trigger_kind or ""),
        status=str(row.status or ""),
        errcode=int(row.errcode or 0),
        errmsg=str(row.errmsg or ""),
        webhook_target=str(row.webhook_target or ""),
        created_at=created_at,
    )
    if include_message:
        return WecomDailyReportLogDetailOut(message=message, **common)
    return WecomDailyReportLogOut(message_preview=preview, **common)


@router.get("/daily-report/logs", response_model=WecomDailyReportLogListOut)
def list_daily_report_logs(
    platform: str = "",
    page: int = 1,
    page_size: int = 20,
):
    rows, total = list_wecom_daily_report_logs(
        page=page,
        page_size=page_size,
        platform=str(platform or "").strip(),
    )
    return WecomDailyReportLogListOut(
        items=[_log_out(row) for row in rows],  # type: ignore[arg-type]
        total=total,
        page=max(1, page),
        page_size=max(1, min(100, page_size)),
    )


@router.get("/daily-report/logs/{log_id}", response_model=WecomDailyReportLogDetailOut)
def get_daily_report_log(log_id: str):
    row = get_wecom_daily_report_log(log_id)
    if not row:
        raise HTTPException(status_code=404, detail="日报发送记录不存在")
    return _log_out(row, include_message=True)


@router.get("/daily-report/in-progress-draft", response_model=WecomInProgressDraftOut)
def get_in_progress_draft():
    """获取 PDD 日报「正在解决/优化中」系统建议草稿。"""
    start, end = report_listing_window()
    window_start, window_end = format_report_window_iso(start, end)
    lines = collect_in_progress_draft_lines(window_start=start, window_end=end)
    return WecomInProgressDraftOut(
        draft="\n".join(lines),
        window_start=window_start,
        window_end=window_end,
        window_description=REPORT_WINDOW_DESCRIPTION,
    )


@router.get("/daily-report/preview", response_model=WecomDailyReportPreviewOut)
def preview_daily_report(platform: WecomDailyReportPlatform = "pdd"):
    """预览指定平台日报草稿（不发送企业微信）。"""
    try:
        draft = generate_daily_report_draft(platform=platform)
    except GitDigestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成日报失败: {exc}") from exc
    return _preview_out(draft)


@router.post("/daily-report/trigger", response_model=WecomDailyReportTriggerOut)
def trigger_daily_report(body: WecomDailyReportTriggerIn | None = None):
    """手动触发：立即生成并发送指定平台日报。"""
    platform = (body.platform if body else "pdd")
    custom_message = str(body.message or "").strip() if body else ""
    cfg = load_wecom_config()
    if not daily_report_webhook_configured(cfg):
        raise HTTPException(status_code=400, detail="请先启用企业微信并配置日报 Webhook")
    label = "PDD" if platform == "pdd" else "淘宝"
    try:
        ok = get_wecom_daily_report_scheduler().trigger_now(
            platform,
            message=custom_message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发送日报失败: {exc}") from exc
    if not ok:
        return WecomDailyReportTriggerOut(
            ok=False,
            platform=platform,
            message=f"{label}日报发送失败，请查看后台日志",
        )
    return WecomDailyReportTriggerOut(
        ok=True,
        platform=platform,
        message=f"{label}日报已发送",
    )
