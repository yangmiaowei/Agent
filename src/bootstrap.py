from tool_manager import ToolManager

from tools.bash import BashTool
from tools.edit import EditTool
from tools.search import SearchTool


def init_tools(tool_manager: ToolManager):
    tool_manager.register(BashTool)
    tool_manager.register(EditTool)
    tool_manager.register(SearchTool)