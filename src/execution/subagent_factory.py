from src.agent.base_agent import BaseAgent
from src.logger.logger import LogSession, SessionEventWriter
from src.model.AnthropicClient import AnthropicClient
from src.prompts.subagent_system_prompt import SUBAGENT_SYSTEM_PROMPT
from src.registry.subagent_types import SubagentTypeDef
from src.registry.tool_registry import ToolRegistry
from src.runtime.subagent_loop import SubAgentLoop
from src.tools.tool_manager import ToolManager


class SubagentFactory:
    def __init__(self, registry: ToolRegistry, log_session: LogSession):
        self._registry = registry
        self._log_session = log_session

    def build(self, type_def: SubagentTypeDef) -> tuple[SubAgentLoop, SessionEventWriter]:
        sub_session = self._log_session.subsession(type_def.name)
        sub_tm = ToolManager(logger=sub_session.events)
        for cls in type_def.resolve_tool_classes(self._registry):
            sub_tm.register(cls)

        system = type_def.system_prompt or SUBAGENT_SYSTEM_PROMPT
        client = AnthropicClient()
        agent = BaseAgent(client=client)
        sub_loop = SubAgentLoop(agent=agent, tools=sub_tm, system_prompt=system)
        return sub_loop, sub_session.events
