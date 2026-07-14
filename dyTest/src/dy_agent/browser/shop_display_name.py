"""从抖店商家后台页面读取店铺展示名。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from dy_agent.db.repositories import get_cached_shop_display_name, update_shop_display_name
from dy_agent.db.session import is_database_available

if TYPE_CHECKING:
    from dy_agent.browser.sync_login import DpPage

# 黑名单：顶栏入口/工具文案，避免把「精选联盟」等当成店铺名
_SHOP_NAME_BLOCKLIST = (
    "退出",
    "登录",
    "设置",
    "消息",
    "帮助",
    "商家后台",
    "抖店",
    "首页",
    "商品发布",
    "工作台",
    "精选联盟",
    "巨量千川",
    "电商罗盘",
    "罗盘",
    "学习中心",
    "服务市场",
    "体验分",
    "客服",
    "公告",
    "智能助理",
    "AI助手",
    "成长中心",
    "抖音商城",
    "商品管理",
    "订单管理",
    "售后",
    "数据",
    "营销",
    "资金",
    "切换店铺",
    "全部功能",
    "搜索",
    "查询",
)

_SHOP_NAME_JS = """
(payload) => {
  const phoneHint = String((payload && payload.phoneHint) || '').trim();
  const blocklist = Array.isArray(payload && payload.blocklist) ? payload.blocklist : [];
  const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);

  function clean(t) {
    return String(t || '').replace(/\\s+/g, ' ').trim();
  }
  function blocked(t) {
    const s = clean(t);
    if (!s) return true;
    for (const bad of blocklist) {
      if (!bad) continue;
      if (s === bad || s.includes(bad)) return true;
    }
    return false;
  }
  function shopLike(t) {
    const s = clean(t);
    if (!s || s.length < 2 || s.length > 40) return false;
    if (phoneHint && s === phoneHint) return false;
    if (/^1\\d{10}$/.test(s)) return false;
    if (blocked(s)) return false;
    // 顶栏工具类常见截断文案（精选联盟供应…）
    if (/[…]|\\.\\.\\.$/.test(s) && /(联盟|千川|罗盘|供应|助手|市场)/.test(s)) return false;
    return /[\\u4e00-\\u9fffA-Za-z0-9]/.test(s);
  }
  function classHint(el) {
    const cls = String((el && (el.className || el.getAttribute && el.getAttribute('class'))) || '').toLowerCase();
    const id = String((el && el.id) || '').toLowerCase();
    return `${cls} ${id}`;
  }
  function scoreCandidate(text, el) {
    let score = 10;
    const hint = classHint(el);
    if (/(shop|store|mall|商家|店铺)/.test(hint)) score += 40;
    if (/(avatar|user|account|profile|header-right|right)/.test(hint)) score += 20;
    if (/(alliance|buyin|qianchuan|compass|menu|nav|tab|btn|button)/.test(hint)) score -= 50;
    try {
      const rect = el.getBoundingClientRect();
      if (rect.top >= 0 && rect.top <= 120) score += 8;
      // 店铺名一般在右上角账号区，而非左/中部工具入口
      if (vw > 0 && rect.left > vw * 0.55) score += 25;
      if (vw > 0 && rect.left < vw * 0.45) score -= 20;
    } catch (e) {}
    // 过短的菜单词降分
    if (text.length <= 3) score -= 5;
    return score;
  }
  function pushCandidate(out, text, el) {
    const s = clean(text);
    if (!shopLike(s)) return;
    out.push({ text: s, score: scoreCandidate(s, el || document.body) });
  }

  // 1) 页面全局状态里的 shopName
  const stateKeys = ['__INITIAL_STATE__', '__NEXT_DATA__', 'rawData', '__NUXT__', '__STORE__'];
  for (const key of stateKeys) {
    try {
      const st = window[key];
      if (!st) continue;
      const json = JSON.stringify(st);
      const patterns = [
        /"(?:shopName|shop_name|storeName|store_name|mallName|mall_name|shop_title|shopTitle)"\\s*:\\s*"([^"]+)"/g,
      ];
      for (const re of patterns) {
        let m;
        while ((m = re.exec(json)) !== null) {
          if (m[1] && shopLike(m[1])) return m[1];
        }
      }
    } catch (e) {}
  }

  // 2) 优先用明确选择器（账号区）
  const preferredSelectors = [
    '[class*="shopName"]',
    '[class*="shop-name"]',
    '[class*="ShopName"]',
    '[class*="storeName"]',
    '[class*="mallName"]',
    '[class*="shop_name"]',
    '[class*="header"] [class*="shop"]',
    '[class*="Header"] [class*="shop"]',
    '[class*="avatar"] + *',
    '[class*="Avatar"] + *',
    '[class*="userInfo"]',
    '[class*="UserInfo"]',
    '[class*="accountInfo"]',
    '[class*="AccountInfo"]',
  ];
  for (const sel of preferredSelectors) {
    try {
      const nodes = document.querySelectorAll(sel);
      for (const node of nodes) {
        const text = clean(node.innerText || node.textContent);
        if (!text || text.length > 80) continue;
        const first = text.split('\\n').map(clean).filter(Boolean)[0] || '';
        if (shopLike(first)) return first;
      }
    } catch (e) {}
  }

  // 3) 扫描顶栏，给候选项打分，取右上角高分项（避开左/中工具入口）
  const roots = document.querySelectorAll(
    'header, [class*="header"], [class*="Header"], [class*="top-bar"], [class*="TopBar"], [class*="nav"], [class*="Navbar"]'
  );
  const scanRoots = roots.length ? Array.from(roots) : [document.body];
  const candidates = [];
  for (const root of scanRoots) {
    const nodes = root.querySelectorAll('span, div, p, a, button');
    for (const node of nodes) {
      const rect = node.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.top > 160) continue;
      const text = clean(node.innerText || node.textContent);
      if (!text || text.length > 80) continue;
      const lines = text.split('\\n').map(clean).filter(Boolean);
      if (!lines.length) continue;
      // 多行时优先短行（店铺名常单独一行，下面对手机号）
      for (const line of lines.slice(0, 3)) {
        pushCandidate(candidates, line, node);
      }
    }
  }
  if (candidates.length) {
    candidates.sort((a, b) => b.score - a.score || b.text.length - a.text.length);
    if (candidates[0].score >= 15) return candidates[0].text;
  }
  return '';
}
"""


def is_invalid_shop_display_name(name: str) -> bool:
    """是否为顶栏工具文案等非店铺名。"""
    text = str(name or "").strip()
    if not text:
        return True
    if len(text) > 40:
        return True
    for bad in _SHOP_NAME_BLOCKLIST:
        if bad and (text == bad or bad in text):
            return True
    if ("…" in text or text.endswith("...")) and any(
        token in text for token in ("联盟", "千川", "罗盘", "供应", "助手", "市场")
    ):
        return True
    return False


def get_valid_shop_display_name(account_id: str) -> str:
    """读取缓存店铺名；若是黑名单无效值则清空并返回空串。"""
    if not is_database_available():
        return ""
    name = get_cached_shop_display_name(account_id)
    if not name:
        return ""
    if is_invalid_shop_display_name(name):
        try:
            update_shop_display_name(account_id, "")
            print(f"[{account_id}] 已清除无效店铺名缓存: {name}", flush=True)
        except Exception:
            pass
        return ""
    return name


def scrape_shop_display_name(dp: DpPage, *, login_phone: str = "") -> str:
    try:
        page = dp.raw
        if "login" in str(dp.url or "").lower():
            return ""
        name = str(
            page.evaluate(
                _SHOP_NAME_JS,
                {
                    "phoneHint": str(login_phone or "").strip(),
                    "blocklist": list(_SHOP_NAME_BLOCKLIST),
                },
            )
            or ""
        ).strip()
        if not name or len(name) > 40:
            return ""
        if login_phone and name == login_phone.strip():
            return ""
        if is_invalid_shop_display_name(name):
            return ""
        return name
    except Exception:
        return ""


def maybe_refresh_shop_display_name(
    account_id: str,
    dp: DpPage,
    *,
    login_phone: str = "",
) -> str:
    cached = get_valid_shop_display_name(account_id) if is_database_available() else ""

    name = scrape_shop_display_name(dp, login_phone=login_phone)
    if not name:
        return cached
    if cached == name:
        return name
    update_shop_display_name(account_id, name)
    print(f"[{account_id}] 店铺名已更新: {name}", flush=True)
    time.sleep(0.3)
    return name


def refresh_shop_display_name(account_id: str, dp: DpPage, *, login_phone: str = "") -> str:
    name = scrape_shop_display_name(dp, login_phone=login_phone)
    if name:
        update_shop_display_name(account_id, name)
        print(f"[{account_id}] 店铺名已强制刷新: {name}", flush=True)
    return name or get_valid_shop_display_name(account_id)
