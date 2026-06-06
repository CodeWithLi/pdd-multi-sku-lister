"""LLM 工厂：统一创建 LangChain ChatOpenAI 实例。"""

from langchain_openai import ChatOpenAI

from pdd_agent.core.config import get_env_settings


def create_chat_model(*, model: str | None = None, temperature: float = 0) -> ChatOpenAI:
    """创建通用对话模型；兼容 OpenAI API 格式的厂商端点。"""
    env = get_env_settings()
    return ChatOpenAI(
        model=model or env.llm_model,
        api_key=env.llm_api_key or "not-set",
        base_url=env.llm_base_url,
        temperature=temperature,
    )


def create_orchestrator_model() -> ChatOpenAI:
    """Orchestrator 可用独立模型；未配置时回退到 llm_model。"""
    env = get_env_settings()
    return create_chat_model(model=env.orchestrator_model or env.llm_model)
