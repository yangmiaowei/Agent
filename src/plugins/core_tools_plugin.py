from src.plugins.base import Plugin
from src.registry.tool_registry import ToolRegistry
from src.tools.bash import Bash
from src.tools.edit_file import EditFile
from src.tools.read_file import ReadFile
from src.tools.write_file import WriteFile
from src.tools.todo import ToDo

CORE_TOOL_CLASSES = [Bash, EditFile, ReadFile, WriteFile, ToDo]


class CoreToolsPlugin(Plugin):
    name = "core_tools"

    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        for cls in CORE_TOOL_CLASSES:
            registry.add_tool(cls)
