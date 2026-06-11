from src.tools.base_tool import BaseTool
from src.memory.todo_manager import TodoManager


class ToDo(BaseTool):
    name = "todo"
    description = "Update task list. Track progress on multi-step tasks."
    input_schema = {
        "type": "object", 
        "properties": {
            "items": {
                "type": "array", 
                "items": {
                    "type": "object", 
                    "properties": {
                        "id": {"type": "string"}, 
                        "text": {"type": "string"}, 
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                    }, 
                    "required": ["id", "text", "status"]}}}, 
        "required": ["items"]
    }

    def __init__(self):
        super().__init__()
        self._manager = TodoManager()  # 每个 tool 实例持有一份状态


    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        items = kwargs["items"]

        try:
            return self._manager.update(items)
        except Exception as e:
            return f"Error: {e}"