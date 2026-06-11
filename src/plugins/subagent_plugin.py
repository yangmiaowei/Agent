from src.plugins.base import Plugin
from src.registry.subagent_types import load_subagent_types
from src.registry.tool_registry import ToolRegistry


class SubagentPlugin(Plugin):
    name = "subagent"

    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        for type_def in load_subagent_types(plugin_config):
            registry.add_subagent_type(type_def)
