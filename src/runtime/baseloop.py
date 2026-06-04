from agent.baseagent import agent
from tools import run_bash

class BaseLoop:
    def __init__(self, agent, tools=None, memory=None):
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
            # Execute each tool call, collect results
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\033[33m$ {block.input['command']}\033[0m")
                    output = run_bash(block.input["command"])
                    print(output[:200])
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output
                    })
            messages.append({"role": "user", "content": results})

agent_loop = BaseLoop(agent)