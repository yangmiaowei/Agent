from src.tools.tool_manager import ToolManager
from src.tools.bash import Bash
from src.tools.edit_file import EditFile
from src.tools.read_file import ReadFile
from src.tools.write_file import WriteFile
from src.tools.todo import ToDo


def init_tools(tool_manager: ToolManager):
    tool_manager.register(Bash)
    tool_manager.register(EditFile)
    tool_manager.register(ReadFile)
    tool_manager.register(WriteFile)
    tool_manager.register(ToDo)
