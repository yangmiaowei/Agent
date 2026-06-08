class ToolManager:
    def __init__(self):
        self._tools = {}  # name -> tool instance

    def register(self, tool_cls):
        """
        动态注册工具（运行时也可以调用）
        """
        instance = tool_cls()
        name = instance.name

        if name in self._tools:
            raise ValueError(f"Tool conflict: {name}")

        self._tools[name] = instance
        return tool_cls

    def call(self, name: str, args: dict):
        """
        统一调用入口
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        return tool.run(**args)

    def list_tools(self):
        """
        给 LLM 用（tool schema / name）
        """
        return [
            {
                "name": t.name,
                "description": getattr(t, "description", ""),
                "input_schema": getattr(t, "input_schema", {})
            }
            for t in self._tools.values()
        ]


tool_manager = ToolManager()

def tool(cls):
    tool_manager.register(cls)
    return cls