from src.plugins.base import Plugin
from src.registry.tool_registry import ToolRegistry
from src.tools.load_skill import LoadSkill


class SkillsPlugin(Plugin):
    name = "skills"

    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        registry.add_tool(LoadSkill)
