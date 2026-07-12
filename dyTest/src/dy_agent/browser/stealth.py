"""反自动化检测参数（骨架，后续可按抖店页面调优）。"""

STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
]

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""
