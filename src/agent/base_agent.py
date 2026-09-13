from src.model.AnthropicClient import AnthropicClient


class BaseAgent:
    def __init__(self, client: AnthropicClient):
        self.client = client

    def run(self, messages, input=None, tools=None, memory=None, system=None):
        return self.client.chat(messages, tools=tools, system=system)

    @property
    def last_usage(self):
        """Token usage of the most recent call, or None if the client tracks none."""
        return getattr(self.client, "last_usage", None)

    @property
    def total_usage(self):
        """Cumulative token usage across this client's lifetime."""
        return getattr(self.client, "usage", None)
