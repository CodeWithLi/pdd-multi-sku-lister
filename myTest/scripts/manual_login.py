"""
首次登录店铺：自动填账号密码，滑块需你在浏览器窗口手动完成。

用法（在 myTest 目录）：
  set PYTHONPATH=src
  python scripts/manual_login.py store_B

成功后登录态写入 data/profiles/{account_id}/user_data/，后续任务可免登录。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdd_agent.browser import BrowserManager, BrowserSession
from pdd_agent.core.config import get_account, load_yaml_settings
from pdd_agent.core.logging import setup_logging


async def main(account_id: str) -> int:
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    account = get_account(settings, account_id)
    if not account:
        print(f"未知店铺: {account_id}")
        return 1

    if settings.browser.headless:
        print("提示: config/settings.yaml 中 browser.headless 建议设为 false，才能看到滑块窗口")

    manager = BrowserManager(settings)
    await manager.start()
    try:
        async with manager.open_context(account_id) as context:
            session = await BrowserSession.open(account, context)
            print(f"\n[{account_id}] 正在打开拼多多商家后台…")
            print("若出现拼图滑块，请在弹出的浏览器里手动拖动完成，无需录屏。\n")
            await session.ensure_login(settings)
            print(f"\n[{account_id}] 登录成功，Profile 已保存到 data/profiles/{account_id}/user_data/\n")
            return 0
    except Exception as exc:
        print(f"\n[{account_id}] 登录失败: {exc}\n")
        return 1
    finally:
        await manager.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="手动完成首次登录（含滑块）")
    parser.add_argument("account_id", help="店铺 ID，如 store_B")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.account_id)))
