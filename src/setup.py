from src.tools.bash import Bash
from src.tools.edit_file import EditFile
from src.tools.read_file import ReadFile
from src.tools.write_file import WriteFile
from src.tools.todo import ToDo
from src.tools.task import Task
from src.tools.tool_manager import ToolManager
from src.model.AnthropicClient import AnthropicClient
from src.agent.base_agent import BaseAgent
from src.runtime.base_loop import BaseLoop
from src.runtime.subagent_loop import SubAgentLoop
from src.logger.logger import JsonLogger
from src.workspace import WORKDIR

CORE_TOOLS = [Bash, EditFile, ReadFile, WriteFile, ToDo]
SUBAGENT_TOOLS = CORE_TOOLS


def _register(tm: ToolManager, tools):
    for t in tools:
        tm.register(t)


def _build_loop(tm: ToolManager, loop_cls):
    client = AnthropicClient(tools=tm)
    agent = BaseAgent(client=client)
    return loop_cls(agent=agent, tools=tm)


def build_main_runtime():
    sub_tm = ToolManager()
    _register(sub_tm, SUBAGENT_TOOLS)
    sub_loop = _build_loop(sub_tm, SubAgentLoop)
    sub_logger = JsonLogger(workdir=WORKDIR / "SubAgent")

    main_tm = ToolManager()
    _register(main_tm, CORE_TOOLS)
    main_tm.register_instance(Task(sub_loop, sub_logger))  # 把 subagent 运行时注入给 Task
    main_loop = _build_loop(main_tm, BaseLoop)
    logger = JsonLogger()
    return main_loop, logger
