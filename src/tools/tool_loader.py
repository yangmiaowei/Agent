from src.bootstrap import init_tools, init_subagent_tools
from src.tools.tool_manager import ToolManager


def load_all_tools(tool_manager: ToolManager):
    init_tools(tool_manager)

def load_subagent_tools(tool_manager: ToolManager):
    init_subagent_tools(tool_manager)