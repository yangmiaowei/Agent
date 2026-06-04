#!/usr/bin/env python3
# Harness: compression -- clean memory for infinite sessions.  
# 压缩 -- 干净的记忆, 无限的会话。

# 核心不都是agent loop吗，langgraph的显式图和这个手工的agent原理上区别在哪？

# 这个：
# - LLM 决定控制流
# - 控制流隐含在 prompt + messages + 模型推理里
# - loop 本身几乎没有业务逻辑
# - runtime 更像工具执行器

# LangGraph：
# - 图已经写死（显式状态机，状态转移规则是代码定义的）
# - 图/状态机决定主流程，流向由 runtime + state 控制
# - LLM 只是某个节点里的推理组件
# - runtime 本身包含业务逻辑
"""
s06_context_compact.py - Compact

Three-layer compression pipeline so the agent can work forever:  # 三层压缩策略

    Every turn:
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        (silent, every turn)
      Replace non-read_file tool_result content older than last 3
      with "[Previous: used {tool_name}]"
            |
            v
    [Check: tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  Save full transcript to .transcripts/
                  Ask LLM to summarize conversation.
                  Replace all messages with [summary].
                        |
                        v
                [Layer 3: compact tool]
                  Model calls compact -> immediate summarization.
                  Same as auto, triggered manually.

Key insight: "The agent can forget strategically and keep working forever."
"""

import json
import os
import subprocess
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"), api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks."""

THRESHOLD = 5000  # 改小点好触发
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3
PRESERVE_RESULT_TOOLS = {"read_file"}  # source of truth


def estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars per token."""
    return len(str(messages)) // 4


# -- Layer 1: micro_compact - replace old tool results with placeholders --
def micro_compact(messages: list) -> list:
    # Collect (msg_index, part_index, tool_result_dict) for all tool_result entries
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and  part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))
    if len(tool_results) <= KEEP_RECENT:
        return messages
    # Find tool_name for each result by matching tool_use_id in prior assistant messages
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name
    # Clear old results (keep last KEEP_RECENT). Preserve read_file outputs because
    # they are reference material; compacting them forces the agent to re-read files.
    to_clear = tool_results[:-KEEP_RECENT]
    for _, _, result in to_clear:
        if not isinstance(result.get("content"), str) or len(result["content"]) <= 100:
            continue
        tool_id = result.get("tool_use_id", "")
        tool_name = tool_name_map.get(tool_id, "unknown")
        if tool_name in PRESERVE_RESULT_TOOLS:
            continue
        result["content"] = f"[Previous: used {tool_name}]"
    return messages


# -- Layer 2: auto_compact - save transcript, summarize, replace messages --
def auto_compact(messages: list) -> list:
    # Save full transcript to disk
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")
    # Ask LLM to summarize
    conversation_text = json.dumps(messages, default=str)[-80000:]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + conversation_text}],
        max_tokens=2000,
    )
    summary = response.content[0].text
    # Replace all messages with compressed summary
    return [
        {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
    ]


# -- Tool implementations --
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    # "compact":    lambda **kw: auto_compact(kw["messages"]),  # messages是agent loop的全局状态，不应该直接塞进tool
    "compact":    lambda **kw: "Manual compression requested.",
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "compact", "description": "Trigger manual conversation compression.",
    "input_schema": {"type": "object", "properties": {"focus": {"type": "string", "description": "What to preserve in the summary"}}}},
]


def agent_loop(messages: list):
    while True:
        # Layer 1: micro_compact before each LLM call
        micro_compact(messages)
        # Layer 2: auto_compact if token estimate exceeds threshold
        if estimate_tokens(messages) > THRESHOLD:
            print("[auto_compact triggered]")
            messages[:] = auto_compact(messages)  # 把 messages 这个列表里的内容，原地替换成新的内
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        manual_compact = False
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compact":
                    manual_compact = True
                    output = "Compressing..."
                else:
                    handler = TOOL_HANDLERS.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"
                print(f"> {block.name}:")
                print(str(output[:200]))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
        # Layer 3: manual compact triggered by the compact tool
        if manual_compact:
            print("[manual compact]")
            messages[:] = auto_compact(messages)
            return


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        print("\n===== FULL MESSAGES DEBUG =====")
        for i, m in enumerate(history):
            print(f"\n--- message {i} ---")
            print(m)

        # response_content = history[-1]["content"]
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
        print()


# s01 >> Read every Python file in the agents/ directory one by one
# > bash:
# find: /Users/yangmw/Personal/Works/Agent/agents/: No such file or directory
# > bash:
# __pycache__
# Agent.py
# greet.py
# LLM.py
# main.py
# mymodule
# prompt.py
# s01_agent_loop.py
# s02_tool_use.py
# s03_todo_write.py
# s04_subagent.py
# s05_skill_loading.py
# s06_context_compact.py
# skills
# task-manager-mcp

# > bash:
# /Users/yangmw/Personal/Works/Agent/Agent.py
# /Users/yangmw/Personal/Works/Agent/greet.py
# /Users/yangmw/Personal/Works/Agent/LLM.py
# /Users/yangmw/Personal/Works/Agent/main.py
# /Users/yangmw/Personal/Work
# [auto_compact triggered]
# [transcript saved: /Users/yangmw/Personal/Works/Agent/.transcripts/transcript_1778493223.jsonl]
# > read_file:
# import json5

# from LLM import OllamaChat
# from tools import Tools

# from prompt import TOOL_DESC, REACT_PROMPT


# class Agent:
#     def __init__(self) -> None:
#         self.tool = Tools()
#         self.sys
# > read_file:
# def greet(name: str) -> str:
#     """Return a greeting message for the given name.

#     Args:
#         name: The name of the person to greet.

#     Returns:
#         A greeting string in the form ``"Hello
# > read_file:
# from typing import Dict, List
# from openai import OpenAI

# class OllamaChat():
#     def __init__(self, model: str = "qwen2.5:7b") -> None:
#         self.client = OpenAI(
#             base_url="http://local
# > read_file:
# from Agent import Agent

# agent = Agent()
# response, _ = agent.text_completion(text='特朗普哪一年出生的？', history=[])
# print(response)
# > read_file:
# TOOL_DESC = """
# {name_for_model}: Call this tool to interact with the {name_for_human} API. 

# What is the {name_for_human} API useful for? {description_for_model} 

# Parameters: {parameters} Format the
# > read_file:

# > read_file:
# from Tools.datetime_tool import DatetimeTool
# from Tools.search_tool import SearchTool


# class Tools:
#     def __init__(self):
#         self.available_tools = {
#             "search": SearchTool(),
      
# > read_file:
# #!/usr/bin/env python3
# # Harness: the loop -- the model's first connection to the real world.
# """
# s01_agent_loop.py - The Agent Loop

# The entire secret of an AI coding agent in one pattern:

#     while
# > read_file:
# #!/usr/bin/env python3
# # Harness: tool dispatch -- expanding what the model can reach.
# """
# s02_tool_use.py - Tools

# The agent loop from s01 didn't change. We just added tools to the array
# and a dispat
# > read_file:
# #!/usr/bin/env python3
# # Harness: planning -- keeping the model on course without scripting the route.
# # 让模型保持在正确的轨道上，而不是事先把路线脚本化。
# """
# s03_todo_write.py - TodoWrite

# The model tracks its own progress 
# > read_file:
# #!/usr/bin/env python3
# # Harness: context isolation -- protecting the model's clarity of thought.
# # 上下文隔离，保护模型思维清晰。
# """
# s04_subagent.py - Subagents

# Spawn a child agent with fresh messages=[]. The chi
# > read_file:
# #!/usr/bin/env python3
# # Harness: on-demand knowledge -- domain expertise, loaded when the model asks.
# # "用到什么知识, 临时加载什么知识" -- 通过 tool_result 注入, 不塞 system prompt。
# # Harness 层: 按需知识 -- 模型开口要时才给的领域专长。

# > read_file:
# #!/usr/bin/env python3
# # Harness: compression -- clean memory for infinite sessions.  
# # 压缩 -- 干净的记忆, 无限的会话。

# # 核心不都是agent loop吗，langgraph的显式图和这个手工的agent原理上区别在哪？

# # 这个：
# # - LLM 决定控制流
# # - 控制流隐含在 prompt
# [auto_compact triggered]
# [transcript saved: /Users/yangmw/Personal/Works/Agent/.transcripts/transcript_1778493238.jsonl]

# ===== FULL MESSAGES DEBUG =====
# message 0 已经不是“原始历史”，而是被 compact 机制“原地改写”过的历史快照。
# --- message 0 ---
# {'role': 'user', 'content': '[Conversation compressed. Transcript: /Users/yangmw/Personal/Works/Agent/.transcripts/transcript_1778493238.jsonl]\n\n**1) What was accomplished:**\n- Read and analyzed all 4 Python files in the `skills/` directory: `minimal-agent.py` (minimal agent template), `subagent-pattern.py` (Task tool for context isolation), `tool-templates.py` (tool definitions/implementations), and `init_agent.py` (project scaffolding script).\n- Previously, a `mymodule` package was created at `/Users/yangmw/Personal/Works/Agent/mymodule/` with `greet()` in `core.py`, `format_message()` in `utils.py`, and proper `__init__.py` exports. All functions were tested and verified.\n\n**2) Current state:**\n- The agent (running `s06_context_compact.py`) has completed the file-reading task. The conversation history has grown significantly, and `micro_compact` has already replaced older tool results with `[Previous: used bash]` placeholders. The auto_compact threshold (5000 tokens) is likely approaching or exceeded.\n- The interactive prompt (`s01 >>`) is awaiting a new user command.\n\n**3) Key decisions made:**\n- `micro_compact` (Layer 1) preserves `read_file` outputs as source of truth, while replacing other old tool results with placeholders.\n- `auto_compact` (Layer 2) saves full transcripts to `.transcripts/` before summarizing, ensuring no data loss.\n- The compact tool (Layer 3) allows manual compression triggered by the model.\n- Subagents use isolated context (no parent history) to prevent context pollution, with filtered tools per agent type (e.g., "explore" is read-only).'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I can see from the conversation summary that we've been working through the Agent project, analyzing the skills directory, creating a `mymodule` package, and understanding the context compaction system. \n\nWhat would you like to do next? Some options based on where we left off:\n\n1. **Continue exploring the Agent project** - dive into other directories or files\n2. **Work on the `mymodule` package** - add more functionality or tests\n3. **Test the context compaction system** - trigger manual compaction and observe behavior\n4. **Build something new** - create a new skill, tool, or agent pattern\n5. **Something else entirely**\n\nWhat's your next command or question?", type='text')]}

# s01 >> 