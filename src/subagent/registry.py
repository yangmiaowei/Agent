from dataclasses import dataclass, field
from typing import Optional

from src.tools.bash import Bash
from src.tools.edit_file import EditFile
from src.tools.read_file import ReadFile
from src.tools.write_file import WriteFile
from src.tools.todo import ToDo

CORE_TOOL_CLASSES = [Bash, EditFile, ReadFile, WriteFile, ToDo]
TOOL_CLASS_BY_NAME = {cls().name: cls for cls in CORE_TOOL_CLASSES}


@dataclass
class SubagentTypeDef:
    name: str
    description: str
    tool_names: list[str]
    system_prompt: Optional[str] = None

    def resolve_tool_classes(self) -> list:
        classes = []
        for name in self.tool_names:
            cls = TOOL_CLASS_BY_NAME.get(name)
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
