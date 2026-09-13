"""Structured result of an agent loop run."""

from dataclasses import dataclass, field

# Why the loop stopped.
STOP_END_TURN = "end_turn"       # model answered without requesting a tool
STOP_MAX_ROUNDS = "max_rounds"   # hit the round budget
STOP_ERROR = "error"             # LLM call raised after retries were exhausted
STOP_COMPACTED = "compacted"     # loop ended to hand control back after compaction


@dataclass
class LoopOutcome:
    stop_reason: str
    rounds: int
    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_errors: dict[str, int] = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def total_tool_calls(self) -> int:
        return sum(self.tool_calls.values())

    def to_dict(self) -> dict:
        return {
            "stop_reason": self.stop_reason,
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "total_tool_calls": self.total_tool_calls,
            "usage": self.usage,
            "error": self.error,
        }
