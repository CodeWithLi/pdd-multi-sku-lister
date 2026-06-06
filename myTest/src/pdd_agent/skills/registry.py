"""默认 Skill 注册表：启动时注册 listing 相关 Tool。"""

from pdd_agent.skills.base import SkillRegistry
from pdd_agent.skills.listing.catalog import CatalogSkill
from pdd_agent.skills.listing.preflight import PreflightSkill


def build_default_registry() -> SkillRegistry:
    """构建含目录解析、上架校验的默认 Skill 集合。"""
    registry = SkillRegistry()
    registry.register(CatalogSkill())
    registry.register(PreflightSkill())
    return registry
