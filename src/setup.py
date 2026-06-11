from pathlib import Path

from src.agent.base_agent import BaseAgent
from src.config.loader import load_config
from src.execution.subagent_executor import SubagentExecutor
from src.execution.subagent_factory import SubagentFactory
from src.execution.tool_executor import ToolExecutor
from src.logger.logger import JsonLogger
from src.model.AnthropicClient import AnthropicClient
from src.orchestrator.base_loop import BaseLoop
from src.plugins.manager import PluginManager
from src.registry.tool_registry import ToolRegistry
from src.runtime.resolver import RuntimePolicyEngine
from src.runtime.skill_loader import SkillLoader


def build_main_runtime(config=None):
    config = config if config is not None else load_config()

    registry = ToolRegistry()
    PluginManager(config).register_all(registry)

    executor_tm = registry.create_tool_manager()
    skill_loader = SkillLoader(Path(__file__).parent / "skills")
    runtime = RuntimePolicyEngine(registry, executor_tm, skill_loader, config)

    subagent_factory = SubagentFactory(registry)
    subagent_executor = SubagentExecutor(registry, subagent_factory)
    executor = ToolExecutor(executor_tm, subagent_executor)

    client = AnthropicClient()
    agent = BaseAgent(client=client)
    main_loop = BaseLoop(agent=agent, runtime=runtime, executor=executor)

    logger = JsonLogger()
    return main_loop, logger
