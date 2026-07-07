from dataclasses import dataclass, field

from src.memory.context_compactor import estimate_tokens, micro_compact, auto_compact


@dataclass
class RuntimeContext:
    messages: list
    round_idx: int = 0
    tags: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    mode: str = "default"

    def estimate_token_count(self) -> int:
        """估算当前上下文 token 数"""
        return estimate_tokens(self.messages)

    def compact_micro(self, keep_recent: int = 3, preserve_result_tools: list = ["read_file"]) -> None:
        """执行微观压缩，替换旧的工具结果为占位符"""
        self.messages = micro_compact(self.messages, keep_recent, preserve_result_tools)

    def compact_auto(self, transcript_dir: str) -> None:
        """执行自动压缩，保存transcript并总结"""
        self.messages = auto_compact(self.messages, transcript_dir)

    def get_compact_config(self) -> dict:
        """返回压缩配置（阈值、保留数量等）"""
        return {
            "threshold": 50000,
            "keep_recent": 3,
            "preserve_result_tools": ["read_file", "grep"],
            "transcript_dir": ".transcripts",
            "summary_max_tokens": 2000,
        }