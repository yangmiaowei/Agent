from src.registry.subagent_types import SubagentTypeDef
from src.tools.tool_manager import ToolManager


class ToolRegistry:
    """Static catalog of all tool classes and subagent type declarations."""

    def __init__(self):
        self._tool_classes: dict[str, type] = {}
        self._subagent_types: dict[str, SubagentTypeDef] = {}

    def add_tool(self, tool_cls: type) -> type:
        instance = tool_cls()
        name = instance.name
        if name in self._tool_classes:
            raise ValueError(f"Tool conflict: {name}")
        self._tool_classes[name] = tool_cls
        return tool_cls

    def add_subagent_type(self, type_def: SubagentTypeDef) -> None:
        if type_def.name in self._subagent_types:
            raise ValueError(f"Subagent type conflict: {type_def.name}")
        self._subagent_types[type_def.name] = type_def

    def get_tool_class(self, name: str) -> type | None:
        return self._tool_classes.get(name)

    def all_tool_classes(self) -> list[type]:
        return list(self._tool_classes.values())

    def all_tool_names(self) -> list[str]:
        return list(self._tool_classes.keys())

    def all_subagent_types(self) -> list[SubagentTypeDef]:
        return list(self._subagent_types.values())

    def get_subagent_type(self, name: str) -> SubagentTypeDef | None:
        return self._subagent_types.get(name)

    def has_subagent_types(self) -> bool:
        return bool(self._subagent_types)

    def create_tool_manager(self) -> ToolManager:
        tm = ToolManager()
        for cls in self._tool_classes.values():
            tm.register(cls)
        return tm
