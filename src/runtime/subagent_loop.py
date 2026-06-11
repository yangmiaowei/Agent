from src.tools.tool_manager import ToolManager
from src.logger.logger import log_message

# -- Subagent: fresh context, filtered tools, summary-only return --
class SubAgentLoop:
    def __init__(self, agent, tools: ToolManager, memory=None, policies=None, system_prompt=None):
        self.agent = agent
        self.tools = tools
        self.memory = memory
        self.policies = policies or []
        self.system_prompt = system_prompt

    def loop(self, prompt: str, logger=None):
        sub_messages = [{"role": "user", "content": prompt}]  # fresh context
        for _ in range(30):  # safety limit
            response = self.agent.run(sub_messages, tools=self.tools, system=self.system_prompt)
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


# 用户输入
#   → BaseLoop（主 agent，6 个工具含 Task）
#       → LLM 决定调用 task
#           → Task.run(prompt=...)
#               → SubAgentLoop（独立上下文，5 个工具，无 Task）
#                   → subagent 自己跑工具、思考
#               → 只把最终文字摘要返回给主 agent