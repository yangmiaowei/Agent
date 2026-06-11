from dataclasses import dataclass

from src.execution.task_schema import build_task_schema
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.registry.tool_registry import ToolRegistry
from src.runtime.context import RuntimeContext
from src.runtime.skill_loader import SkillLoader
from src.runtime.tool_view import ToolView
from src.tools.tool_manager import ToolManager


@dataclass
class ResolvedRuntime:
    tool_view: ToolView
    system_prompt: str


class RuntimePolicyEngine:
    """Decide tool visibility and system prompt for each orchestrator round."""

    def __init__(
        self,
        registry: ToolRegistry,
        executor_tm: ToolManager,
        skill_loader: SkillLoader,
        config: dict,
    ):
        self._registry = registry
        self._executor_tm = executor_tm
        self._skill_loader = skill_loader
        self._config = config
        subagent_cfg = config.get("plugins", {}).get("subagent", {})
        self._subagent_enabled = subagent_cfg.get("enabled", True)

    def resolve(self, ctx: RuntimeContext) -> ResolvedRuntime:
        visible = set(self._registry.all_tool_names())
        extra_schemas: list[dict] = []

        if self._subagent_enabled and self._registry.has_subagent_types():
            visible.add("task")
            type_defs = self._registry.all_subagent_types()
            default_type = "full" if any(t.name == "full" for t in type_defs) else type_defs[0].name
            extra_schemas.append(build_task_schema(type_defs, default_type))

        tool_view = ToolView(self._executor_tm, visible, extra_schemas)
        system_prompt = self._build_system_prompt()
        return ResolvedRuntime(tool_view=tool_view, system_prompt=system_prompt)

    def _build_system_prompt(self) -> str:
        # Phase 1: equivalent to previous static prompt; skill injection in Phase 2.
        return SYSTEM_PROMPT
