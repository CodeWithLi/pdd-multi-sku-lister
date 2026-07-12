"""发布页主图上传（1~5 张）。"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

UPLOAD_TRIGGER_TEXTS = ("上传主图", "上传辅助图", "上传图片")


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _count_uploaded_main_images(page: Page) -> int:
    try:
        return int(
            page.evaluate(
                """
                () => {
                  const section = Array.from(document.querySelectorAll('*'))
                    .find(el => (el.innerText || '').includes('主图上传'));
                  if (!section) return 0;
                  let root = section;
                  for (let i = 0; i < 6 && root.parentElement; i++) root = root.parentElement;
                  const imgs = root.querySelectorAll('img');
                  let n = 0;
                  for (const img of imgs) {
                    const r = img.getBoundingClientRect();
                    if (r.width >= 40 && r.height >= 40) n++;
                  }
                  return n;
                }
                """
            )
        )
    except Exception:
        return 0


def _upload_via_file_inputs(page: Page, image_path: str, index: int) -> bool:
    inputs = page.locator('input[type="file"]')
    if inputs.count() <= index:
        return False
    try:
        inputs.nth(index).set_input_files(image_path)
        return True
    except Exception:
        return False


def _upload_via_file_chooser(page: Page, image_path: str, trigger_text: str) -> bool:
    try:
        with page.expect_file_chooser(timeout=5_000) as fc_info:
            page.get_by_text(trigger_text, exact=True).first.click(timeout=3_000)
        fc_info.value.set_files(image_path)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False


def upload_main_carousel_images(
    page: Page,
    account_id: str,
    label: str,
    images: list[Path],
    *,
    max_images: int = 5,
) -> int:
    """上传主图 1~5，返回成功上传数量。"""
    paths = [str(p.resolve()) for p in images[:max_images] if p.is_file()]
    if not paths:
        raise RuntimeError(f"[{account_id}] [{label}] 无可用主图文件")

    _log(account_id, label, f"开始上传主图 {len(paths)} 张…")
    uploaded = 0

    for idx, image_path in enumerate(paths):
        trigger = UPLOAD_TRIGGER_TEXTS[0] if idx == 0 else UPLOAD_TRIGGER_TEXTS[1]
        ok = _upload_via_file_inputs(page, image_path, idx)
        if not ok:
            ok = _upload_via_file_chooser(page, image_path, trigger)
        if not ok:
            ok = _upload_via_file_chooser(page, image_path, UPLOAD_TRIGGER_TEXTS[2])

        if ok:
            uploaded += 1
            _log(account_id, label, f"主图 {idx + 1}/{len(paths)} 已提交: {Path(image_path).name}")
            time.sleep(1.2)
        else:
            _log(account_id, label, f"主图 {idx + 1} 上传失败: {Path(image_path).name}")

    for sec in range(30):
        current = _count_uploaded_main_images(page)
        if current >= uploaded and uploaded > 0:
            _log(account_id, label, f"主图上传完成（页面约 {current} 张预览）")
            return uploaded
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, label, f"等待主图渲染… ({sec + 1}/30s)")
        time.sleep(1)

    if uploaded > 0:
        _log(account_id, label, f"主图已提交 {uploaded} 张（预览计数未完全确认）")
        return uploaded
    raise RuntimeError(f"[{account_id}] [{label}] 主图上传失败")
