"""使用 LLM 将 Git 提交归纳为业务进展摘要。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from pdd_agent.core.config import get_env_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.git.digest import GitCommitRecord, commits_to_context
from pdd_agent.llm.factory import create_chat_model

logger = get_logger(__name__)

_SYSTEM_PROMPT = """你是技术开发日报助手。根据今日 Git 提交记录，归纳「今天交付了哪些功能/能力」。

核心原则：多个 commit 往往是在迭代同一个需求，必须合并，不要逐条复述 commit。

合并规则：
1. 同一功能域/同一需求的多次提交（初版、重构、补 API、加预览、加定时、改 DTO 等）→ 合并成 1 条
2. 只写最终交付的能力，不要写实现过程（如：加接口、重构、DTO、类型定义、配置文件更新、单元测试）
3. 不同业务域的功能才分开写（例如「商品属性」和「企业微信日报」是两条）
4. 全天通常 2~5 条即可；提交很多时也尽量控制在 5 条以内，只保留最重要的

输出格式：
1. 每行一条，不要编号、不要 Markdown、不要标题
2. 每条用简短中文，写「做了什么功能」，控制在 25 字以内
3. 禁止效果/价值后缀：不要写 提升xxx、方便xxx、提高xxx、优化用户体验 等
4. 不要 commit hash、文件路径、类名、函数名

合并示例（输入多条 wecom 相关 commit）：
❌ 错误（太碎）：
添加企业微信日报多平台支持
实现拼多多和淘宝日报生成
添加日报手动填写内容API
支持日报预览和发送功能
重构日报消息组装逻辑

✅ 正确（合并）：
企业微信日报功能（多平台预览、定时发送、手动填写）

风格参考：
erp上架标题用调用ai大模型生成
拼多多商品属性自动填写与管理功能
企业微信日报功能

若今日无有效提交，只输出一行：今日暂无代码提交
"""


_MAX_PROGRESS_LINES = 6


def _clean_progress_lines(content: str) -> list[str]:
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in lines:
        while line and line[0] in "-·•*":
            line = line[1:].lstrip()
        if line.startswith(("当日已完成", "技术项目进展")):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(line)
    return cleaned[:_MAX_PROGRESS_LINES]


def summarize_commits_as_progress(commits: list[GitCommitRecord]) -> str:
    """调用 LLM，将提交记录转为「当日已完成交付技术项目进展」条目。"""
    env = get_env_settings()
    if not env.llm_api_key:
        raise RuntimeError("未配置 LLM_API_KEY，请在 myTest/.env 中填写后重启后台")

    context = commits_to_context(commits)
    model = create_chat_model(temperature=0.1)
    logger.info("git digest llm summarize commits=%s", len(commits))
    resp = model.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "以下是今日全部 Git 提交。请按「功能/需求」合并归纳，"
                    "同一需求的多次 commit 只输出 1 条，全天控制在 2~5 条：\n\n"
                    f"{context}"
                )
            ),
        ]
    )
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    cleaned = _clean_progress_lines(content)
    return "\n".join(cleaned) if cleaned else "今日暂无代码提交"
