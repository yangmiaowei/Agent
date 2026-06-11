from src.execution.subagent_executor import SubagentExecutor
from src.runtime.context import RuntimeContext
from src.runtime.tool_view import ToolView
from src.tools.tool_manager import ToolManager


class ToolExecutor:
    def __init__(self, executor_tm: ToolManager, subagent_executor: SubagentExecutor):
        self._tm = executor_tm
        self._subagent = subagent_executor

    def run(self, name: str, args: dict, ctx: RuntimeContext, tool_view: ToolView) -> str:
        if not tool_view.can_call(name):
            return f"Error: Tool '{name}' is not available in the current context."

        if name == "task":
            return self._subagent.run(args, ctx)

        return self._tm.call(name, args)
