"""从拼多多商家后台页面读取店铺展示名（如「兔兔潮玩屋」）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdd_agent.db.repositories import get_cached_shop_display_name, update_shop_display_name

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

# 右上角账号区：上行店铺名、下行登录账号（多多青提2601）
_SHOP_NAME_JS = """
const loginHint = String(arguments[0] || '').trim();

function clean(t) {
  return String(t || '').replace(/\\s+/g, ' ').trim();
}

function shopLike(t) {
  if (!t || t.length < 2 || t.length > 30) return false;
  if (loginHint && t === loginHint) return false;
  if (/退出|登录|设置|消息|帮助|商家后台|首页/.test(t)) return false;
  return /[\\u4e00-\\u9fff]/.test(t);
}

function accountLike(t) {
  if (!t || t.length < 2 || t.length > 40) return false;
  if (loginHint && t === loginHint) return true;
  return /^(多多|拼多多)/.test(t);
}

const stateKeys = ['__INITIAL_STATE__', '__NEXT_DATA__', 'rawData', '__NUXT__'];
for (const key of stateKeys) {
  try {
    const st = window[key];
    if (!st) continue;
    const json = JSON.stringify(st);
    const m = json.match(/"(?:mallName|mall_name|shopName|shop_name|storeName|store_name)"\\s*:\\s*"([^"]+)"/);
    if (m && m[1] && m[1] !== loginHint && shopLike(m[1])) return m[1];
  } catch (e) {}
}

const roots = document.querySelectorAll(
  'header, [class*="header"], [class*="Header"], [class*="top"], [class*="nav"]'
);
const scanRoots = roots.length ? roots : [document.body];
for (const root of scanRoots) {
  const nodes = root.querySelectorAll(
    '[class*="user"], [class*="mall"], [class*="shop"], [class*="account"], span, div, p'
  );
  for (const node of nodes) {
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || rect.top > 140) continue;
    const text = clean(node.innerText || node.textContent);
    if (!text || text.length > 80) continue;
    const lines = text.split('\\n').map(clean).filter(Boolean);
    if (lines.length >= 2) {
      const top = lines[0];
      const bottom = lines[lines.length - 1];
      if (loginHint && bottom === loginHint && shopLike(top)) return top;
      if (!loginHint && shopLike(top) && accountLike(bottom) && top !== bottom) return top;
    }
  }
}

if (loginHint) {
  const all = document.querySelectorAll('span, div, p, a');
  for (const el of all) {
    const t = clean(el.innerText || el.textContent);
    if (t !== loginHint) continue;
    const box = el.getBoundingClientRect();
    if (box.top > 160) continue;
    let parent = el.parentElement;
    for (let depth = 0; depth < 5 && parent; depth++) {
      const kids = Array.from(parent.children).filter((c) => {
        const r = c.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.top <= 160;
      });
      kids.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
      for (const kid of kids) {
        const kt = clean(kid.innerText || kid.textContent);
        if (!kt || kt === loginHint || kt.includes(loginHint)) continue;
        const first = kt.split('\\n').map(clean).filter(Boolean)[0] || '';
        if (shopLike(first)) return first;
      }
      parent = parent.parentElement;
    }
  }
}

return '';
"""


def scrape_shop_display_name(dp: DpPage, *, login_username: str = "") -> str:
    """从已登录页面抓取店铺展示名；失败返回空字符串。"""
    try:
        if "login" in str(dp.url or "").lower():
            return ""
        name = str(dp.run_js(_SHOP_NAME_JS, str(login_username or "").strip()) or "").strip()
        if not name or len(name) > 40:
            return ""
        if login_username and name == login_username.strip():
            return ""
        return name
    except Exception:
        return ""


def maybe_refresh_shop_display_name(
    account_id: str,
    dp: DpPage,
    *,
    login_username: str = "",
) -> str:
    """抓取并缓存店铺展示名；已有缓存且未变则跳过写入。"""
    aid = str(account_id or "").strip()
    if not aid:
        return ""
    cached = get_cached_shop_display_name(aid)
    scraped = scrape_shop_display_name(dp, login_username=login_username)
    if scraped:
        if scraped != cached:
            update_shop_display_name(aid, scraped)
        return scraped
    return cached


@dataclass(frozen=True)
class ShopVerifyResult:
    ok: bool
    expected: str
    actual: str
    error: str = ""


def verify_shop_for_account(
    account_id: str,
    dp: DpPage,
    *,
    login_username: str = "",
) -> ShopVerifyResult:
    """
    校验浏览器当前登录店铺与 account_id 缓存的展示名一致。

    防止浏览器 profile 串店导致误下架其他店铺商品。
    """
    aid = str(account_id or "").strip()
    expected = get_cached_shop_display_name(aid)
    actual = maybe_refresh_shop_display_name(aid, dp, login_username=login_username)

    if not actual:
        return ShopVerifyResult(
            ok=False,
            expected=expected,
            actual="",
            error="shop_display_name_not_detected",
        )
    if expected and actual != expected:
        return ShopVerifyResult(
            ok=False,
            expected=expected,
            actual=actual,
            error="shop_display_name_mismatch",
        )
    return ShopVerifyResult(ok=True, expected=expected or actual, actual=actual)
