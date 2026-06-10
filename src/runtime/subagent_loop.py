from src.tools.tool_manager import ToolManager
from src.logger.logger import log_message

# -- Subagent: fresh context, filtered tools, summary-only return --
class SubAgentLoop:
    def __init__(self, agent, tools: ToolManager, memory=None, policies=None):
        self.agent = agent
        self.tools = tools
        self.memory = memory
        self.policies = policies or []

    def loop(self, prompt: str, logger=None):
        sub_messages = [{"role": "user", "content": prompt}]  # fresh context
        for _ in range(30):  # safety limit
            response = self.agent.run(sub_messages, tools=self.tools)
            assistant_msg = {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            }
            sub_messages.append(assistant_msg)
            log_message(logger, assistant_msg)

            if response.stop_reason != "tool_use":
                break

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
            sub_messages.append(user_msg)
            log_message(logger, user_msg)
            
         # Only the final text returns to the parent -- child context is discarded
        return "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"