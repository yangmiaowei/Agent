"""Token accounting for LLM calls."""

from dataclasses import asdict, dataclass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @classmethod
    def from_response(cls, response) -> "Usage":
        raw = getattr(response, "usage", None)
        if raw is None:
            return cls(calls=1)
        return cls(
            calls=1,
            input_tokens=getattr(raw, "input_tokens", 0) or 0,
            output_tokens=getattr(raw, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
        )

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data
