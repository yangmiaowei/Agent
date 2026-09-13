from src.memory.context_compactor import auto_compact, estimate_tokens, micro_compact
from src.orchestrator.base_loop import BaseLoop
from src.orchestrator.outcome import STOP_COMPACTED


class CompactLoop(BaseLoop):
    """BaseLoop with context compact."""

    def __init__(
        self,
        *args,
        compact_threshold: int = 50000,
        keep_recent: int = 3,
        preserve_result_tools: list[str] | None = None,
        transcript_dir: str = ".transcripts",
        summary_max_tokens: int = 2000,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.compact_threshold = compact_threshold
        self.keep_recent = keep_recent
        self.preserve_result_tools = (
            preserve_result_tools
            if preserve_result_tools is not None
            else ["read_file"]
        )
        self.transcript_dir = transcript_dir
        self.summary_max_tokens = summary_max_tokens
        self._manual_compact = False

    def before_turn(self, messages: list, *, turn: int, max_rounds: int | None, logger=None) -> None:
        # Layer 1: micro_compact before each LLM call
        micro_compact(messages, self.keep_recent, self.preserve_result_tools)
        # Layer 2: auto_compact if token estimate exceeds threshold
        if estimate_tokens(messages) > self.compact_threshold:
            self._log_event(logger, {"event": "auto_compact", "turn": turn})
            messages[:] = auto_compact(messages, self.transcript_dir)

    def handle_tool_use(self, block, ctx, resolved):
        # Layer 3: manual compact requested by the model
        if block.name == "compact":
            self._manual_compact = True
            return "Compression requested.", True
        return super().handle_tool_use(block, ctx, resolved)

    def after_round(self, messages: list, ctx) -> None:
        if self._manual_compact:
            messages[:] = auto_compact(messages, self.transcript_dir)
            self._manual_compact = False

    def stop_reason_after_round(self) -> str:
        return STOP_COMPACTED
