"""LLM 工厂。"""

from langchain_openai import ChatOpenAI

from dy_agent.core.config import get_env_settings


def create_chat_model(*, model: str | None = None, temperature: float = 0) -> ChatOpenAI:
    env = get_env_settings()
    return ChatOpenAI(
        model=model or env.llm_model,
        api_key=env.llm_api_key or "not-set",
        base_url=env.llm_base_url,
        temperature=temperature,
    )


def create_orchestrator_model() -> ChatOpenAI:
    env = get_env_settings()
    return create_chat_model(model=env.orchestrator_model or env.llm_model)


def create_vision_model() -> ChatOpenAI:
    env = get_env_settings()
    return create_chat_model(model=getattr(env, "vision_model", None) or "glm-4v-flash")
