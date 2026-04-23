from Tools.datetime_tool import DatetimeTool
from Tools.search_tool import SearchTool


class Tools:
    def __init__(self):
        self.available_tools = {
            "search": SearchTool(),
            "datetime": DatetimeTool(),
        }
        self.toolConfig = self._get_tools_config()

    def _get_tools_config(self):
        return [
            {
                "name_for_human": tool.name_for_human,
                "name_for_model": tool.name_for_model,
                "description_for_model": tool.description_for_model,
                "parameters": tool.parameters,
            }
            for tool in self.available_tools.values()
        ]
    
    def run(self, tool_name: str, **kwargs):
        if tool_name not in self.available_tools:
            raise ValueError(f"未知工具: {tool_name}")
        return self.available_tools[tool_name].run(**kwargs)