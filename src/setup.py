from src.tools.bash import Bash
from src.tools.edit_file import EditFile
from src.tools.read_file import ReadFile
from src.tools.write_file import WriteFile
from src.tools.todo import ToDo
from src.tools.tool_manager import ToolManager
from src.model.AnthropicClient import AnthropicClient
from src.agent.base_agent import BaseAgent
from src.runtime.base_loop import BaseLoop
from src.plugins.manager import PluginManager

CORE_TOOLS = [Bash, EditFile, ReadFile, WriteFile, ToDo]


def _register(tm: ToolManager, tools):
    for t in tools:
        tm.register(t)


def _build_loop(tm: ToolManager, loop_cls):
    client = AnthropicClient(tools=tm)
    agent = BaseAgent(client=client)
    return loop_cls(agent=agent, tools=tm)


def build_main_runtime(config=None):
    main_tm = ToolManager()
    _register(main_tm, CORE_TOOLS)

    PluginManager(config).setup_all(main_tm)

    main_loop = _build_loop(main_tm, BaseLoop)
    from src.logger.logger import JsonLogger
    logger = JsonLogger()
    return main_loop, logger
