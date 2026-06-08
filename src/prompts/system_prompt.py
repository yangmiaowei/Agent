from pathlib import Path

WORKDIR = Path.cwd()

SYSTEM_PROMPT =  f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."