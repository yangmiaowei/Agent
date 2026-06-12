```
session_xxx/
  events.jsonl     # 完整事件流（按时间顺序）
  subagents/
    read/
      events.jsonl # subagent 独立事件流，带 scope 标记
```

## 事件格式

同一条时间线里用 `data` 字段区分类型：

```jsonl
{"timestamp": "...", "data": {"role": "user", "content": "Build an MCP server..."}}
{"timestamp": "...", "data": {"role": "assistant", "content": {"type": "text", "text": "..."}}}
{"timestamp": "...", "data": {"role": "assistant", "content": {"type": "tool_use", "name": "bash", ...}}}
{"timestamp": "...", "data": {"event": "tool_start", "tool_name": "bash", "args": {...}}}
{"timestamp": "...", "data": {"event": "tool_end", "tool_name": "bash", "output": "...", "cost_ms": 4716}}
{"timestamp": "...", "data": {"role": "user", "content": {"type": "tool_result", ...}}}
```

判别方式：
- 有 `role` → 对话消息（user / assistant）
- 有 `event` → 工具生命周期（`tool_start` / `tool_end` / `tool_error`），含 `cost_ms`、`trace_id` 等

subagent 事件会多一个顶层 `scope` 字段，例如 `"scope": "subagent/read"`。

```
用户输入 → 助手思考 → tool_use → tool_start → tool_end → tool_result → ...
```

打开一个文件就能还原全过程。