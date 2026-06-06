#!/usr/bin/env python3
"""
从 npmmirror 安装 Playwright 自带 Chromium（适用于国内 / 服务器部署）。

Playwright 1.49+ 的 Chromium 走 Chrome-for-Testing 路径 builds/cft/...，
npmmirror 实际文件在 chrome-for-testing/<version>/<platform>/ 下，无 builds/cft 前缀，
因此 PLAYWRIGHT_DOWNLOAD_HOST 会 404。本脚本按 --dry-run 解析安装目录，从镜像正确 URL 下载并解压。

用法（在 myTest 根目录、已激活 .venv）:
  python scripts/install_playwright_browsers.py
  python scripts/install_playwright_browsers.py --chromium-only
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

NPPMirror_CFT = "https://cdn.npmmirror.com/binaries/chrome-for-testing"
NPPMirror_PW = "https://cdn.npmmirror.com/binaries/playwright/builds"


def _rewrite_mirror_url(url: str) -> str:
    """将官方 CDN URL 转为 npmmirror 可访问地址。"""
    # Chrome for Testing: .../builds/cft/148.x/win64/chrome-win64.zip
    m = re.search(
        r"/builds/cft/([\d.]+)/([^/]+)/(chrome-win64|chrome-headless-shell-win64)\.zip",
        url,
    )
    if m:
        version, platform, name = m.groups()
        return f"{NPPMirror_CFT}/{version}/{platform}/{name}.zip"

    # ffmpeg / winldd / 旧版 chromium: .../builds/<type>/<rev>/<file>.zip
    m = re.search(r"/builds/((?:ffmpeg|winldd|chromium|firefox|webkit)/.+?\.zip)", url)
    if m:
        return f"{NPPMirror_PW}/{m.group(1)}"

    return url


def _parse_dry_run(text: str) -> list[tuple[str, str, str]]:
    """
    解析 playwright install --dry-run 输出。
    返回 [(标题, 安装目录, 下载URL), ...]
    """
    items: list[tuple[str, str, str]] = []
    title = ""
    install_dir = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Install location:"):
            install_dir = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Download url:") and install_dir:
            url = line.split(":", 1)[1].strip()
            items.append((title or "browser", install_dir, url))
            continue
        if line.startswith("Download fallback"):
            continue
        # 新条目标题行（在 Install location 之前）
        if "(" in line and "playwright" in line.lower():
            title = line.split("(")[0].strip()
            install_dir = ""
    return items


def _download(url: str, dest: Path) -> None:
    print(f"  下载: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        pct = min(100, block_num * block_size * 100 // total_size)
        print(f"\r  进度: {pct}%", end="", flush=True)

    urlretrieve(url, dest, reporthook=_progress)
    print()


def _extract(zip_path: Path, install_dir: Path) -> None:
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(install_dir)
    print(f"  解压到: {install_dir}")


def _run_dry_run(python: str) -> str:
    proc = subprocess.run(
        [python, "-m", "playwright", "install", "chromium", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"playwright --dry-run 失败:\n{out}")
    return out


def install(chromium_only: bool = True) -> None:
    python = sys.executable
    print("解析 Playwright 安装清单...")
    dry = _run_dry_run(python)
    items = _parse_dry_run(dry)
    if not items:
        print("未解析到下载项，原始输出:\n", dry)
        sys.exit(1)

    seen_dirs: set[str] = set()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for title, install_dir, official_url in items:
            if chromium_only and "chromium" not in title.lower() and "ffmpeg" not in title.lower():
                if "winldd" in title.lower():
                    continue
            # ffmpeg 两个 browser 条目重复，跳过重复目录
            if install_dir in seen_dirs:
                continue
            seen_dirs.add(install_dir)

            mirror = _rewrite_mirror_url(official_url)
            print(f"\n[{title}]")
            zip_file = tmp_path / f"{hash(install_dir)}.zip"
            try:
                _download(mirror, zip_file)
            except Exception as exc:
                print(f"  镜像失败: {exc}")
                print(f"  尝试官方源: {official_url}")
                _download(official_url, zip_file)
            _extract(zip_file, Path(install_dir))

    print("\n验证安装...")
    proc = subprocess.run(
        [python, "-m", "playwright", "install", "chromium", "--dry-run"],
        capture_output=True,
        text=True,
    )
    print(proc.stdout or proc.stderr or "")
    print("完成。可运行:")
    print("  python -c \"from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); print('OK'); b.close(); p.stop()\"")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 npmmirror 安装 Playwright Chromium")
    parser.add_argument(
        "--all",
        action="store_true",
        help="同时安装 winldd 等（默认仅 chromium + ffmpeg）",
    )
    args = parser.parse_args()
    install(chromium_only=not args.all)


if __name__ == "__main__":
    main()
