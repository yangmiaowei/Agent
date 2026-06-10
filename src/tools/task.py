from src.tools.base_tool import BaseTool

from src.tools.tool_manager import ToolManager
from src.tools.tool_loader import load_subagent_tools
from src.model.AnthropicClient import AnthropicClient
from src.agent.base_agent import BaseAgent
from src.runtime.subagent_loop import SubAgentLoop
from src.logger.logger import JsonLogger
from pathlib import Path

subagent_logger = JsonLogger(workdir=Path.cwd() / "WORKDIR" / "SubAgent")

subagent_tool_manager = ToolManager()
load_subagent_tools(subagent_tool_manager)

subagent_client = AnthropicClient(tools=subagent_tool_manager)
subagent = BaseAgent(client=subagent_client)
subagent_loop = SubAgentLoop(agent=subagent, tools=subagent_tool_manager)


class Task(BaseTool):
    name = "task"
    description = "Spawn a subagent with fresh context. It shares the filesystem but not conversation history."
    input_schema = {
        "type": "object", 
        "properties": {
            "prompt": {"type": "string"}, 
            "description": {
                "type": "string", 
                "description": "Short description of the task"
            }
        }, 
        "required": ["prompt"]
    }

    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        prompt = kwargs["prompt"]

        try:
            summary = subagent_loop.loop(prompt=prompt, logger=subagent_logger)
            return summary

        except Exception as e:
            return f"Error: {e}"