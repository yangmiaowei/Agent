from src.runtime import subagent_loop
from src.tools.base_tool import BaseTool


class Task(BaseTool):
    name = "task"
    description = "Spawn a subagent with fresh context. It shares the filesystem but not conversation history."
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string"
            },
            "description": {
                "type": "string",
                "description": "Short description of the task"
            },
            "subagent_type": {
                "type": "string",
                "description":  (
                    "Tool profile for the subagent. "
                    "'read' can only inspect and read files. "
                    "'shell' can read, edit, write files and execute shell commands. "
                    "'full' includes all shell capabilities plus todo management."
                ),
                "enum": [
                    "read",
                    "shell",
                    "full",
                ],
            }
        },
        "required": ["prompt"]
    }

    def __init__(self, subagent_loop, logger):
        super().__init__()
        self._loop = subagent_loop
        self._logger = logger

    def run(self, **kwargs) -> str:
        self.validate(kwargs)
        
        profile = kwargs.get("subagent_type", "full")

        try:
            subagent_loop, subagent_logger = self._runtime[profile]
            return self._loop.loop(prompt=kwargs["prompt"], logger=self._logger)
        except Exception as e:
            return f"Error: {e}"
