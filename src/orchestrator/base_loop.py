import logging
from collections import Counter

from src.execution.tool_executor import ToolExecutor
from src.logger.logger import log_message
from src.model.usage import Usage
from src.orchestrator.outcome import (
    STOP_END_TURN,
    STOP_ERROR,
    STOP_MAX_ROUNDS,
    LoopOutcome,
)
from src.runtime.context import RuntimeContext
from src.runtime.resolver import RuntimePolicyEngine

logger_ = logging.getLogger(__name__)


class BaseLoop:
    def __init__(self, agent, runtime: RuntimePolicyEngine, executor: ToolExecutor, memory=None, policies=None):
        self.agent = agent
        self.runtime = runtime
        self.executor = executor
        self.memory = memory
        self.policies = policies or []

    # --- extension points -------------------------------------------------
    # Subclasses customise behaviour by overriding these rather than the
    # whole loop body.

    def build_context(self, messages: list) -> RuntimeContext:
        return RuntimeContext(messages=messages)

    def before_turn(self, messages: list, *, turn: int, max_rounds: int | None, logger=None) -> None:
        """Called before each LLM call. Used for nudges and compaction."""

    def on_tool_use(self, block) -> None:
        """Called for each requested tool call before it executes."""

    def handle_tool_use(self, block, ctx, resolved) -> tuple[str, bool]:
        """Run one tool. Returns (output, should_stop_after_this_round)."""
        try:
            output = self.executor.run(block.name, block.input, ctx, resolved.tool_view)
        except Exception as e:
            output = f"Error: {e}"
        return output, False

    def after_round(self, messages: list, ctx: RuntimeContext) -> None:
        """Called after tool results are appended."""

    # --- main loop --------------------------------------------------------

    def loop(self, messages: list, logger=None, max_rounds: int | None = None) -> LoopOutcome:
        ctx = self.build_context(messages)
        turn = 0
        tool_calls: Counter = Counter()
        tool_errors: Counter = Counter()
        usage = Usage()

        while True:
            if max_rounds is not None and turn >= max_rounds:
                return self._finish(
                    STOP_MAX_ROUNDS, turn, tool_calls, tool_errors, usage, logger
                )
            turn += 1

            self.before_turn(messages, turn=turn, max_rounds=max_rounds, logger=logger)

            resolved = self.runtime.resolve(ctx)
            try:
                response = self.agent.run(
                    messages,
                    tools=resolved.tool_view,
                    system=resolved.system_prompt,
                )
            except Exception as e:
                logger_.error("LLM call failed on turn %d: %s: %s", turn, type(e).__name__, e)
                return self._finish(
                    STOP_ERROR,
                    turn - 1,
                    tool_calls,
                    tool_errors,
                    usage,
                    logger,
                    error=f"{type(e).__name__}: {e}",
                )

            turn_usage = getattr(self.agent, "last_usage", None)
            if turn_usage is not None:
                usage.add(turn_usage)
                self._log_event(
                    logger,
                    {
                        "event": "llm_call",
                        "turn": turn,
                        "stop_reason": response.stop_reason,
                        "usage": turn_usage.to_dict(),
                    },
                )

            assistant_msg = {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            }
            messages.append(assistant_msg)
            log_message(logger, assistant_msg)

            if response.stop_reason != "tool_use":
                return self._finish(
                    STOP_END_TURN, turn, tool_calls, tool_errors, usage, logger
                )

            results = []
            stop_after_round = False
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_calls[block.name] += 1
                self.on_tool_use(block)
                output, stop = self.handle_tool_use(block, ctx, resolved)
                stop_after_round = stop_after_round or stop
                if isinstance(output, str) and output.startswith("Error"):
                    tool_errors[block.name] += 1
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

            user_msg = {"role": "user", "content": results}
            messages.append(user_msg)
            log_message(logger, user_msg)
            ctx.round_idx += 1
            self.after_round(messages, ctx)

            if stop_after_round:
                return self._finish(
                    self.stop_reason_after_round(), turn, tool_calls, tool_errors, usage, logger
                )

    def stop_reason_after_round(self) -> str:
        return STOP_END_TURN

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _log_event(logger, data: dict) -> None:
        if logger:
            logger.log(data)

    def _finish(
        self,
        stop_reason: str,
        rounds: int,
        tool_calls: Counter,
        tool_errors: Counter,
        usage: Usage,
        logger,
        *,
        error: str | None = None,
    ) -> LoopOutcome:
        outcome = LoopOutcome(
            stop_reason=stop_reason,
            rounds=rounds,
            tool_calls=dict(tool_calls),
            tool_errors=dict(tool_errors),
            usage=usage.to_dict(),
            error=error,
        )
        self._log_event(logger, {"event": "loop_end", **outcome.to_dict()})
        return outcome
