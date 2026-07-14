"""发布页第二步：白底图(9) + 商品详情图(6~8) 上传。"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def wait_for_media_info_page(page: Page, account_id: str, label: str, *, max_wait: int = 30) -> bool:
    """等待「下一步」后进入图文信息页（含白底图 / 商品详情）。"""
    for sec in range(max_wait):
        try:
            text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            text = ""
        if "白底图" in text and "商品详情" in text:
            _log(account_id, label, "已进入图文信息页（白底图 / 商品详情）")
            return True
        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, label, f"等待图文信息页… ({sec + 1}/{max_wait}s)")
        time.sleep(1)
    return False


def _scroll_section_into_view(page: Page, keyword: str) -> None:
    try:
        page.evaluate(
            """
            (keyword) => {
              const nodes = Array.from(document.querySelectorAll('*'));
              const target = nodes.find((el) => {
                const t = (el.innerText || '').trim();
                return t.includes(keyword) && t.length <= 32;
              });
              if (target) target.scrollIntoView({ block: 'center', behavior: 'instant' });
            }
            """,
            keyword,
        )
    except Exception:
        pass
    time.sleep(0.4)


def _upload_via_file_chooser(page: Page, trigger_text: str, files: str | list[str]) -> bool:
    try:
        with page.expect_file_chooser(timeout=8_000) as fc_info:
            page.get_by_text(trigger_text, exact=True).first.click(timeout=5_000)
        fc_info.value.set_files(files)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False


def _upload_via_section_file_input(
    page: Page,
    section_keyword: str,
    files: str | list[str],
    *,
    exclude_detail: bool = False,
) -> bool:
    """在包含 section_keyword 的区域内找 file input 并上传。"""
    try:
        marked = page.evaluate(
            """
            ({ sectionKeyword, excludeDetail }) => {
              function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              document.querySelectorAll('input[data-dy-agent-target]').forEach((el) => {
                el.removeAttribute('data-dy-agent-target');
              });
              const sections = Array.from(document.querySelectorAll('*')).filter((el) => {
                if (!isVisible(el)) return false;
                const t = (el.innerText || '').trim();
                return t.includes(sectionKeyword);
              });
              if (!sections.length) return false;
              sections.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
              const section = sections[0];
              let node = section;
              for (let depth = 0; depth < 12 && node; depth++) {
                const inputs = node.querySelectorAll('input[type="file"]');
                for (const input of inputs) {
                  const vid = (input.getAttribute('data-tracking-click-viewid') || '').toLowerCase();
                  if (excludeDetail && vid.includes('detail')) continue;
                  input.setAttribute('data-dy-agent-target', 'dy-upload');
                  return true;
                }
                node = node.parentElement;
              }
              return false;
            }
            """,
            {"sectionKeyword": section_keyword, "excludeDetail": exclude_detail},
        )
        if not marked:
            return False
        locator = page.locator('input[data-dy-agent-target="dy-upload"]').first
        if locator.count() <= 0:
            return False
        locator.set_input_files(files)
        return True
    except Exception:
        return False


def _click_detail_upload_button(page: Page) -> bool:
    """点击「商品详情」区域内的「上传图片」按钮。"""
    try:
        clicked = page.evaluate(
            """
            () => {
              function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const detailAnchors = Array.from(document.querySelectorAll('*')).filter((el) => {
                if (!isVisible(el)) return false;
                const t = (el.innerText || '').trim();
                return t.startsWith('商品详情');
              });
              if (!detailAnchors.length) return false;
              detailAnchors.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
              let root = detailAnchors[0];
              for (let i = 0; i < 8 && root.parentElement; i++) root = root.parentElement;
              const buttons = Array.from(root.querySelectorAll('button, span, div, a')).filter((el) => {
                if (!isVisible(el)) return false;
                return (el.innerText || '').trim() === '上传图片';
              });
              if (!buttons.length) return false;
              buttons[0].click();
              return true;
            }
            """
        )
        return bool(clicked)
    except Exception:
        return False


def upload_white_background_image(
    page: Page,
    account_id: str,
    label: str,
    image_path: Path,
) -> bool:
    """上传 9.png 到「白底图」区域。"""
    path = str(image_path.resolve())
    if not image_path.is_file():
        _log(account_id, label, f"白底图文件不存在，跳过: {image_path.name}")
        return False

    _log(account_id, label, f"开始上传白底图: {image_path.name}")
    _scroll_section_into_view(page, "白底图")

    ok = _upload_via_file_chooser(page, "上传白底图", path)
    if not ok:
        ok = _upload_via_section_file_input(page, "白底图", path, exclude_detail=True)
    if not ok:
        _log(account_id, label, "白底图上传失败：未找到上传入口")
        return False

    _log(account_id, label, "白底图已提交上传")
    time.sleep(1.5)
    return True


def upload_detail_images(
    page: Page,
    account_id: str,
    label: str,
    images: list[Path],
) -> int:
    """上传 6~8.png 到「商品详情」区域，返回成功提交张数。"""
    paths = [str(p.resolve()) for p in images if p.is_file()]
    if not paths:
        _log(account_id, label, "无可用详情图 (6~8.png)，跳过")
        return 0

    _log(account_id, label, f"开始上传商品详情图 {len(paths)} 张…")
    _scroll_section_into_view(page, "商品详情")

    ok = False
    try:
        with page.expect_file_chooser(timeout=8_000) as fc_info:
            if not _click_detail_upload_button(page):
                page.locator("div").filter(has_text="商品详情").get_by_text("上传图片", exact=True).first.click(
                    timeout=5_000
                )
        fc_info.value.set_files(paths)
        ok = True
    except PlaywrightTimeoutError:
        ok = False
    except Exception:
        ok = False

    if not ok:
        ok = _upload_via_section_file_input(page, "商品详情", paths)

    if not ok:
        _log(account_id, label, "商品详情图上传失败：未找到上传入口")
        return 0

    _log(account_id, label, f"商品详情图已提交 {len(paths)} 张")
    time.sleep(2)
    return len(paths)


def upload_media_images_step2(
    page: Page,
    account_id: str,
    label: str,
    *,
    material_image: Path | None,
    detail_images: list[Path],
) -> dict:
    """Step2 总入口：白底图 → 详情图。"""
    if not wait_for_media_info_page(page, account_id, label):
        raise RuntimeError(f"[{account_id}] [{label}] 未进入图文信息页（白底图/商品详情）")

    white_ok = upload_white_background_image(page, account_id, label, material_image) if material_image else False
    detail_count = upload_detail_images(page, account_id, label, detail_images)

    if material_image and not white_ok:
        raise RuntimeError(f"[{account_id}] [{label}] 白底图上传失败")
    if detail_images and detail_count <= 0:
        raise RuntimeError(f"[{account_id}] [{label}] 商品详情图上传失败")

    return {
        "white_background_uploaded": white_ok,
        "detail_images_uploaded": detail_count,
    }
