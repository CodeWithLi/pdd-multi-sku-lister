"""
首次登录抖店：自动打开官网、填手机号、等待你手动输入验证码后点击登录。

用法（在 dyTest 目录）：
  python scripts/manual_login.py store_A

成功后登录态写入 data/profiles/{account_id}/user_data/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dy_agent.browser.profile_lock import account_profile_lock
from dy_agent.browser.sync_job import _launch_persistent
from dy_agent.browser.sync_login import perform_sms_login_sync
from dy_agent.core.config import get_account, load_yaml_settings
from dy_agent.core.logging import setup_logging


def main(account_id: str) -> int:
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    account = get_account(settings, account_id)
    if not account:
        print(f"未知店铺: {account_id}")
        return 1

    if settings.browser.headless:
        print("提示: config/settings.yaml 中 browser.headless 建议设为 false，才能看到验证码输入窗口")

    with account_profile_lock(settings, account_id, reason="manual_login"):
        pw, context, page = _launch_persistent(settings, account_id, headless=False)
        try:
            print(f"\n[{account_id}] 正在打开抖店官网并进入登录页…")
            print("请在浏览器中：1) 确认收到短信  2) 输入验证码  3) 脚本将自动勾选协议并点击登录\n")
            perform_sms_login_sync(account, page)
            print(f"\n[{account_id}] 登录成功，Profile 已保存到 data/profiles/{account_id}/user_data/\n")
            return 0
        except Exception as exc:
            print(f"\n[{account_id}] 登录失败: {exc}\n")
            return 1
        finally:
            try:
                page.evaluate("window.onbeforeunload = null;")
            except Exception:
                pass
            context.close()
            pw.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抖店手动验证码登录")
    parser.add_argument("account_id", help="店铺 ID，如 store_A")
    args = parser.parse_args()
    raise SystemExit(main(args.account_id))
