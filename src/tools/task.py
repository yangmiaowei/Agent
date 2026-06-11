from src.tools.base_tool import BaseTool
from src.subagent.registry import SubagentTypeDef


def _build_description(type_defs: list[SubagentTypeDef]) -> str:
    lines = [
        "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
        "",
        "Available subagent types:",
    ]
    for t in type_defs:
        lines.append(f"- {t.name}: {t.description}")
    return "\n".join(lines)


def _build_schema(type_defs: list[SubagentTypeDef], default_type: str) -> dict:
    type_names = [t.name for t in type_defs]
    type_desc = "; ".join(f"'{t.name}' — {t.description}" for t in type_defs)
    return {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed instructions for the subagent",
            },
            "description": {
                "type": "string",
                "description": "Short description of the task",
            },
            "subagent_type": {
                "type": "string",
                "description": (
                    f"Tool profile for the subagent. Defaults to '{default_type}'. "
                    f"Options: {type_desc}"
                ),
                "enum": type_names,
            },
        },
        "required": ["prompt"],
    }


class Task(BaseTool):
    name = "task"

    def __init__(self, runtimes: dict, type_defs: list[SubagentTypeDef]):
        self._runtimes = runtimes
        self._type_defs = type_defs
        self._default_type = "full" if "full" in runtimes else next(iter(runtimes))
        self.description = _build_description(type_defs)
        self.input_schema = _build_schema(type_defs, self._default_type)
        super().__init__()

    def run(self, **kwargs) -> str:
        self.validate(kwargs)

        profile = kwargs.get("subagent_type", self._default_type)
        if profile not in self._runtimes:
            available = ", ".join(self._runtimes)
            return f"Error: Unknown or disabled subagent_type '{profile}'. Available: {available}"

        loop, logger = self._runtimes[profile]
        return loop.loop(prompt=kwargs["prompt"], logger=logger)
