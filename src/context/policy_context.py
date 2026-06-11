from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyContext:
    # 当前轮次 messages
    messages: List[dict] = field(default_factory=list)

    # model 输出的 tool blocks
    tool_blocks: List[Any] = field(default_factory=list)

    # tool 执行结果
    tool_results: List[dict] = field(default_factory=list)

    # policy 共享状态（重点）
    state: Dict[str, Any] = field(default_factory=dict)

    # 当前 round number
    round_idx: int = 0

    # debug / trace
    trace: List[dict] = field(default_factory=list)