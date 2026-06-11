from src.tools.tool_manager import ToolManager
from src.logger.logger import log_message
from src.context.policy_context import PolicyContext


class PolicyLoop:
    def __init__(self, agent, tools: ToolManager, memory=None, policies=None):
        self.agent = agent
        self.tools = tools
        self.memory = memory
        self.policies = policies or []

    def loop(self, messages: list, logger=None):
        context = PolicyContext()
        context.messages = messages

        while True:
            context.round_idx += 1

            response = self.agent.run(messages, tools=self.tools)
            assistant_msg = {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            }
            messages.append(assistant_msg)
            log_message(logger, assistant_msg)

            if response.stop_reason != "tool_use":
                return

            context.tool_blocks = response.content

            for p in self.policies:
                if hasattr(p, "before_tool"):
                    context.tool_blocks = p.before_tool(context)

            results = []
            for block in context.tool_blocks:
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

            context.tool_results = results

            for p in self.policies:
                if hasattr(p, "after_tool"):
                    context.tool_results = p.after_tool(context)

            user_msg = {"role": "user", "content": context.tool_results}
            messages.append(user_msg)
            context.messages = messages
            log_message(logger, user_msg)

            for p in self.policies:
                if hasattr(p, "before_next_round"):
                    p.before_next_round(context)
