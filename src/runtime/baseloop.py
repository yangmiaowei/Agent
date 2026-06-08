from src.agent.baseagent import agent
from src.tools.tool_manager import ToolManager, tool_manager

class BaseLoop:
    def __init__(self, agent, tools: ToolManager, memory=None):
        self.agent = agent
        self.tools = tools
        self.memory = memory

    def loop(self, messages: list):
        while True:
            response = self.agent.run(messages)
            messages.append({"role": "assistant", "content": response.content})
            
            # If the model didn't call a tool, we're done
            if response.stop_reason != "tool_use":
                return

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self.tools.call(block.name, block.input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output
                    })
            messages.append({"role": "user", "content": results})


agent_loop = BaseLoop(agent, tools=tool_manager)