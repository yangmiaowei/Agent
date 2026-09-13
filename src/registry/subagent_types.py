from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.registry.tool_registry import ToolRegistry


@dataclass
class SubagentTypeDef:
    name: str
    description: str
    tool_names: list[str]
    system_prompt: Optional[str] = None

    def resolve_tool_classes(self, registry: "ToolRegistry") -> list:
        classes = []
        for name in self.tool_names:
            cls = registry.get_tool_class(name)
            if cls is None:
                raise ValueError(f"Unknown tool '{name}' in subagent type '{self.name}'")
            classes.append(cls)
        return classes


DEFAULT_TYPES: dict[str, SubagentTypeDef] = {
    "read": SubagentTypeDef(
        name="read",
        description="Read-only: inspect and read files only",
        tool_names=["read_file"],
    ),
    "shell": SubagentTypeDef(
        name="shell",
        description="Shell: read, edit, write files and execute commands",
        tool_names=["bash", "edit_file", "read_file", "write_file"],
    ),
    "full": SubagentTypeDef(
        name="full",
        description="Full: all shell capabilities plus todo management",
        tool_names=["bash", "edit_file", "read_file", "write_file", "todo"],
    ),
}


def load_subagent_types(plugin_config: dict) -> list[SubagentTypeDef]:
    """Merge built-in and config-defined types; filter by enabled_types."""
    types: dict[str, SubagentTypeDef] = dict(DEFAULT_TYPES)

    for name, cfg in plugin_config.get("custom_types", {}).items():
        types[name] = SubagentTypeDef(
            name=name,
            description=cfg["description"],
            tool_names=cfg["tools"],
            system_prompt=cfg.get("system_prompt"),
        )

    enabled = plugin_config.get("enabled_types")
    if enabled is not None:
        unknown = set(enabled) - set(types)
        if unknown:
            raise ValueError(f"Unknown subagent types in enabled_types: {unknown}")
        return [types[name] for name in enabled]

    return list(types.values())
