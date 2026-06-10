from src.tools.base_tool import BaseTool


class Task(BaseTool):
    name = "task"
    description = "Spawn a subagent with fresh context. It shares the filesystem but not conversation history."
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "description": {
                "type": "string",
                "description": "Short description of the task"
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

        try:
            return self._loop.loop(prompt=kwargs["prompt"], logger=self._logger)
        except Exception as e:
            return f"Error: {e}"
