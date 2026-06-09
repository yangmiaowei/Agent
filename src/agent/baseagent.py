from src.model.AnthropicClient import AnthropicClient
from src.tools.tool_manager import ToolManager


class BaseAgent:
    def __init__(self, client: AnthropicClient):
        self.client = client

    def run(self, messages, input=None, tools: ToolManager = None, memory=None):
        return self.client.chat(messages, tools=tools)
