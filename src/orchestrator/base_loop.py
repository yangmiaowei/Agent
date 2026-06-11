from src.execution.tool_executor import ToolExecutor
from src.logger.logger import log_message
from src.runtime.context import RuntimeContext
from src.runtime.resolver import RuntimePolicyEngine


class BaseLoop:
    def __init__(self, agent, runtime: RuntimePolicyEngine, executor: ToolExecutor, memory=None, policies=None):
        self.agent = agent
        self.runtime = runtime
        self.executor = executor
        self.memory = memory
        self.policies = policies or []

    def loop(self, messages: list, logger=None):
        ctx = RuntimeContext(messages=messages)

        while True:
            resolved = self.runtime.resolve(ctx)
            response = self.agent.run(
                messages,
                tools=resolved.tool_view,
                system=resolved.system_prompt,
            )
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
                        output = self.executor.run(
                            block.name,
                            block.input,
                            ctx,
                            resolved.tool_view,
                        )
                    except Exception as e:
                        output = f"Error: {e}"
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

            user_msg = {"role": "user", "content": results}
            messages.append(user_msg)
            log_message(logger, user_msg)
            ctx.round_idx += 1
