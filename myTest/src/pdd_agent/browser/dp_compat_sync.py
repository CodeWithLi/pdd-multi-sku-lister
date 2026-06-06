"""
DrissionPage 兼容层（同步 Playwright）。

让从 pdd_auto 迁移的页面操作代码尽量少改，直接接收 DpPage 而非 ChromiumPage。
"""

from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Locator, Page


def _to_playwright_selector(selector: str) -> str:
    sel = (selector or "").strip()
    if not sel:
        return sel
    if sel.startswith("css:"):
        return sel[4:]
    if sel.startswith("xpath:"):
        return sel
    if sel.startswith("text:"):
        return f"text={sel[5:]}"
    if sel.startswith("tag:"):
        body = sel[4:]
        if "@" not in body:
            return body
        tag, rest = body.split("@", 1)
        if rest.startswith("text()="):
            val = rest[7:]
            return f'{tag}:has-text("{val}")'
        if rest.startswith("placeholder="):
            val = rest[12:]
            return f'{tag}[placeholder="{val}"]'
        if rest.startswith("type="):
            val = rest[5:]
            return f'{tag}[type="{val}"]'
        return tag
    if sel.startswith("#") or sel.startswith(".") or sel.startswith("["):
        return sel
    return sel


class _LoadWait:
    def __init__(self, page: Page) -> None:
        self._page = page

    def load_start(self) -> None:
        time.sleep(1)


class _ElementState:
    def __init__(self, loc: Locator) -> None:
        self._loc = loc

    @property
    def is_displayed(self) -> bool:
        try:
            return self._loc.is_visible()
        except Exception:
            return False


class DpElement:
    def __init__(self, page: Page, locator: Locator) -> None:
        self._page = page
        self._loc = locator

    @property
    def states(self) -> _ElementState:
        return _ElementState(self._loc)

    @property
    def text(self) -> str:
        try:
            return (self._loc.inner_text(timeout=500) or "").strip()
        except Exception:
            return ""

    @property
    def value(self) -> str:
        try:
            return self._loc.input_value(timeout=500) or ""
        except Exception:
            return ""

    def attr(self, name: str) -> str | None:
        try:
            return self._loc.get_attribute(name)
        except Exception:
            return None

    def click(self, by_js: bool = False) -> None:
        if by_js:
            self._loc.evaluate("el => el.click()")
        else:
            self._loc.click(timeout=5000)

    def input(self, value: Any, clear: bool = False) -> None:
        if isinstance(value, (list, tuple)):
            self._loc.set_input_files([str(v) for v in value])
            return
        text = str(value)
        if clear:
            self._loc.fill("")
        if text == "\n":
            self._loc.press("Enter")
            return
        if (self.attr("type") or "").lower() == "file":
            self._loc.set_input_files(text)
            return
        self._loc.fill(text)

    def ele(self, selector: str, timeout: float = 5) -> DpElement | None:
        return DpPage(self._page).ele(selector, timeout=timeout, root=self._loc)

    def eles(self, selector: str, timeout: float = 5) -> list[DpElement]:
        return DpPage(self._page).eles(selector, timeout=timeout, root=self._loc)


class DpPage:
    """DrissionPage ChromiumPage 的 Playwright 同步替身。"""

    def __init__(self, page: Page) -> None:
        self._page = page
        self.wait = _LoadWait(page)

    @property
    def url(self) -> str:
        return self._page.url

    def get(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def _locator(self, selector: str, root: Locator | None = None) -> Locator:
        pw = _to_playwright_selector(selector)
        base = root or self._page
        if pw.startswith("xpath="):
            return base.locator(pw)
        if pw.startswith("text="):
            return base.get_by_text(pw[5:], exact=False)
        return base.locator(pw)

    def ele(self, selector: str, timeout: float = 5, root: Locator | None = None) -> DpElement | None:
        loc = self._locator(selector, root=root)
        try:
            loc.first.wait_for(state="attached", timeout=int(timeout * 1000))
            if not loc.first.count():
                return None
            return DpElement(self._page, loc.first)
        except Exception:
            return None

    def eles(self, selector: str, timeout: float = 5, root: Locator | None = None) -> list[DpElement]:
        loc = self._locator(selector, root=root)
        try:
            loc.first.wait_for(state="attached", timeout=int(timeout * 1000))
        except Exception:
            return []
        count = loc.count()
        return [DpElement(self._page, loc.nth(i)) for i in range(count)]

    def run_js(self, script: str, *args: Any) -> Any:
        """
        执行 JS。DrissionPage 脚本里常有顶层 return，必须包在函数体内；
        多参数时对齐 arguments[0]、arguments[1]…
        """
        body = script.strip()

        if args and isinstance(args[0], DpElement):
            fn = f"(el) => {{ const arguments = [el]; {body} }}"
            return args[0]._loc.evaluate(fn)

        if len(args) == 1:
            fn = f"(arg) => {{ const arguments = [arg]; {body} }}"
            return self._page.evaluate(fn, args[0])

        if len(args) > 1:
            fn = f"(argv) => {{ const arguments = argv; {body} }}"
            return self._page.evaluate(fn, list(args))

        fn = f"() => {{ {body} }}"
        return self._page.evaluate(fn)

    def get_screenshot(self, path: str) -> None:
        self._page.screenshot(path=path, full_page=True)

    def quit(self) -> None:
        try:
            self._page.context.close()
        except Exception:
            pass
