"""Skill 抽象与注册表：将业务能力暴露为 LangChain Tool。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool


class Skill(ABC):
    """
    可挂载到 LangGraph 的业务能力单元。
    实现 as_tool() 后 Agent 可通过 Tool Calling 或直接 invoke 调用。
    """

    name: str
    description: str

    @abstractmethod
    def as_tool(self) -> BaseTool:
        raise NotImplementedError


class SkillRegistry:
    """集中管理 Skill，便于 Orchestrator 一次性绑定 tools。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def as_tools(self) -> list[BaseTool]:
        """转为 LangChain Tool 列表，供 bind_tools 使用。"""
        return [s.as_tool() for s in self._skills.values()]


def tool_from_callable(name: str, description: str, fn: Any) -> StructuredTool:
    """快捷：把普通函数包装为 StructuredTool。"""
    return StructuredTool.from_function(name=name, description=description, func=fn)
