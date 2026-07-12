"""领域异常。"""


class AgentError(Exception):
    """智能体编排层错误。"""


class BrowserError(Exception):
    """Playwright 浏览器操作错误。"""


class PreflightError(Exception):
    """上架前校验失败。"""
