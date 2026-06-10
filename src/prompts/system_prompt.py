from pathlib import Path

WORKDIR = Path.cwd() / "WORKDIR"

SYSTEM_PROMPT = f"""You are a coding agent at {WORKDIR}. 
Use the task tool to delegate exploration or subtasks."""