from pathlib import Path

from src.agent.base_agent import BaseAgent
from src.config.loader import load_config
from src.execution.subagent_executor import SubagentExecutor
from src.execution.subagent_factory import SubagentFactory
from src.execution.tool_executor import ToolExecutor
from src.logger.logger import LogSession, is_test_context
from src.model.AnthropicClient import AnthropicClient
from src.orchestrator.base_loop import BaseLoop
from src.plugins.manager import PluginManager
from src.registry.tool_registry import ToolRegistry
from src.runtime.resolver import RuntimePolicyEngine
from src.runtime.skill_loader import SkillLoader
from src.tools.load_skill import LoadSkill


def build_main_runtime(config=None, *, log_session=None, test=None):
    config = config if config is not None else load_config()
    if test is None:
        test = is_test_context()

    log_session = log_session or LogSession.create(test=test)

    skill_loader = SkillLoader(Path(__file__).parent / "skills")
    LoadSkill.configure(skill_loader)

    registry = ToolRegistry()
    PluginManager(config).register_all(registry)  # 注册静态定义全集

    executor_tm = registry.create_tool_manager(log_session.events)  # 所有工具的执行入口
    runtime = RuntimePolicyEngine(registry, executor_tm, skill_loader, config)  # 可见性裁剪等策略设置

    subagent_factory = SubagentFactory(registry, log_session)  # 独立运行环境
    subagent_executor = SubagentExecutor(registry, subagent_factory)  # 触发 subagent 执行
    executor = ToolExecutor(executor_tm, subagent_executor)  # 执行 + 路由 + 子世界切换

    client = AnthropicClient()
    agent = BaseAgent(client=client)
    main_loop = BaseLoop(agent=agent, runtime=runtime, executor=executor)  # 每一轮对话循环

    return main_loop, log_session
