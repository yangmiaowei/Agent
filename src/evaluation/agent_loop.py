from src.execution.tool_executor import ToolExecutor
from src.logger.logger import log_message
from src.orchestrator.base_loop import BaseLoop
from src.runtime.context import RuntimeContext
from src.runtime.resolver import RuntimePolicyEngine

EDIT_TOOLS = frozenset({"edit_file"})

FORCE_EDIT_NUDGE = (
    "You have spent many turns exploring without editing source files. "
    "Stop exploring and use edit_file to modify an existing tracked source file now. "
    "Do not create new scripts."
)


class SweBenchLoop(BaseLoop):
    """Agent loop with edit tracking and late-stage nudges for SWE-bench."""

    def __init__(
        self,
        agent,
        runtime: RuntimePolicyEngine,
        executor: ToolExecutor,
        *,
        nudge_before_last_rounds: int = 8,
    ):
        super().__init__(agent=agent, runtime=runtime, executor=executor)
        self._nudge_before_last_rounds = nudge_before_last_rounds
        self.has_edited = False

    def loop(self, messages: list, logger=None, max_rounds: int | None = None):
        ctx = RuntimeContext(messages=messages, mode="swe")
        turn = 0

        while True:
            if max_rounds is not None and turn >= max_rounds:
                return
            turn += 1

            if (
                max_rounds is not None
                and not self.has_edited
                and turn == max_rounds - self._nudge_before_last_rounds + 1
            ):
                user_msg = {"role": "user", "content": FORCE_EDIT_NUDGE}
                messages.append(user_msg)
                log_message(logger, user_msg)

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
                    if block.name in EDIT_TOOLS:
                        self.has_edited = True
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
