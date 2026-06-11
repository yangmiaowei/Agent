from src.plugins.base import Plugin, BuildContext
from src.subagent.registry import load_subagent_types, SubagentTypeDef
from src.tools.task import Task
from src.tools.tool_manager import ToolManager
from src.model.AnthropicClient import AnthropicClient
from src.agent.base_agent import BaseAgent
from src.runtime.subagent_loop import SubAgentLoop
from src.logger.logger import JsonLogger
from src.prompts.subagent_system_prompt import SUBAGENT_SYSTEM_PROMPT
from src.workspace import WORKDIR


def _register(tm: ToolManager, tool_classes):
    for cls in tool_classes:
        tm.register(cls)


def _build_subagent_runtime(type_def: SubagentTypeDef):
    sub_tm = ToolManager()
    _register(sub_tm, type_def.resolve_tool_classes())

    system = type_def.system_prompt or SUBAGENT_SYSTEM_PROMPT
    client = AnthropicClient(tools=sub_tm)
    agent = BaseAgent(client=client)
    sub_loop = SubAgentLoop(agent=agent, tools=sub_tm, system_prompt=system)
    sub_logger = JsonLogger(workdir=WORKDIR / "SubAgent" / type_def.name)
    return sub_loop, sub_logger


class SubagentPlugin(Plugin):
    name = "subagent"

    def setup(self, ctx: BuildContext, plugin_config: dict) -> None:
        type_defs = load_subagent_types(plugin_config)  # 把 subagent 类型加载出来
        if not type_defs:
            return

        runtimes = {t.name: _build_subagent_runtime(t) for t in type_defs}  # 把每个 subagent 变成“可运行对象”
        ctx.main_tm.register_instance(Task(runtimes, type_defs))  # 整个 subagent system 作为一个“任务实例”注册进主系统
