from src.workspace import get_workdir

def build_system_prompt(skill_descriptions: str | None = None) -> str:
    parts = [
        f"""You are a coding agent at {get_workdir()}.
Use the task tool to delegate exploration or subtasks."""
    ]
    if skill_descriptions:
        parts.extend([
            "",
            "Use load_skill to access specialized knowledge before tackling unfamiliar topics.",
            "",
            "Skills available:",
            skill_descriptions,
        ])
    return "\n".join(parts)
