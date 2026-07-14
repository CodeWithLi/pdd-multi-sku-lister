"""login health helpers 单元测试。"""

from dy_agent.browser.login_health import LoginCheckResult, _page_looks_logged_in
from dy_agent.browser.shop_display_name import scrape_shop_display_name


class _FakePage:
    url = "https://fxg.jinritemai.com/"

    def evaluate(self, script, arg=""):
        return "测试抖店"


class _FakeLoggedInPage:
    url = "https://fxg.jinritemai.com/login/common"

    def evaluate(self, script):
        return True


class _FakeDp:
    url = "https://fxg.jinritemai.com/ffa/mshop/homepage"
    raw = _FakePage()


def test_scrape_shop_display_name():
    assert scrape_shop_display_name(_FakeDp(), login_phone="13800138000") == "测试抖店"


def test_login_check_result():
    row = LoginCheckResult(account_id="store_A", status="logged_in", reason="ok")
    assert row.account_id == "store_A"


def test_page_looks_logged_in_by_header_probe():
    assert _page_looks_logged_in(_FakeLoggedInPage())
