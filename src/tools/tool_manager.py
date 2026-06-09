import uuid
import time
import copy
import traceback
from logger.logger import JsonLogger


class ToolManager:
    def __init__(self):
        self._tools = {}  # name -> tool instance
        self.logger = JsonLogger()

        # 默认全局回调
        self.default_on_start = self._default_on_start
        self.default_on_end = self._default_on_end
        self.default_on_error = self._default_on_error
    
    def _log(self, data: dict):
        self.logger.log(data)

    def _default_on_start(self, context):
        self._log({
            "event": "tool_start",
            "tool_name": context["tool_name"],
            "trace_id": context["trace_id"],
            "args": context["args"],
            "timestamp": time.time()
        })

    def _default_on_end(self, context):
        self._log({
            "event": "tool_end",
            "tool_name": context["tool_name"],
            "trace_id": context["trace_id"],
            "output": context["output"],
            "cost_ms": context["cost_ms"],
            "timestamp": time.time()
        })

    def _default_on_error(self, context):
        self._log({
            "event": "tool_error",
            "tool_name": context["tool_name"],
            "trace_id": context["trace_id"],
            "error": str(context["error"]),
            "timestamp": time.time()
        })

    def register(self, tool_cls):
        """
        动态注册工具（运行时也可以调用）
        """
        instance = tool_cls()
        name = instance.name

        if name in self._tools:
            raise ValueError(f"Tool conflict: {name}")

        self._tools[name] = instance
        return tool_cls

    def call(self, name: str, args: dict):
        """
        统一调用入口
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        trace_id = str(uuid.uuid4())
        start_time = time.time()

        args_copy = copy.deepcopy(args)

        context = {
            "tool_name": name,
            "args": args_copy,
            "trace_id": trace_id,
        }

        try:
            self.default_on_start(context)

            result = tool.run(**args)

            cost_ms = int((time.time() - start_time) * 1000)

            context.update({
                "output": result,
                "cost_ms": cost_ms
            })

            # 并发冲突
            # if hasattr(tool, "on_call_end"):
            #     tool.on_call_end(tool_name=name, output=result)

            self.default_on_end(context)

            return result

        except Exception as e:
            context.update({
                "error": {
                    "message": str(e),
                    "type": type(e).__name__,
                    "traceback": traceback.format_exc()
                },
                "cost_ms": int((time.time() - start_time) * 1000)
            })

            self.default_on_error(context)
            raise

    def list_tools(self):
        """
        给 LLM 用（tool schema / name）
        """
        return [
            {
                "name": t.name,
                "description": getattr(t, "description", ""),
                "input_schema": getattr(t, "input_schema", {})
            }
            for t in self._tools.values()
        ]


tool_manager = ToolManager()

from bootstrap import init_tools
init_tools(tool_manager)

# 初始化顺序不可控，多实例冲突等问题
# def tool(cls):
#     tool_manager.register(cls)
#     return cls