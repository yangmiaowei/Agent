from src.model.AnthropicClient import client


class BaseAgent:
    def __init__(self):
        pass

    def run(self, messages, input=None, tools=None, memory=None):
        return client.chat(messages)

agent = BaseAgent()