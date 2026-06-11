from src.workspace import WORKDIR

BASE_SYSTEM_PROMPT = f"""You are a coding agent at {WORKDIR}.
Use the task tool to delegate exploration or subtasks."""

# Backward-compatible alias
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def build_system_prompt(skill_descriptions: str | None = None) -> str:
    parts = [BASE_SYSTEM_PROMPT]
    if skill_descriptions:
        parts.extend([
            "",
            "Use load_skill to access specialized knowledge before tackling unfamiliar topics.",
            "",
            "Skills available:",
            skill_descriptions,
        ])
    return "\n".join(parts)
