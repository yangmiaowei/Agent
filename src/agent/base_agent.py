from src.model.AnthropicClient import AnthropicClient


class BaseAgent:
    def __init__(self, client: AnthropicClient):
        self.client = client

    def run(self, messages, input=None, tools=None, memory=None, system=None):
        return self.client.chat(messages, tools=tools, system=system)
