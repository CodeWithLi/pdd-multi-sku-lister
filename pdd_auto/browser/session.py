"""拼多多商家后台浏览器会话（登录复用）。"""
import time

from DrissionPage import ChromiumOptions, ChromiumPage


def _configure_chrome_options(profile_path: str) -> ChromiumOptions:
    co = ChromiumOptions()
    co.set_user_data_path(profile_path)
    # 抑制 Chrome / chromedriver 向控制台倾倒二进制或调试日志（上传图片时常见）
    co.set_argument("--disable-logging")
    co.set_argument("--log-level=3")
    co.set_argument("--silent")
    co.set_argument("--disable-dev-shm-usage")
    return co


def ensure_login(account_id, profile_path, username=None, password=None):
    """
    负责接管浏览器的启动、Session 读取与账号密码登录。
    成功返回 ChromiumPage，失败返回 None。
    """
    print(f"\n--- [{account_id}] 正在检查登录状态 ---")
    co = _configure_chrome_options(profile_path)

    page = ChromiumPage(co)
    page.set.window.max()

    try:
        page.get("https://mms.pinduoduo.com/home/")
        time.sleep(2)

        if "login" in page.url:
            print(f"[{account_id}] 未登录或缓存已过期，正在使用账号密码登录...")

            if not username or not password:
                print(f"[{account_id}] 未配置账号或密码")
                page.quit()
                return None

            account_tab = page.ele("text:账号登录", timeout=5)
            if account_tab:
                account_tab.click()
                time.sleep(1)

            user_input = page.ele("#usernameId", timeout=5)
            if user_input:
                user_input.clear()
                user_input.input(username)

            time.sleep(0.5)

            pwd_input = page.ele("#passwordId", timeout=5)
            if pwd_input:
                pwd_input.clear()
                pwd_input.input(password)

            time.sleep(1)

            login_btn = page.ele("t:span@text()=登录", timeout=5)
            if login_btn:
                login_btn.click()

            for _ in range(30):
                if "login" not in page.url:
                    print(f"[{account_id}] 账号密码登录成功")
                    time.sleep(2)
                    return page
                time.sleep(1)

            print(f"[{account_id}] 登录超时，请检查")
            page.quit()
            return None

        print(f"[{account_id}] 读取本地 Session 成功，已免密进入后台")
        return page

    except Exception as e:
        print(f"[{account_id}] 登录异常: {e}")
        page.quit()
        return None
