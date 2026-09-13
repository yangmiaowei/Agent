from src.execution.subagent_factory import SubagentFactory
from src.registry.tool_registry import ToolRegistry
from src.runtime.context import RuntimeContext


class SubagentExecutor:
    def __init__(self, registry: ToolRegistry, factory: SubagentFactory):
        self._registry = registry
        self._factory = factory
        self._cache: dict[str, tuple] = {}

    def _default_type(self) -> str:
        type_defs = self._registry.all_subagent_types()
        if not type_defs:
            raise RuntimeError("No subagent types registered")
        if any(t.name == "full" for t in type_defs):
            return "full"
        return type_defs[0].name

    def run(self, args: dict, ctx: RuntimeContext) -> str:
        profile = args.get("subagent_type", self._default_type())
        type_def = self._registry.get_subagent_type(profile)
        if type_def is None:
            available = ", ".join(t.name for t in self._registry.all_subagent_types())
            return f"Error: Unknown or disabled subagent_type '{profile}'. Available: {available}"

        if profile not in self._cache:
            self._cache[profile] = self._factory.build(type_def)

        loop, logger = self._cache[profile]
        return loop.loop(prompt=args["prompt"], logger=logger)
