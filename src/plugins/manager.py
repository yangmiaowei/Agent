from src.plugins.base import Plugin
from src.plugins.core_tools_plugin import CoreToolsPlugin
from src.plugins.subagent_plugin import SubagentPlugin
from src.registry.tool_registry import ToolRegistry
from src.config.loader import load_config

OPTIONAL_PLUGINS: dict[str, Plugin] = {
    "subagent": SubagentPlugin(),
}


class PluginManager:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def register_all(self, registry: ToolRegistry) -> None:
        CoreToolsPlugin().register(registry, {})

        for name, plugin in OPTIONAL_PLUGINS.items():
            plugin_config = self.config.get("plugins", {}).get(name, {})
            if not plugin_config.get("enabled", True):
                continue
            plugin.register(registry, plugin_config)
