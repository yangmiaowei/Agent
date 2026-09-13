from src.workspace import get_workdir


def build_subagent_system_prompt() -> str:
    return f"""You are a coding subagent at {get_workdir()}.
Complete the given task, then summarize your findings."""


# Backward-compatible alias
SUBAGENT_SYSTEM_PROMPT = build_subagent_system_prompt()
