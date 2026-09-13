from src.workspace import get_workdir


def build_system_prompt(
    skill_descriptions: str | None = None,
    *,
    visible_tools: set[str] | None = None,
) -> str:
    """Build the system prompt.

    `visible_tools` is the set of tools actually exposed this round. Guidance for
    a tool is only emitted when that tool is callable, otherwise modes that hide
    tools (e.g. swe) instruct the model to use something it cannot see.
    """
    def available(name: str) -> bool:
        return visible_tools is None or name in visible_tools

    parts = [f"You are a coding agent at {get_workdir()}."]

    if available("task"):
        parts.append("Use the task tool to delegate exploration or subtasks.")

    if skill_descriptions and available("load_skill"):
        parts.extend([
            "",
            "Use load_skill to access specialized knowledge before tackling unfamiliar topics.",
            "",
            "Skills available:",
            skill_descriptions,
        ])

    return "\n".join(parts)
