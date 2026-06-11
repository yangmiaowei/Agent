from src.tools.tool_manager import ToolManager
from src.logger.logger import log_message


class BaseLoop:
    def __init__(self, agent, tools: ToolManager, memory=None, policies=None):
        self.agent = agent
        self.tools = tools
        self.memory = memory
        self.policies = policies or []

    def loop(self, messages: list, logger=None):
        while True:
            response = self.agent.run(messages, tools=self.tools)
            assistant_msg = {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            }
            messages.append(assistant_msg)
            log_message(logger, assistant_msg)

            if response.stop_reason != "tool_use":
                return

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    try:
                        output = self.tools.call(block.name, block.input)
                    except Exception as e:
                        output = f"Error: {e}"
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output
                    })

            user_msg = {"role": "user", "content": results}
            messages.append(user_msg)
            log_message(logger, user_msg)