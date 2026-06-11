from src.agent.base_agent import BaseAgent
from src.logger.logger import JsonLogger
from src.model.AnthropicClient import AnthropicClient
from src.prompts.subagent_system_prompt import SUBAGENT_SYSTEM_PROMPT
from src.registry.subagent_types import SubagentTypeDef
from src.registry.tool_registry import ToolRegistry
from src.runtime.subagent_loop import SubAgentLoop
from src.tools.tool_manager import ToolManager
from src.workspace import WORKDIR


class SubagentFactory:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def build(self, type_def: SubagentTypeDef) -> tuple[SubAgentLoop, JsonLogger]:
        sub_tm = ToolManager()
        for cls in type_def.resolve_tool_classes(self._registry):
            sub_tm.register(cls)

        system = type_def.system_prompt or SUBAGENT_SYSTEM_PROMPT
        client = AnthropicClient()
        agent = BaseAgent(client=client)
        sub_loop = SubAgentLoop(agent=agent, tools=sub_tm, system_prompt=system)
        sub_logger = JsonLogger(workdir=WORKDIR / "SubAgent" / type_def.name)
        return sub_loop, sub_logger
