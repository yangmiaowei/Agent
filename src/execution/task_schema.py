from src.registry.subagent_types import SubagentTypeDef


def build_task_description(type_defs: list[SubagentTypeDef]) -> str:
    lines = [
        "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
        "",
        "Available subagent types:",
    ]
    for t in type_defs:
        lines.append(f"- {t.name}: {t.description}")
    return "\n".join(lines)


def build_task_schema(type_defs: list[SubagentTypeDef], default_type: str) -> dict:
    type_names = [t.name for t in type_defs]
    type_desc = "; ".join(f"'{t.name}' — {t.description}" for t in type_defs)
    return {
        "name": "task",
        "description": build_task_description(type_defs),
        "input_schema": {
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
        },
    }
