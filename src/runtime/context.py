from dataclasses import dataclass, field


@dataclass
class RuntimeContext:
    messages: list
    round_idx: int = 0
    tags: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    mode: str = "default"
