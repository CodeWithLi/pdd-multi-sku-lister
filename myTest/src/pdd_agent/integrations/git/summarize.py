"""使用 LLM 将 Git 提交归纳为业务进展摘要。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from pdd_agent.core.config import get_env_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.git.digest import GitCommitRecord, commits_to_context
from pdd_agent.llm.factory import create_chat_model

logger = get_logger(__name__)

_SYSTEM_PROMPT = """你是技术开发日报助手。根据今日 Git 提交记录，列出今天实际完成了哪些开发工作。

输出要求：
1. 只输出工作条目，每行一条，不要编号、不要 Markdown、不要标题
2. 每条只写「做了什么」，用简短中文动宾短语或短句，控制在 20 字以内为佳
3. 禁止写效果、价值、目的类后缀，例如不要出现：提升xxx、方便xxx、提高xxx、优化用户体验、增强xxx效率 等
4. 合并同类项，提炼成少量高层工作项，不要把 commit 正文里的每个子 bullet 都单独列一行
5. 避免 commit hash、源码路径、类名、函数名等技术细节
6. 风格参考（只写做了什么，不加后半句）：
erp上架标题用调用ai大模型生成
erp多店铺 多规格的测试
拼多多商品属性自动填写功能
商品属性管理功能
7. 若今日无有效提交，只输出一行：今日暂无代码提交
"""


def summarize_commits_as_progress(commits: list[GitCommitRecord]) -> str:
    """调用 LLM，将提交记录转为「当日已完成交付技术项目进展」条目。"""
    env = get_env_settings()
    if not env.llm_api_key:
        raise RuntimeError("未配置 LLM_API_KEY，请在 myTest/.env 中填写后重启后台")

    context = commits_to_context(commits)
    model = create_chat_model(temperature=0.2)
    logger.info("git digest llm summarize commits=%s", len(commits))
    resp = model.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "请根据以下今日 Git 提交记录，列出今天完成了哪些开发工作（只写做了什么，不要写效果或价值）：\n\n"
                    f"{context}"
                )
            ),
        ]
    )
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    # 去掉 LLM 可能带出的列表符号
    cleaned = []
    for line in lines:
        while line and line[0] in "-·•*":
            line = line[1:].lstrip()
        if line.startswith(("当日已完成", "技术项目进展")):
            continue
        cleaned.append(line)
    return "\n".join(cleaned) if cleaned else "今日暂无代码提交"
