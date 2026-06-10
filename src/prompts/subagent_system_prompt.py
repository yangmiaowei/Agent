from pathlib import Path

WORKDIR = Path.cwd() / "WORKDIR"

SUBAGENT_SYSTEM_PROMPT = f"""You are a coding subagent at {WORKDIR}. 
Complete the given task, then summarize your findings."""