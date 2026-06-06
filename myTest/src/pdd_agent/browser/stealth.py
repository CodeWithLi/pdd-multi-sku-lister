"""降低 Playwright 自动化特征（无法保证 100% 绕过风控，但比裸 Chromium 更接近真人浏览器）。"""

# 在页面 JS 执行前注入，隐藏常见自动化标记
STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  if (!window.chrome) {
    window.chrome = { runtime: {} };
  }

  const originalQuery = window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
      parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
  }

  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
  });

  Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en'],
  });
})();
"""

# launch_persistent_context 启动参数
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]
