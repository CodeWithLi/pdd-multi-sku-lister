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


def create_chat_model_with_runtime(
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0,
) -> ChatOpenAI:
    """按运行时配置创建模型（用于可热切换厂商/模型场景）。"""
    return ChatOpenAI(
        model=str(model or "").strip(),
        api_key=str(api_key or "").strip() or "not-set",
        base_url=str(base_url or "").strip() or None,
        temperature=temperature,
    )


def create_orchestrator_model() -> ChatOpenAI:
    """Orchestrator 可用独立模型；未配置时回退到 llm_model。"""
    env = get_env_settings()
    return create_chat_model(model=env.orchestrator_model or env.llm_model)


def create_vision_model() -> ChatOpenAI:
    """视觉识别模型（款式颜色）；未配置 vision_model 时用 glm-4v-flash。"""
    env = get_env_settings()
    return create_chat_model(model=env.vision_model or "glm-4v-flash")
