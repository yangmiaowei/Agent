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

    def build_context(self, messages: list) -> RuntimeContext:
        return RuntimeContext(messages=messages, mode="swe")

    def before_turn(self, messages: list, *, turn: int, max_rounds: int | None, logger=None) -> None:
        if (
            max_rounds is not None
            and not self.has_edited
            and turn == max_rounds - self._nudge_before_last_rounds + 1
        ):
            user_msg = {"role": "user", "content": FORCE_EDIT_NUDGE}
            messages.append(user_msg)
            log_message(logger, user_msg)

    def handle_tool_use(self, block, ctx, resolved):
        output, stop = super().handle_tool_use(block, ctx, resolved)
        # Only a successful edit counts: a failed edit_file must still trigger
        # the nudge, otherwise the agent can burn every remaining round on
        # edits that never apply.
        if block.name in EDIT_TOOLS and not (
            isinstance(output, str) and output.startswith("Error")
        ):
            self.has_edited = True
        return output, stop
