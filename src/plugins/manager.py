from src.plugins.base import BuildContext, Plugin
from src.plugins.subagent_plugin import SubagentPlugin
from src.subagent.registry import CORE_TOOL_CLASSES
from src.tools.tool_manager import ToolManager
from src.config.loader import load_config

PLUGINS: dict[str, Plugin] = {
    "subagent": SubagentPlugin(),
}


class PluginManager:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def setup_all(self, main_tm: ToolManager) -> None:
        ctx = BuildContext(
            main_tm=main_tm,
            core_tools=CORE_TOOL_CLASSES,
            config=self.config,
        )
        for name, plugin in PLUGINS.items():
            plugin_config = self.config.get("plugins", {}).get(name, {})
            if not plugin_config.get("enabled", True):
                continue
            plugin.setup(ctx, plugin_config)
