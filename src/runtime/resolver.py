from dataclasses import dataclass

from src.execution.task_schema import build_task_schema
from src.prompts.system_prompt import build_system_prompt
from src.registry.subagent_types import SubagentTypeDef
from src.registry.tool_registry import ToolRegistry
from src.runtime.context import RuntimeContext
from src.runtime.skill_loader import SkillLoader
from src.runtime.tool_view import ToolView
from src.tools.bash_policy import policy_for_mode, set_bash_policy
from src.tools.tool_manager import ToolManager

SAFE_MODE_BLOCKED_TOOLS = frozenset({"bash", "edit_file", "write_file"})
SWE_MODE_BLOCKED_TOOLS = frozenset({"todo", "write_file", "load_skill", "task"})
READ_ONLY_TOOLS = frozenset({"read_file"})


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
        runtime_cfg = config.get("runtime", {})
        subagent_cfg = config.get("plugins", {}).get("subagent", {})

        self._default_mode = runtime_cfg.get("mode", "default")
        self._config_safe_mode = runtime_cfg.get("safe_mode", False)
        self._skills_enabled = runtime_cfg.get("skills_enabled", True)
        self._subagent_enabled = subagent_cfg.get("enabled", True)

    def resolve(self, ctx: RuntimeContext) -> ResolvedRuntime:
        mode = self._effective_mode(ctx)
        # Visibility is not enough for bash: it stays available in swe mode but
        # must not be allowed to mutate the host environment.
        set_bash_policy(policy_for_mode(mode))
        visible = self._resolve_visible_tools(ctx, mode)
        extra_schemas = self._resolve_extra_schemas(mode, visible)

        tool_view = ToolView(self._executor_tm, visible, extra_schemas)
        # Built after extra schemas so `visible` reflects the final tool set.
        system_prompt = self._build_system_prompt(visible)
        return ResolvedRuntime(tool_view=tool_view, system_prompt=system_prompt)

    def _effective_mode(self, ctx: RuntimeContext) -> str:
        if ctx.mode != "default":
            return ctx.mode
        if self._config_safe_mode:
            return "safe"
        return self._default_mode

    def _resolve_visible_tools(self, ctx: RuntimeContext, mode: str) -> set[str]:
        visible = set(self._registry.all_tool_names())

        if mode == "safe":
            visible -= SAFE_MODE_BLOCKED_TOOLS
        elif mode == "swe":
            visible -= SWE_MODE_BLOCKED_TOOLS

        if not self._skills_enabled or not self._skill_loader.skills:
            visible.discard("load_skill")

        return visible

    def _resolve_extra_schemas(self, mode: str, visible: set[str]) -> list[dict]:
        if not self._subagent_enabled or not self._registry.has_subagent_types():
            return []

        type_defs = self._filter_subagent_types(mode)
        if not type_defs:
            visible.discard("task")
            return []

        visible.add("task")
        default_type = "full" if any(t.name == "full" for t in type_defs) else type_defs[0].name
        return [build_task_schema(type_defs, default_type)]

    def _filter_subagent_types(self, mode: str) -> list[SubagentTypeDef]:
        type_defs = self._registry.all_subagent_types()
        if mode != "safe":
            return type_defs
        return [
            t for t in type_defs
            if set(t.tool_names).issubset(READ_ONLY_TOOLS)
        ]

    def _build_system_prompt(self, visible: set[str]) -> str:
        skill_descriptions = None
        if (
            self._skills_enabled
            and "load_skill" in visible
            and self._skill_loader.skills
        ):
            skill_descriptions = self._skill_loader.get_descriptions()
        return build_system_prompt(skill_descriptions, visible_tools=visible)
